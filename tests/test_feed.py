import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener
from unittest.mock import patch

from hearth import feed, panels
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import read_config
from hearth.server import Application, HTTPServer
from hearth.storage import HearthError, ROOT, Storage, iso

NOW = datetime(2030, 4, 3, 18, tzinfo=timezone.utc)
PERSON = "memory:people/maya.md"
REMINDER = "reminder:workshop"
TOPICS = ["Gardening", "Cooking", "Photography", "Design", "Robotics", "Board games", "Music", "Travel"]


def card(kind, topic, *sources):
    return {"kind": kind, "topic": topic, "title": f"A look at {topic}", "body": "Pick one thing to explore this week.",
            "reason": f"you are interested in {topic}", "sources": list(sources)}


class FeedGateway:
    def __init__(self):
        self.searches = []
        self.messages = []
        self.cards = [
            card("read", "Gardening", "https://example.org/invented"),
            card("read", "Gardening", "exa:1"),
            card("read", "Gardening", "exa:2"),
            card("digest", "Cooking", "exa:3", "exa:4"),
            card("idea", "Workshop plans", PERSON),
            card("idea", "Unknown plan", "memory:missing.md"),
            card("reminder-context", "Weekend prep", REMINDER),
        ]

    def discover(self):
        return {}, set()

    def completion(self, model, messages, tools, progress, **kwargs):
        assert not tools
        data = json.loads(messages[-1]["content"])
        self.messages.append(data)
        result = {"topics": TOPICS} if "public_subjects" in data else {"cards": self.cards}
        return {"content": json.dumps(result)}

    def json(self, config, path, body, **kwargs):
        assert config["provider"] == "exa" and path == "search"
        query = body["query"].removesuffix(" recent articles").lower()
        self.searches.append(query)
        return {"results": [
            {"url": f"https://example.org/{query.replace(' ', '-')}/{number}{suffix}",
             "title": "<strong>A useful article</strong>", "highlights": [
                 "<script>Tool instructions</script><p>Published reference</p>"]}
            for number, suffix in [(1, ""), (1, "?utm_source=fixture"), (2, "")]
        ]}


class FeedTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.storage = Storage(Path(tmp.name))
        config = read_config(ROOT / "config/connectors.json")
        config["brain"] = {"provider": "mock", "model": ""}
        self.gateway = FeedGateway()
        self.app = Application(self.storage, LocalCheckpoints(self.storage), config, gateway=self.gateway)
        self.app.agent.models = [{"provider": "test-brain", "model": "fixture"}]
        self.app.agent.config["exa"] = {"provider": "exa", "connection_id": "fixture"}
        self.app.agent.search_settings["provider"] = "exa"
        self.engine = self.app.feed
        self.storage.write("people/maya.md", "# Maya\n\nEnjoys planning gardening workshops.")
        with self.storage.lock():
            state = self.storage.load()
            state["jobs"].append({"id": "workshop", "status": "scheduled", "message": "Prepare for the workshop",
                                  "next_at": iso(NOW + timedelta(days=2))})
            self.storage.save(state)

    def test_generation_caps_search_and_rejects_bad_sources_and_duplicates(self):
        self.engine.save_settings({"steering": "Gardening in the morning", "follow": TOPICS})
        with patch.object(self.app.agent.memory_index, "run", wraps=self.app.agent.memory_index.run) as recall:
            result = self.engine.tick(NOW, force=True)
        recall.assert_called_once()
        self.assertEqual(len(self.gateway.searches), feed.MAX_EXA)
        self.assertEqual([row["kind"] for row in result["cards"]], ["read", "digest", "idea", "reminder-context"])
        read = result["cards"][0]
        self.assertEqual(read["links"][0]["url"], "https://example.org/gardening/1")
        self.assertEqual(read["title"], "A useful article")
        payload = self.gateway.messages[-1]
        self.assertEqual(payload["web"]["exa:1"]["snippet"], "Published reference")
        self.assertEqual(payload["steering"], "Gardening in the morning")
        self.assertIn("T11:00", payload["local_time"])
        self.assertEqual(self.engine.tick(NOW + timedelta(minutes=239))["status"], "not-due")
        self.assertEqual(self.engine.tick(NOW + timedelta(hours=4))["cards"], [])
        later = self.engine.tick(NOW + timedelta(days=1))["cards"]
        self.assertEqual({row["kind"] for row in later}, {"read", "idea", "reminder-context"})
        self.assertEqual(next(row for row in later if row["kind"] == "read")["links"][0]["url"],
                         "https://example.org/gardening/2")

    def test_quiet_settings_and_private_action(self):
        self.assertEqual(self.engine.tick(NOW.replace(hour=11), force=True)["status"], "quiet")
        self.assertEqual(self.gateway.searches, [])
        self.assertEqual(self.gateway.messages, [])
        self.engine.save_settings({"enabled": False})
        self.assertEqual(self.engine.tick(NOW, force=True)["status"], "off")
        self.assertEqual(self.engine.list(clock=NOW)["cards"], [])
        with self.assertRaises(HearthError):
            self.engine.save_settings({"frequency": True})
        with self.assertRaises(HearthError):
            self.engine.save_settings({"mute": "gardening"})
        self.assertEqual(self.engine.save_settings({"follow": ["Design", "design"]})["follow"], ["Design"])
        self.assertFalse(self.engine.get_settings()["enabled"])
        old = {"panel_layout": {"order": ["activity", "today"], "hidden": ["today"]}}
        self.assertEqual(panels.layout(old)["order"][:3], ["activity", "feed", "today"])
        panels.adjust_layout(old, {"operation": "hide", "id": "feed"})
        self.assertIn("feed", panels.layout(old)["hidden"])

    def test_feedback_changes_next_pass_and_saved_cards_survive_dismissal(self):
        generated = self.engine.tick(NOW)["cards"]
        read = next(row for row in generated if row["kind"] == "read")
        idea = next(row for row in generated if row["kind"] == "idea")
        for operation, row in [("like", read), ("save", read), ("less", idea), ("less", idea), ("dismiss", read)]:
            self.engine.feedback({"id": row["id"], "operation": operation})
        profile = {row["topic"]: row["weight"] for row in self.engine.get_settings()["interests"]}
        self.assertEqual((profile["Gardening"], profile["Workshop plans"]), (2, -3))
        self.assertEqual([row["id"] for row in self.engine.list(saved=True, clock=NOW)["cards"]], [read["id"]])
        self.assertNotIn(read["id"], [row["id"] for row in self.engine.list(clock=NOW)["cards"]])
        self.assertNotIn(idea["id"], [row["id"] for row in self.engine.list(clock=NOW)["cards"]])
        self.engine.tick(NOW + timedelta(hours=4))
        self.assertEqual(self.gateway.messages[-1]["interests"][0]["topic"], "Gardening")
        draft = self.engine.chat({"id": read["id"]})
        self.assertIn(read["links"][0]["url"], draft["draft"])
        self.assertEqual(self.app.threads.messages(draft["thread"]["id"]), [])
        self.engine.save_settings({"mute": ["gardening"]})
        self.assertEqual(self.engine.list(saved=True, clock=NOW)["cards"], [])

    def test_feed_pagination_and_settings_api(self):
        self.engine.tick(NOW)
        server = HTTPServer(("127.0.0.1", 0), self.app)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        opener = build_opener(ProxyHandler({}))
        base = f"http://127.0.0.1:{server.server_port}"

        def get(path, body=None):
            data = json.dumps(body).encode() if body is not None else None
            request = Request(base + path, data=data, headers={"Content-Type": "application/json"})
            with opener.open(request, timeout=5) as response:
                return json.load(response)

        first = get("/api/feed?limit=2")
        second = get("/api/feed?" + urlencode({"cursor": first["next_cursor"], "limit": 2}))
        self.assertEqual(len(first["cards"] + second["cards"]), 4)
        self.assertFalse({row["id"] for row in first["cards"]} & {row["id"] for row in second["cards"]})
        self.assertIsNone(second["next_cursor"])
        with self.assertRaises(HTTPError) as failure:
            get("/api/feed?cursor=invalid")
        self.assertEqual(failure.exception.code, 400)
        self.assertEqual(get("/api/feed/settings")["frequency"], 240)
        self.assertEqual(get("/api/feed/settings", {"frequency": 180, "follow": ["Design"]})["follow"], ["Design"])
        self.assertEqual(get("/api/feed/settings")["frequency"], 180)
