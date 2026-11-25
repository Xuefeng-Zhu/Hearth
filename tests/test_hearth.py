import io
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from hearth.agent import Agent, tool_call
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import ConnectorError, Gateway, read_config
from hearth.scheduler import add_job, next_cron, run_due
from hearth.server import Application, HTTPServer
from hearth.storage import HearthError, Storage


class Recorder:
    def __init__(self):
        self.requests = []

    def json(self, config, path, body, headers=None):
        self.requests.append((path, body, headers))
        return {"message_id": "test-message"}


class HearthTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.storage = Storage(scratch.name)
        self.checkpoints = LocalCheckpoints(self.storage)
        self.config = read_config(Path("config/connectors.json"))
        self.agent = Agent(self.storage, self.checkpoints, self.config)

    def chat(self, prompt):
        events = []
        self.agent.chat(prompt, lambda name, data: events.append((name, data)))
        return events

    def test_thanksgiving_loop_streams_and_stages_an_email(self):
        events = self.chat("Plan Thanksgiving dinner")
        names = [name for name, _ in events]
        self.assertEqual(names[:2], ["demo_listening", "started"])
        self.assertIn("demo_warning", names)
        self.assertEqual(names.count("tool_started"), names.count("tool_finished"))
        self.assertLess(names.index("tool_started"), names.index("token"))
        self.assertEqual((events[-1][0], events[-1][1]["provider"]), ("done", "mock"))
        self.assertGreater(sum(name == "token" for name, _ in events), 5)
        remembered = events[-1][1]["message"]["remembered"]
        self.assertEqual({hit["path"] for hit in remembered},
                         {"topics/thanksgiving.md", "people/maya.md", "people/daniel.md"})
        draft, reminder = [data for name, data in events if name == "action"]
        self.assertEqual(draft["email"]["to"], ["daniel@example.invalid", "maya@example.invalid"])
        self.assertEqual(draft["status"], "pending")
        self.assertEqual(reminder["kind"], "reminder")
        self.assertEqual(self.storage.load()["outbox"], [])
        self.assertEqual(len(self.storage.load()["jobs"]), 1)

    def test_keywords_and_markdown_path_validation(self):
        self.assertIn("people/maya.md", [hit["path"] for hit in self.storage.search("vegetarian")])
        for path in ("../USER.md", "/USER.md", "people/../USER.md", "config/connectors.json", "people/alice.txt"):
            with self.assertRaises(HearthError):
                self.storage.read(path)
        alias = self.storage.memory / "people" / "alias.md"
        alias.symlink_to(self.storage.memory / "USER.md")
        with self.assertRaises(HearthError):
            self.storage.read("people/alias.md")
        self.assertNotIn("people/alias.md", self.storage.files())

    def test_bulk_validation_precedes_writes_and_restore_recovers_file(self):
        original = self.storage.read("USER.md")
        with self.assertRaises(HearthError):
            self.agent.memory_write([{"path": "USER.md", "content": ""}, {"path": "/bad", "content": ""}])
        self.assertEqual(self.storage.read("USER.md"), original)
        self.assertEqual(self.checkpoints.list(), [])
        action = self.agent.memory_write([{"path": "USER.md", "content": ""}])["action"]
        self.assertEqual(self.storage.read("USER.md"), "")
        self.checkpoints.restore(action["checkpoint"]["id"])
        self.assertEqual(self.storage.read("USER.md"), original)
        self.assertNotIn(action["id"], self.storage.load()["actions"])

    def test_mock_approval_is_idempotent_and_undoable(self):
        action = self.agent.send_email(["me@example.invalid"], "Test", "Hello")["action"]
        self.assertEqual(self.storage.load()["outbox"], [])
        approved = self.agent.approve(action["id"])
        self.assertEqual(approved["status"], "simulated")
        self.assertEqual(self.agent.approve(action["id"]), approved)
        self.assertEqual(len(self.storage.load()["outbox"]), 1)
        self.checkpoints.restore(approved["checkpoint"]["id"])
        self.assertEqual(self.storage.load()["outbox"], [])
        self.assertEqual(self.storage.load()["actions"][action["id"]]["status"], "pending")

    def test_real_approval_snapshots_before_gateway_and_has_delivery_guard(self):
        class MailGateway(Recorder):
            def json(inner, config, path, body, headers=None):
                self.assertEqual(len(self.checkpoints.list()), 1)
                return super().json(config, path, body, headers)

        gateway = MailGateway()
        self.config["agentmail"].update(connection_id="test-id", inbox_id="hearth@agentmail.to")
        agent = Agent(self.storage, self.checkpoints, self.config, gateway)
        action = agent.send_email(["me@example.com"], "Test", "Hello")["action"]
        self.assertEqual(gateway.requests, [])
        with self.assertRaises(HearthError):
            agent.approve("missing")
        sent = agent.approve(action["id"])
        self.assertEqual(sent["status"], "sent")
        self.assertFalse(agent.can_undo(sent))
        self.assertEqual(gateway.requests[0], ("v0/inboxes/hearth%40agentmail.to/messages/send",
                                             action["email"], {"Idempotency-Key": action["id"]}))
        self.checkpoints.restore(sent["checkpoint"]["id"])
        with self.assertRaises(HearthError):
            agent.approve(action["id"])
        self.assertEqual(len(gateway.requests), 1)

    def test_agent_falls_back_if_provider_fails(self):
        class OfflineGateway(Recorder):
            def completion(self, config, messages, tools, emit):
                emit("partial")
                raise ConnectorError("Unavailable.")

        self.config["llm"][0]["connection_id"] = "test-id"
        self.agent = Agent(self.storage, self.checkpoints, self.config, OfflineGateway())
        events = self.chat("Read USER.md")
        self.assertIn("reset", [name for name, _ in events])
        self.assertEqual((events[-1][0], events[-1][1]["provider"]), ("done", "mock"))
        self.assertTrue(self.agent.threads.messages("main")[-1]["content"].startswith("# Frank"))

    def test_model_fallback_preserves_an_already_staged_action(self):
        class InterruptedGateway(Recorder):
            def completion(self, config, messages, tools, emit):
                if messages[-1]["role"] == "tool":
                    raise ConnectorError("Unavailable.", 503)
                return tool_call("send_email", {"to": ["guest@example.invalid"], "subject": "Dinner", "text": "Join us?"})

        self.config["llm"][0]["connection_id"] = "test-id"
        self.agent = Agent(self.storage, self.checkpoints, self.config, InterruptedGateway())
        events = self.chat("Plan Thanksgiving dinner")
        self.assertEqual((events[-1][0], events[-1][1]["provider"]), ("done", "mock"))
        state = self.storage.load()
        draft, fallback = state["actions"].values()
        self.assertEqual((draft["kind"], draft["status"]), ("email", "pending"))
        self.assertEqual(draft["email"]["to"], ["daniel@example.invalid", "maya@example.invalid"])
        self.assertEqual(fallback["title"], "Brain fallback")
        self.assertEqual(self.agent.threads.messages("main")[-1]["action_ids"], [draft["id"]])
        self.assertEqual(self.agent.threads.messages("main")[-1]["notices"], [fallback["detail"]])
        self.assertEqual(state["outbox"], [])

    def test_scheduler_persists_and_catches_up_once(self):
        now = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
        state = self.storage.load()
        add_job(state, "one shot", now, at=(now + timedelta(minutes=1)).isoformat())
        add_job(state, "weekly", now, cron="*/15 12 * * 3")
        self.storage.save(state)
        resumed = Storage(self.storage.root)
        self.assertEqual(run_due(resumed, now + timedelta(hours=2)), 2)
        self.assertEqual(run_due(resumed, now + timedelta(hours=2)), 0)
        result = resumed.load()
        self.assertEqual([item["message"] for item in result["reminders"]], ["one shot", "weekly"])
        self.assertEqual(result["jobs"][1]["next_at"], "2026-12-02T12:00:00+00:00")
        self.assertEqual(next_cron("0 0 29 2 *", now).year, 2028)
        with self.assertRaises(HearthError):
            next_cron("0 0 31 2 *", now)

    def test_chat_can_schedule_a_recurring_reminder_offline(self):
        events = self.chat("Schedule check the oven | 0 17 * * 4")
        action, = [data for name, data in events if name == "action"]
        self.assertEqual(action["job"]["cron"], "0 17 * * 4")
        self.assertEqual(action["job"]["message"], "check the oven")
        self.assertEqual(self.storage.load()["jobs"], [action["job"]])

    def test_semantic_index_is_written_after_checkpoint_and_reused_for_recall(self):
        class PineconeGateway(Recorder):
            def json(inner, config, path, body=None, headers=None):
                inner.requests.append((path, body))
                if path == "indexes/hearth-memory":
                    return {"dimension": 2, "metric": "cosine"}
                if path == "embed":
                    return {"data": [{"values": [1, 0] if "vegetarian" in item["text"] or
                                     body["parameters"]["input_type"] == "query" else [0, 1]}
                                    for item in body["inputs"]]}
                if path.endswith("/vectors/upsert"):
                    self.assertEqual(len(self.checkpoints.list()), 1)
                    inner.vectors = body["vectors"]
                    return {"upsertedCount": len(inner.vectors)}
                if path.endswith("/query"):
                    self.assertEqual(body["vector"], [1, 0])
                    return {"matches": [{"id": item["id"], "score": item["values"][0]}
                                        for item in inner.vectors]}
                self.fail("Unexpected Pinecone API path.")

        self.config["pinecone"]["connection_id"] = "test-id"
        gateway = PineconeGateway()
        agent = Agent(self.storage, self.checkpoints, self.config, gateway)
        for _ in range(2):
            result = agent.memory_search("dietary preferences")
            self.assertEqual(result["backend"], "pinecone")
            hit = result["results"][0]
            self.assertEqual((hit["path"], hit["line"], hit["similarity"]), ("people/maya.md", 3, 1.0))
        paths = [path for path, _ in gateway.requests]
        self.assertEqual(paths.count("indexes/hearth-memory/vectors/upsert"), 1)
        self.assertEqual(paths.count("indexes/hearth-memory/query"), 2)

    def test_http_flow_streams_and_restores(self):
        app = Application(self.storage, self.checkpoints, self.config)
        server = HTTPServer(("127.0.0.1", 0), app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        opener = build_opener(ProxyHandler({}))

        def request(path, body=None, headers=None):
            request = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                              headers={"Content-Type": "application/json", **(headers or {})})
            with opener.open(request, timeout=5) as response:
                return response.read().decode(), response.status

        def get(path):
            return json.loads(request(path)[0])

        self.assertEqual(get("/health"), {"ok": True, "checkpoints": "local"})
        self.assertIn("Message Hearth", request("/")[0])
        for asset, content_type in {
            "manifest.webmanifest": "application/manifest+json",
            "icons/icon.svg": "image/svg+xml",
            "icons/favicon.svg": "image/svg+xml",
            "icons/apple-touch-icon.png": "image/png",
            "icons/icon-512.png": "image/png",
        }.items():
            with self.subTest(asset=asset), opener.open(f"{base}/{asset}", timeout=5) as response:
                self.assertEqual(response.headers.get_content_type(), content_type)
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(response.read(), (Path("web") / asset).read_bytes())
        self.assertIn("USER.md", get("/api/memory")["files"])
        path = "/api/memory?path=topics%2Fthanksgiving.md"
        original = get(path)["content"]
        with self.assertRaises(HTTPError):
            request("/api/chat", {"message": "Checkpoint"}, {"Sec-Fetch-Site": "cross-site"})
        body, _ = request("/api/chat", {"message": "Wipe topics/thanksgiving.md"})
        self.assertIn("event: token", body)
        action = get("/api/state")["actions"][-1]
        self.assertEqual(get(path)["content"], "")
        self.assertEqual(get("/api/checkpoints")["checkpoints"][0]["id"], action["checkpoint"]["id"])
        self.assertEqual(request("/api/undo", {"id": action["id"]})[1], 202)
        for _ in range(25):
            if get(path)["content"] == original:
                break
            time.sleep(.08)
        self.assertEqual(get(path)["content"], original)


class GatewayTest(unittest.TestCase):
    def test_streaming_content_and_fragmented_tool_calls(self):
        class StreamGateway(Gateway):
            def open(self, config, path, body, headers=None):
                assert path == "v1/chat/completions"
                assert body["stream"]
                chunks = [
                    {"delta": {"content": "One "}, "finish_reason": None},
                    {"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function":
                                               {"name": "memory_read", "arguments": '{"pa'}}]}},
                    {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'th":"USER.md"}'}}]},
                     "finish_reason": "tool_calls"},
                ]
                return io.BytesIO(b"".join(f"data: {json.dumps({'choices': [item]})}\n\n".encode()
                                           for item in chunks) + b"data: [DONE]\n\n")

        emitted = []
        answer = StreamGateway().completion({"provider": "meta", "model": "test"}, [], [], emitted.append)
        self.assertEqual(emitted, ["One "])
        self.assertEqual(answer["tool_calls"][0]["function"]["arguments"], '{"path":"USER.md"}')


if __name__ == "__main__":
    unittest.main()
