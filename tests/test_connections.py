import io
import json
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import DISCOVERY_PROVIDERS, GATEWAY, ConnectorError, Gateway, read_config
from hearth.server import Application, HTTPServer
from hearth.storage import HearthError, ROOT, Storage


class FakeGateway(Gateway):
    def __init__(self):
        self.entries = []
        self.probes = []
        self.fail_discovery = False
        self.denied = set()
        self.offline = set()
        self.completions = []

    def request(self, path, body, headers, timeout):
        if path == "list":
            if self.fail_discovery:
                raise ConnectorError("private upstream details", 502)
            payload = {"connections": self.entries, "available": [{"provider": p} for p in DISCOVERY_PROVIDERS]}
        else:
            provider, connection_id, endpoint = path.split("/", 2)
            self.probes.append((provider, connection_id, endpoint, body))
            if provider in self.denied:
                raise ConnectorError("private upstream details", 403)
            if provider in self.offline:
                raise ConnectorError("private upstream details", 503)
            if provider == "meta":
                payload = {"choices": [{"message": {"content": "OK"}}]}
            elif provider == "pinecone":
                payload = {"name": endpoint.removeprefix("indexes/")}
            elif provider == "tavily":
                payload = {"results": []}
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
        emit("Muse Spark replied")
        return {"role": "assistant", "content": "Muse Spark replied"}


class DiscoveryTest(unittest.TestCase):
    def test_discovery_distinguishes_catalog_and_validates_urls(self):
        gateway = FakeGateway()
        gateway.add("meta", "conn_meta")
        gateway.entries.extend([
            {"provider": "pinecone", "authorized": False, "gateway_base_url": f"{GATEWAY}/pinecone/conn_old"},
            {"provider": "tavily", "gateway_base_url": "https://example.com/v1/gateway/tavily/conn_outside"},
            {"provider": "tavily", "gateway_base_url": f"{GATEWAY}/agentmail/conn_wrong"},
            {"provider": "tavily", "gateway_base_url": f"{GATEWAY}/tavily/conn_extra/private"},
            {"provider": "tavily", "gateway_base_url": f"{GATEWAY}/tavily/conn_query?key=sensitive"},
        ])
        authorized, found = gateway.discover()
        self.assertEqual(authorized, {"meta": ["conn_meta"], "pinecone": [], "tavily": [], "agentmail": []})
        self.assertEqual(found, {"meta", "pinecone", "tavily"})

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

    def test_startup_scan_saves_ids_once_and_activates_and_revokes_muse_spark(self):
        self.gateway.add("meta", "conn_meta")
        self.gateway.add("meta", "conn_later")
        self.gateway.add("pinecone", "conn_index")
        self.gateway.add("tavily", "conn_search")
        self.gateway.add("agentmail", "conn_inbox")
        self.gateway.denied.add("tavily")
        self.app.scan_connections()
        snapshot = self.app.connection_info()
        self.assertEqual(snapshot["model"], "meta")
        self.assertEqual({p: entry["status"] for p, entry in snapshot["providers"].items()},
                         {"meta": "connected", "pinecone": "connected", "tavily": "unauthorized", "agentmail": "connected"})
        self.assertFalse(self.app.agent.tools.has_mail())
        self.assertEqual(len(self.gateway.probes), 4)
        self.assertEqual({p: endpoint for p, _, endpoint, _ in self.gateway.probes}, {
            "meta": "v1/chat/completions", "pinecone": "indexes/hearth-memory",
            "tavily": "search", "agentmail": "v0/inboxes?limit=1",
        })

        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["llm"][0]["connection_id"], "conn_later")
        self.assertEqual(saved["tavily"]["connection_id"], "conn_search")
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
        self.assertEqual(snapshot["providers"]["agentmail"]["status"], "unavailable")
        self.assertEqual(len(self.gateway.probes), before + 1)
        self.assertEqual(self.gateway.probes[-1], ("agentmail", "conn_inbox", "v0/inboxes/demo%40agentmail.to", None))
        self.assertFalse(self.app.agent.tools.has_mail())

        for body, headers in [
            ({"provider": "agentmail", "value": "invalid"}, {}),
            ({"provider": [], "value": "invalid"}, {}),
            ({"provider": "pinecone", "value": "other-index", "api_key": "discard"}, {}),
            ({"provider": "pinecone", "value": "other-index"}, {"Sec-Fetch-Site": "cross-site"}),
        ]:
            with self.assertRaises(HTTPError) as error:
                request("/api/connections/settings", body, headers)
            self.assertEqual(error.exception.code, 400)
        self.assertEqual(json.loads(self.path.read_text()), saved)
