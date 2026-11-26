import io
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from hearth.checkpoints import LocalCheckpoints
from hearth.browserbase import TEST_PATH
from hearth.connections import CATALOG, HEALTH_TTL
from hearth.connectors import CORE_PROVIDERS, GATEWAY, ConnectorError, Gateway, read_config
from hearth.server import Application, HTTPServer
from hearth.storage import HearthError, ROOT, Storage


class FakeGateway(Gateway):
    def __init__(self):
        self.entries = []
        self.probes = []
        self.fail_discovery = False
        self.denied = set()
        self.offline = set()
        self.missing = set()
        self.completions = []
        self.methods = []
        self.unset = list(CORE_PROVIDERS)
        self.failed_models = set()
        self.seen_tools = []

    def request(self, path, body, headers, timeout, *, method=None):
        if path == "list":
            if self.fail_discovery:
                raise ConnectorError("private upstream details", 502)
            payload = {"connections": self.entries, "available": [{"provider": p} for p in self.unset]}
        else:
            if path == f"browserbase/{TEST_PATH}":
                raise ConnectorError("No org-level connection.", 404, missing_connection=True)
            provider, connection_id, endpoint = path.split("/", 2)
            self.probes.append((provider, connection_id, endpoint, body))
            self.methods.append((method or ("GET" if body is None else "POST"), headers))
            if provider in self.denied:
                raise ConnectorError("private upstream details", 403)
            if provider in self.offline:
                raise ConnectorError("private upstream details", 503)
            if provider in self.missing:
                raise ConnectorError("private upstream details", 404, missing_connection=True)
            if provider == "meta":
                payload = {"choices": [{"message": {"content": "OK"}}]}
            elif provider == "huggingface" and endpoint == "v1/models":
                payload = {"data": [
                    {"id": "Qwen/Qwen3-Coder-Next", "architecture": {"output_modalities": ["text"]}},
                    {"id": "Qwen/Qwen3-Embedding", "pipeline_tag": "feature-extraction"},
                    {"id": "image-generator", "architecture": {"output_modalities": ["image"]}},
                ]}
            elif provider == "pinecone":
                payload = {"name": endpoint.removeprefix("indexes/")}
            elif provider == "tavily":
                payload = {"results": []}
            elif provider == "exa":
                payload = {"results": []}
            elif provider == "browserbase":
                payload = []
            elif endpoint.startswith("v0/inboxes?"):
                payload = {"inboxes": []}
            else:
                payload = {"inbox_id": "demo@agentmail.to"}
        return io.BytesIO(json.dumps(payload).encode())

    def add(self, provider, connection_id):
        self.entries.append({
            "provider": provider, "gateway_base_url": f"{GATEWAY}/{provider}/{connection_id}",
            "usage_snippet": "upstream metadata that should never appear in the app or on disk",
        })

    def completion(self, config, messages, tools, emit):
        self.completions.append(config["connection_id"])
        self.seen_tools = tools
        if {config["provider"], config["model"]} & self.failed_models:
            raise ConnectorError("Private upstream model details", 503)
        emit("Muse Spark replied")
        return {"role": "assistant", "content": "Muse Spark replied"}


class DiscoveryTest(unittest.TestCase):
    def test_discovery_distinguishes_catalog_and_validates_urls(self):
        gateway = FakeGateway()
        gateway.add("meta", "conn_meta")
        gateway.add("fresh_provider", "conn_new")
        gateway.unset.append("future_provider")
        gateway.entries.extend([
            {"provider": "pinecone", "authorized": False, "gateway_base_url": f"{GATEWAY}/pinecone/conn_old"},
            {"provider": "tavily", "gateway_base_url": "https://example.com/v1/gateway/tavily/conn_outside"},
            {"provider": "tavily", "gateway_base_url": f"{GATEWAY}/agentmail/conn_wrong"},
            {"provider": "tavily", "gateway_base_url": f"{GATEWAY}/tavily/conn_extra/private"},
            {"provider": "tavily", "gateway_base_url": f"{GATEWAY}/tavily/conn_query?key=sensitive"},
        ])
        authorized, found = gateway.discover()
        self.assertEqual(authorized, {"meta": ["conn_meta"], "pinecone": [], "tavily": [], "agentmail": [],
                                      "fresh_provider": ["conn_new"], "future_provider": []})
        self.assertEqual(found, {"meta", "pinecone", "tavily", "fresh_provider"})

    def test_machines_preset_uses_custom_api_gateway_slug(self):
        gateway = FakeGateway()
        gateway.add("custom_api", "conn_fly")
        gateway.entries[-1]["provider_info"] = {"base_api_url": "https://api.machines.dev"}
        gateway.add("custom_api", "conn_other")
        authorized, found = gateway.discover()
        self.assertEqual(authorized["fly_machines"], ["conn_fly"])
        self.assertEqual(authorized["custom_api"], ["conn_other"])
        self.assertTrue({"fly_machines", "custom_api"} <= found)

    def test_gateway_requests_are_credential_free_and_read_methods_have_no_body(self):
        class Opener:
            def open(self, request, timeout):
                self.request = request
                return io.BytesIO(b'{"connections": []}')

        gateway = Gateway()
        opener = gateway.opener = Opener()
        gateway.discover()
        self.assertEqual(opener.request.full_url, f"{GATEWAY}/list")
        self.assertEqual(opener.request.get_method(), "GET")
        gateway.json({"provider": "pinecone", "connection_id": "conn_example"}, "indexes/hearth-memory",
                     headers={"Authorization": "discard", "Api-Key": "discard", "X-Pinecone-Api-Version": "2025-10"})
        self.assertEqual(opener.request.full_url, f"{GATEWAY}/pinecone/conn_example/indexes/hearth-memory")
        self.assertEqual(opener.request.get_method(), "GET")
        self.assertIsNone(opener.request.data)
        self.assertEqual(dict(opener.request.header_items()), {"X-pinecone-api-version": "2025-10"})

    def test_gateway_distinguishes_missing_connection_from_missing_resource(self):
        class Opener:
            def open(self, request, timeout):
                raise HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO(self.payload))

        gateway = Gateway()
        gateway.opener = opener = Opener()
        for message, missing in (("no browserbase connection configured for this organization", True),
                                 ("session not found", False)):
            opener.payload = json.dumps({"error": message}).encode()
            with self.assertRaises(ConnectorError) as received:
                gateway.request(f"browserbase/{TEST_PATH}", None, None, 1)
            self.assertEqual(received.exception.missing_connection, missing)


class ConnectionsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.storage = Storage(temporary.name)
        self.path = self.storage.live / "connectors.local.json"
        self.checkpoints = LocalCheckpoints(self.storage)
        self.gateway = FakeGateway()
        self.config = read_config(ROOT / "config/connectors.json")
        self.app = Application(self.storage, self.checkpoints, self.config, gateway=self.gateway)

    def checkpoint_copy(self, checkpoint):
        path = self.checkpoints.root / checkpoint["id"] / "live" / self.path.name
        return json.loads(path.read_text()) if path.exists() else None

    def test_discovery_saves_ids_once_and_activates_and_revokes_muse_spark(self):
        self.gateway.add("meta", "conn_meta")
        self.gateway.add("meta", "conn_later")
        self.gateway.add("pinecone", "conn_index")
        self.gateway.add("tavily", "conn_search")
        self.gateway.add("agentmail", "conn_inbox")
        self.gateway.entries[-2]["authorized"] = False
        self.app.scan_connections()
        snapshot = self.app.connection_info()
        self.assertEqual(snapshot["model"], "meta")
        self.assertEqual({p: snapshot["providers"][p]["status"] for p in CORE_PROVIDERS},
                         {"meta": "connected", "pinecone": "connected", "tavily": "unauthorized", "agentmail": "connected"})
        self.assertFalse(self.app.agent.tools.has_mail())
        self.assertEqual(self.gateway.probes, [])

        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["llm"][0]["connection_id"], "conn_later")
        self.assertEqual(saved["tavily"]["connection_id"], "")
        self.assertNotIn("usage_snippet", self.path.read_text())
        self.assertNotIn("conn_", json.dumps(snapshot))
        checkpoints = self.checkpoints.list()
        self.assertEqual(len(checkpoints), 1)
        self.assertIsNone(self.checkpoint_copy(checkpoints[0]))

        self.gateway.add("meta", "conn_a")
        self.app.scan_connections()
        self.assertEqual(len(self.checkpoints.list()), 1)
        self.assertEqual(json.loads(self.path.read_text())["llm"][0]["connection_id"], "conn_later")

        self.gateway.fail_discovery = True
        self.app.scan_connections()
        self.assertEqual(self.app.brain, "meta")
        self.assertIsNotNone(self.app.connection_info()["scan_error"])
        self.assertNotIn("private upstream details", str(self.app.connection_info()))

        self.gateway.fail_discovery = False
        self.gateway.entries = [entry for entry in self.gateway.entries if entry["provider"] != "meta"]
        self.app.scan_connections()
        self.assertEqual(self.app.brain, "mock")
        row = self.app.connection_info()["providers"]["meta"]
        self.assertEqual(row["status"], "unauthorized")
        self.assertFalse(row["can_test"])
        self.assertEqual(len(self.checkpoints.list()), 1)

    def test_empty_catalog_and_checkpoint_failure(self):
        self.app.scan_connections()
        self.assertEqual({row["status"] for row in self.app.connection_info()["providers"].values()}, {"not_set_up"})
        self.assertFalse(self.path.exists())

        def fail_checkpoint(comment):
            self.assertFalse(self.path.exists())
            raise HearthError("private checkpoint details")

        self.checkpoints.create = fail_checkpoint
        self.gateway.add("meta", "conn_meta")
        self.app.scan_connections()
        self.assertFalse(self.path.exists())
        self.assertEqual(self.app.brain, "mock")
        self.assertIn("checkpoint", self.app.connection_info()["scan_error"])
        self.assertNotIn("private checkpoint details", self.app.connection_info()["scan_error"])
        with self.assertRaises(HearthError):
            self.app.connections.save("pinecone", "another-index")
        self.assertFalse(self.path.exists())

    def test_catalog_pins_essentials_and_preserves_unknown_discovery_results(self):
        self.gateway.add("extra_tools", "conn_tools")
        self.gateway.unset.append("future_tools")
        self.gateway.entries.append({"provider": "denied_tools", "authorized": False})
        self.gateway.add("notion", "conn_notes")
        self.app.scan_connections()
        providers = self.app.connection_info()["providers"]
        self.assertEqual(len(CATALOG), 61)
        self.assertEqual(list(providers)[:4], list(CORE_PROVIDERS))
        self.assertEqual([p for p, row in providers.items() if row["pinned"]], list(CORE_PROVIDERS))
        self.assertEqual(providers["extra_tools"]["status"], "connected")
        self.assertEqual(providers["future_tools"]["status"], "not_set_up")
        self.assertEqual(providers["denied_tools"]["status"], "unauthorized")
        self.assertEqual(providers["extra_tools"]["access_rule"], "Name Prefix hearth")
        self.assertTrue(providers["extra_tools"]["can_test"])
        self.app.connections.test("notion")
        self.assertEqual(self.gateway.methods[-1], ("GET", {"Notion-Version": "2026-03-11"}))
        self.assertEqual(self.gateway.probes[-1][2:], ("v1/users/me", None))
        with self.assertRaises(HearthError):
            self.app.connections.test("future_tools")
        self.gateway.entries = [entry for entry in self.gateway.entries if entry["provider"] != "extra_tools"]
        self.app.scan_connections()
        self.assertEqual(self.app.connection_info()["providers"]["extra_tools"]["status"], "unauthorized")
        self.assertNotIn("extra_tools", self.app.agent.tools.config["gateway"])

    def test_configured_connectors_report_uses_and_keep_failed_tests_in_configured(self):
        self.app.scan_connections()
        self.assertEqual(self.app.connection_info()["providers"]["huggingface"]["status"], "not_set_up")
        for provider in ("huggingface", "exa", "pinecone", "agentmail", "codex"):
            self.gateway.add(provider, f"conn_{provider}")
        self.app.scan_connections()
        rows = self.app.connection_info()["providers"]
        self.assertEqual({provider: row["uses"] for provider, row in rows.items() if row["status"] == "connected"}, {
            "huggingface": ["Brain", "Memory", "Voice", "Tools"], "exa": ["Search", "Tools"],
            "pinecone": ["Memory", "Tools"], "agentmail": ["Reminders", "Inbox", "Tools"], "codex": [],
        })
        self.assertTrue(all(row["can_test"] for row in rows.values() if row["status"] == "connected"))
        self.assertIsNone(rows["huggingface"]["test_status"])
        self.app.connections.test("huggingface")
        self.app.connections.test("exa")
        self.assertEqual(self.gateway.probes, [
            ("huggingface", "conn_huggingface", "v1/models", None),
            ("exa", "conn_exa", "search", {"query": "example.com", "numResults": 1}),
        ])
        self.assertEqual(self.app.connections.report()["providers"]["exa"]["test_status"], "passed")

        self.gateway.denied.add("huggingface")
        self.app.connections.test("huggingface")
        self.gateway.denied.add("exa")
        self.gateway.entries = [entry for entry in self.gateway.entries if entry["provider"] != "exa"]
        self.app.connections.test("exa")
        self.gateway.add("exa", "conn_replacement")
        rows = self.app.connections.report()["providers"]
        for provider in ("huggingface", "exa"):
            self.assertEqual((rows[provider]["status"], rows[provider]["test_status"]), ("connected", "denied"))
        self.app.scan_connections()
        self.assertEqual(self.app.connection_info()["providers"]["huggingface"]["test_status"], "denied")
        self.assertIsNone(self.app.connection_info()["providers"]["exa"]["test_status"])

    def test_home_probes_live_provider_health_with_expiring_cache(self):
        for name in ("browserbase", "exa", "box", "apify", "fresh_provider"):
            self.gateway.add(name, f"conn_{name}")
        self.gateway.missing.add("browserbase")
        self.gateway.offline.add("box")
        self.gateway.denied.add("apify")

        def statuses():
            pinecone = self.app.memory_index.pinecone_status(self.app.agent.config)
            return {row["id"]: row["status"] for row in self.app.connections.health(pinecone)["items"]}

        with patch("hearth.connections.time.monotonic", return_value=100) as clock:
            self.app.scan_connections()
            providers = self.app.connection_info()["providers"]
            for name in ("apify", "fresh_provider"):
                self.assertEqual(providers[name]["status"], "connected")
                self.assertEqual(providers[name]["uses"], [])
            self.assertEqual(statuses(), {"browserbase": "not_connected", "exa": "ok", "box": "error"})
            self.assertCountEqual(self.gateway.probes, [
                ("browserbase", "conn_browserbase", TEST_PATH, None),
                ("exa", "conn_exa", "search", {"query": "example.com", "numResults": 1}),
                ("box", "conn_box", "2.0/users/me", None),
            ])
            self.gateway.missing.clear()
            self.gateway.offline.clear()
            clock.return_value += HEALTH_TTL - 1
            self.assertEqual(statuses()["browserbase"], "not_connected")
            self.assertEqual(len(self.gateway.probes), 3)
            clock.return_value += 1
            self.assertEqual(statuses(), {"browserbase": "ok", "exa": "ok", "box": "ok"})
            self.assertEqual(len(self.gateway.probes), 6)
            self.gateway.entries = [entry for entry in self.gateway.entries if entry["provider"] != "exa"]
            self.gateway.add("exa", "conn_replacement")
            self.gateway.missing.add("exa")
            self.app.scan_connections()
            self.assertEqual(statuses()["exa"], "not_connected")
            self.assertEqual(self.gateway.probes[-1][1], "conn_replacement")

    def test_browserbase_rescan_refreshes_both_views_and_the_agent(self):
        self.gateway.add("browserbase", "conn_browserbase")
        self.gateway.denied.add("browserbase")

        def statuses():
            card = self.app.connection_info()["providers"]["browserbase"]
            home = self.app.home.snapshot()["builtin"]["connections"]["items"]
            health = next(row for row in home if row["id"] == "browserbase")
            return card["status"], card["test_status"], health["status"]

        self.app.scan_connections()
        self.assertEqual(statuses(), ("unauthorized", "denied", "error"))
        self.gateway.denied.clear()
        self.app.scan_connections()
        self.assertEqual(statuses(), ("connected", "passed", "ok"))
        self.assertEqual(self.app.agent.browser.connection["connection_id"], "conn_browserbase")

        self.gateway.offline.add("browserbase")
        self.app.connections.test("browserbase")
        self.app.connection_state = self.app.connections.report()
        self.assertEqual(statuses(), ("connected", "failed", "error"))
        self.assertTrue(all(probe == ("browserbase", "conn_browserbase", TEST_PATH, None)
                            for probe in self.gateway.probes))

    def test_llm_selection_uses_discovery_and_preserves_successful_fallback_on_rescan(self):
        for provider in ("ollama", "gemini", "anthropic", "openai", "openrouter", "meta"):
            self.gateway.add(provider, f"conn_{provider}")
        self.app.scan_connections()
        self.assertEqual(self.app.agent.brain_mode, "smart")
        self.app.connections.save_brain({"provider": "priority", "model": ""}, None)
        self.app.reload_agent()
        self.assertEqual([model["provider"] for model in self.app.agent.models],
                         ["meta", "openrouter", "openai", "anthropic", "gemini", "ollama", "mock"])
        self.gateway.failed_models.update(("meta", "openrouter", "openai", "anthropic"))
        events = []
        self.app.agent.chat("Hello", lambda name, data: events.append((name, data)))
        self.assertEqual((events[-1][0], events[-1][1]["provider"]), ("done", "gemini"))
        self.assertEqual(self.gateway.completions, ["conn_meta", "conn_openrouter", "conn_openai",
                                                     "conn_anthropic", "conn_gemini"])
        self.app.brain = "gemini"  # The HTTP stream records the provider from the done event.
        self.app.scan_connections()
        self.assertEqual(self.app.brain, "gemini")

    def test_http_settings_test_and_chat_use_hot_reloaded_config(self):
        self.gateway.add("agentmail", "conn_inbox")
        self.gateway.add("meta", "conn_meta")
        server = HTTPServer(("127.0.0.1", 0), self.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        opener = build_opener(ProxyHandler({}))

        def request(path, data=None, headers=None):
            req = Request(base + path, json.dumps(data).encode() if data is not None else None,
                          {"Content-Type": "application/json", **(headers or {})})
            with opener.open(req, timeout=5) as response:
                if response.headers.get_content_type() == "text/event-stream":
                    return response.read().decode()
                return json.load(response)

        self.assertEqual(request("/api/connections")["model"], "mock")
        self.assertEqual(request("/api/connections/rescan", {})["model"], "meta")
        self.assertEqual(request("/api/state")["model"], "meta")
        self.assertIn("Muse Spark replied", request("/api/chat", {"message": "Hello"}))
        self.assertEqual(self.gateway.completions, ["conn_meta"])

        request("/api/connections/settings", {"provider": "pinecone", "value": "custom-index"})
        request("/api/connections/settings", {"provider": "agentmail", "value": "demo@agentmail.to"})
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["pinecone"]["index"], "custom-index")
        self.assertEqual(saved["agentmail"]["inbox_id"], "demo@agentmail.to")
        self.assertTrue(self.app.agent.tools.has_mail())
        snapshots = [self.checkpoint_copy(item) for item in self.checkpoints.list()]
        self.assertTrue(any(s and s["pinecone"]["index"] == "custom-index" and not s["agentmail"]["inbox_id"]
                            for s in snapshots))
        before = len(self.gateway.probes)
        self.gateway.offline.add("agentmail")
        snapshot = request("/api/connections/test", {"provider": "agentmail"})
        self.assertEqual(snapshot["providers"]["agentmail"]["status"], "connected")
        self.assertEqual(snapshot["providers"]["agentmail"]["test_status"], "failed")
        self.assertEqual(len(self.gateway.probes), before + 1)
        self.assertEqual(self.gateway.probes[-1], ("agentmail", "conn_inbox", "v0/inboxes/demo%40agentmail.to", None))
        self.assertTrue(self.app.agent.tools.has_mail())

        for body, headers in [
            ({"provider": "agentmail", "value": "invalid"}, {}),
            ({"provider": [], "value": "invalid"}, {}),
            ({"provider": "pinecone", "value": "other-index", "api_key": "discard"}, {}),
            ({"provider": "pinecone", "value": "other-index"}, {"Sec-Fetch-Site": "cross-site"}),
        ]:
            with self.assertRaises(HTTPError) as error:
                request("/api/connections/settings", body, headers)
            self.assertEqual(error.exception.code, 403 if headers else 400)
        self.assertEqual(json.loads(self.path.read_text()), saved)

        self.gateway.add("huggingface", "conn_hf")
        self.gateway.add("codex", "conn_codex")
        request("/api/connections/rescan", {})
        brain = request("/api/brain")
        self.assertEqual(brain["selection"]["provider"], "auto")
        self.assertEqual({row["provider"]: row["supported"] for row in brain["providers"]},
                         {"meta": True, "huggingface": True, "codex": False})
        listing = request("/api/brain/models?provider=huggingface")
        self.assertEqual(listing["models"], ["Qwen/Qwen3-Coder-Next:fastest"])
        self.assertTrue(request("/api/connections")["providers"]["huggingface"]["can_test"])
        self.assertEqual(request("/api/connections/test", {"provider": "huggingface"})
                         ["providers"]["huggingface"]["test_status"], "passed")
        snapshots_before = len(self.checkpoints.list())
        selection = {"provider": "huggingface", "model": "Qwen/explicit-override:fastest"}
        state_before_test = request("/api/state")
        result = request("/api/brain/test", selection)
        self.assertEqual(result["model"], selection["model"])
        self.assertGreaterEqual(result["latency_ms"], 0)
        self.assertEqual(self.gateway.seen_tools, [])
        self.assertEqual(request("/api/state"), state_before_test)
        self.assertEqual(len(self.checkpoints.list()), snapshots_before)
        brain = request("/api/brain/settings", selection)
        self.assertEqual(brain["selection"], selection)
        self.assertEqual(request("/api/state")["model"], "huggingface")
        self.assertEqual(self.app.agent.models[0]["model"], selection["model"])
        self.assertEqual(json.loads(self.path.read_text())["brain"], selection)
        self.assertEqual(len(self.checkpoints.list()), snapshots_before + 1)
        self.assertTrue(any(snapshot and snapshot["brain"]["provider"] == "auto"
                            for snapshot in map(self.checkpoint_copy, self.checkpoints.list())))
        request("/api/connections/rescan", {})
        self.assertEqual(request("/api/brain")["selection"], selection)

        self.gateway.failed_models.add("huggingface")
        stream = request("/api/chat", {"message": "Hello"})
        self.assertIn("Hugging Face could not reply. The gateway returned HTTP 503. Trying Meta Muse Spark.", stream)
        self.assertNotIn("Private upstream model details", stream)
        state = request("/api/state")
        self.assertEqual(state["model"], "meta")
        self.assertEqual(state["messages"][-1]["notices"], [state["actions"][-1]["detail"]])
        self.assertEqual(state["actions"][-1]["title"], "Brain fallback")
        self.assertEqual(request("/api/brain")["selection"], selection)

        request("/api/brain/settings", {"provider": "mock", "model": ""})
        self.assertEqual([entry["provider"] for entry in self.app.agent.models], ["mock"])
        request("/api/brain/settings", {"provider": "auto", "model": ""})
        self.assertEqual(request("/api/state")["model"], "huggingface")

        self.gateway.failed_models.clear()
        coder = "Qwen/Qwen3-Coder-Next:fastest"
        fast = "deepseek-ai/DeepSeek-V4.1-Flash:fastest"
        pool = [{"provider": "huggingface", "model": model} for model in (coder, fast)]
        smart = {"provider": "smart", "model": "", "pool": pool}
        before = self.gateway.completions.copy()
        preview = request("/api/brain/route", {**smart, "prompt": "Remind me to call home."})
        self.assertEqual((preview["test"]["class"], preview["test"]["order"][0]["model"]), ("tool", fast))
        self.assertEqual(len(preview["preview"]), 8)
        self.assertEqual(self.gateway.completions, before)
        with self.assertRaises(HTTPError) as error:
            request("/api/brain/settings", {**smart, "pool": [pool[0], pool[0]]})
        self.assertEqual(error.exception.code, 400)

        request("/api/brain/settings", smart)
        request("/api/connections/rescan", {})
        self.assertEqual([row["model"] for row in request("/api/brain")["pool"]], [coder, fast])
        self.gateway.failed_models.add(fast)
        stream = request("/api/chat", {"message": "Hello again!"})
        self.assertIn(f"{fast} could not reply.", stream)
        self.assertIn(f"Trying Hugging Face \\u00b7 {coder}.", stream)
        state = request("/api/state")
        self.assertEqual(state["model_id"], coder)
        self.assertEqual(state["messages"][-1]["routing"]["reason"], "Fallback")
        self.assertEqual(state["routing"][-1]["order"][0]["model"], fast)
        preview = request("/api/brain/route", {**smart, "prompt": "Hi again."})
        self.assertEqual(preview["test"]["order"][0]["model"], coder)
        self.assertIn("recent failure", preview["test"]["reason"])
