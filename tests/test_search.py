import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from urllib.error import HTTPError

from hearth.agent import Agent
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import Gateway, read_config
from hearth.search import PROVIDERS, settings
from hearth.storage import HearthError, ROOT, Storage


class MockHTTP:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        response = next(self.responses)
        if isinstance(response, int):
            raise HTTPError(request.full_url, response, "error", {}, io.BytesIO(b"{}"))
        return io.BytesIO(json.dumps(response).encode())


class SearchTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.storage = Storage(scratch.name)
        self.checkpoints = LocalCheckpoints(self.storage)
        self.config = read_config(ROOT / "config/connectors.json")

    def agent(self, providers, responses, **selection):
        self.config["gateway"] = {name: {"provider": name, "connection_id": "demo-connector"} for name in providers}
        self.config["search"] = settings(selection)
        http = MockHTTP(responses)
        gateway = Gateway()
        gateway.opener = http
        return Agent(self.storage, self.checkpoints, self.config, gateway), http

    def test_each_adapter_builds_the_gateway_request_and_normalizes_http_results(self):
        url = "https://docs.example.org/manual"
        published = datetime.now(timezone.utc).date().isoformat()
        samples = {
            "tavily": ("search", {"results": [{"title": "Manual", "url": url, "content": "excerpt",
                                               "published_date": published}]},
                       ["max_results", "time_range", "safe_search", "include_domains"]),
            "exa": ("search", {"results": [{"title": "Manual", "url": url, "highlights": ["excerpt"],
                                            "publishedDate": published}]},
                    ["numResults", "startPublishedDate", "includeDomains"]),
            "linkup": ("v1/search", {"results": [{"name": "Manual", "url": url, "content": "excerpt",
                                                 "publishedAt": published}]},
                       ["maxResults", "fromDate", "includeDomains"]),
            "kagi": ("api/v1/search", {"data": {"search": [{"title": "Manual", "url": url, "snippet": "excerpt",
                                                           "time": published}]}},
                     ["limit", "filters", "lens"]),
            "keenable": ("v1/search", {"results": [{"title": "Manual", "url": url, "snippet": "excerpt",
                                                   "published_at": published}]},
                         ["max_results", "published_after", "site", "moderation"]),
            "firecrawl": ("v2/search", {"success": True, "data": {"web": [
                {"title": "Manual", "url": url, "description": "excerpt", "date": published}
            ]}}, ["limit", "tbs", "safe", "includeDomains"]),
        }
        for provider, (path, data, fields) in samples.items():
            with self.subTest(provider=provider):
                agent, http = self.agent([provider], [data], provider=provider, recency="year",
                                        max_results=1, safe_search=True, include_domains=["example.org"])
                result = agent.web_search("where is the manual")
                self.assertEqual(result["results"], [
                    {"title": "Manual", "url": url, "snippet": "excerpt", "published": published}
                ])
                self.assertEqual(result["provider"], provider)
                self.assertGreaterEqual(result["latency_ms"], 0)
                (request, timeout), = http.requests
                self.assertEqual(request.full_url, f"https://api.sprites.dev/v1/gateway/{provider}/demo-connector/{path}")
                self.assertEqual(request.get_method(), "POST")
                self.assertEqual(timeout, 12)
                self.assertIsNone(request.get_header("Authorization"))
                body = json.loads(request.data)
                self.assertEqual(body.get("query", body.get("q")), "where is the manual")
                self.assertTrue(set(fields) <= body.keys())

    def test_auto_fallback_records_timeline_and_applies_local_filters(self):
        raw = {"results": [
            {"url": "https://example.org.evil/"},
            {"url": "https://skip.example.org/"},
            {"url": "https://example.org/too-old", "publishedDate": "1999-12-01"},
            {"url": "https://example.org/adult", "nsfw": True},
            {"url": "javascript:alert(1)"},
            {"url": "https://keep.example.org/manual", "title": "Manual"},
            {"url": "https://keep.example.org/extra", "title": "Second manual"},
        ]}
        agent, http = self.agent(PROVIDERS, [503, raw], safe_search=True, max_results=1, recency="week",
                                include_domains=["example.org"], exclude_domains=["skip.example.org"])
        result = agent.web_search("manual")
        self.assertEqual(result["provider"], "exa")
        self.assertEqual([row["title"] for row in result["results"]], ["Manual"])
        self.assertIn("503", result["warnings"][0])
        self.assertIn("basic result filter", result["warnings"][1])
        action, = self.storage.load()["actions"].values()
        self.assertEqual(action["title"], "Search fallback")
        self.assertIn("Trying Exa", action["detail"])
        self.assertEqual(len(http.requests), 2)

    def test_off_and_disconnected_are_not_available_as_brain_tools(self):
        for selection, providers, active in [("off", ["exa"], False), ("auto", [], False), ("auto", ["exa"], True)]:
            with self.subTest(selection=selection, providers=providers):
                agent, http = self.agent(providers, [], provider=selection)
                definitions = []

                def completion(model, messages, tools, emit):
                    definitions.extend(tool["function"]["name"] for tool in tools)
                    return {"role": "assistant", "content": "Done"}

                agent.tools.gateway.completion = completion
                agent.models = [{"provider": "huggingface", "model": "test-brain", "connection_id": "demo"}]
                agent.chat("A message", lambda *_: None)
                self.assertEqual("web_search" in definitions, active)
                self.assertEqual(http.requests, [])
                if not active:
                    with self.assertRaisesRegex(HearthError, "off|Connect in Settings → Connections"):
                        agent.web_search("where is the manual")

    def test_invalid_options_are_rejected(self):
        for selection in [{"provider": "apify"}, {"max_results": 0}, {"safe_search": 1},
                          {"include_domains": ["https://example.org"]}]:
            with self.subTest(selection=selection), self.assertRaises(HearthError):
                settings(selection)
