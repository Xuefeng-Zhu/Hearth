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
from unittest.mock import Mock

from hearth.agent import Agent, tool_call
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import ConnectorError, Gateway, read_config
from hearth.scheduler import add_job, next_cron, run_due
from hearth.server import Application, HTTPServer
from hearth.storage import HearthError, Storage
from hearth.timeline import record


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
        from hearth import memory
        self.assertEqual(memory.parse("USER.md", self.storage.read("USER.md"), strict=True)[1], "")
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
        self.assertTrue(self.agent.threads.messages("main")[-1]["content"].startswith("# Demo profile"))

    def test_model_fallback_preserves_an_already_staged_action(self):
        class InterruptedGateway(Recorder):
            def completion(self, config, messages, tools, emit):
                if messages[-1]["role"] == "tool":
                    raise ConnectorError("Unavailable.", 503)
                return tool_call("send_email", {"to": ["guest@example.invalid"], "subject": "Dinner", "text": "Join us?"})

        self.config["llm"][0]["connection_id"] = "test-id"
        self.agent = Agent(self.storage, self.checkpoints, self.config, InterruptedGateway())
        events = self.chat("Email guest@example.invalid | Dinner | Join us?")
        self.assertEqual((events[-1][0], events[-1][1]["provider"]), ("done", "mock"))
        state = self.storage.load()
        draft, fallback = state["actions"].values()
        self.assertEqual((draft["kind"], draft["status"]), ("email", "pending"))
        self.assertEqual(draft["email"]["to"], ["guest@example.invalid"])
        self.assertEqual(fallback["title"], "Brain fallback")
        self.assertEqual(self.agent.threads.messages("main")[-1]["action_ids"], [draft["id"]])
        self.assertEqual(self.agent.threads.messages("main")[-1]["notices"], [fallback["detail"]])
        self.assertEqual(state["outbox"], [])

    def test_model_turn_cleans_fragmented_tool_markup_and_credentials(self):
        class ModelGateway(Recorder):
            def completion(self, config, messages, tools, emit):
                chunks = ["Hello ", "  <", "/func", "tion>\n", "<tool_", "call>",
                          '{"arguments":"internal-only"}', "</tool_call>",
                          "**Menu**\n", "password", ": ", "fake", "-value",
                          "\n", "sk-", "abcdefghijklmnopqrstuvwx"]
                for chunk in chunks:
                    emit(chunk)
                return {"content": "".join(chunks)}

        self.config["llm"][0]["connection_id"] = "test-id"
        self.agent = Agent(self.storage, self.checkpoints, self.config, ModelGateway())
        events = self.chat("Hello")
        text = "".join(data["text"] for name, data in events if name == "token")
        self.assertGreater(sum(name == "token" for name, _ in events), 1)
        self.assertIn('**Menu**\npassword: "[redacted]"\n[redacted]', text)
        self.assertNotRegex(text, "function|tool_call|internal-only|fake-value|abcdefghijkl")
        self.assertEqual(events[-1][1]["message"]["content"], text.strip())
        self.assertEqual(self.agent.threads.messages("main")[-1]["content"], text.strip())

    def test_reply_stream_redacts_credentials_before_a_tool_marker(self):
        from hearth.reply_text import ReplyStream

        emitted = []
        stream = ReplyStream(emitted.append)
        stream.write("Hello ")
        stream.write("sk-abc</function>defghijklmnopqrstuvwxyz ")
        stream.finish()
        self.assertEqual(emitted, ["Hello ", "[redacted] "])

    def test_reply_stream_redacts_an_incomplete_private_key_block(self):
        from hearth.reply_text import ReplyStream

        emitted = []
        stream = ReplyStream(emitted.append)
        for chunk in ["Before the key.\n", "-----BE", "GIN TEST PRIVATE KEY-----\n", "private material\n"]:
            stream.write(chunk)
        stream.finish()
        self.assertEqual("".join(emitted), "Before the key.\n[redacted]\n\n")

    def test_self_closing_and_stray_tool_tags_preserve_following_text(self):
        from hearth.reply_text import ReplyStream, clean_reply

        chunks = ["Dinner ", "<func", 'tion name="lookup"/>\n', "starts here. ",
                  "<tool_calls><function=lookup>private work</function></tool_calls>",
                  "< / tool_call >", "**Bring a dish.** ", "</function incomplete"]
        expected = "Dinner \nstarts here. **Bring a dish.** "
        emitted = []
        stream = ReplyStream(emitted.append)
        for chunk in chunks:
            stream.write(chunk)
        stream.finish()
        self.assertEqual("".join(emitted), expected)
        self.assertEqual(clean_reply("".join(chunks)), expected)

    def test_textual_tool_dialects_preserve_arguments_without_exposing_calls(self):
        from hearth.reply_text import clean_reply, text_tool_calls

        args = '{"path":"topics/round-two.md","content":"Line 1\\nLine 2"}'
        envelope = '{"name":"memory_write","arguments":' + args + '}'
        for raw in (
            "<tool_call>" + envelope + "</tool_call>",
            "memory_write>" + args,
            "<|python_tag|>" + envelope,
            "<|python_tag|>memory_write>" + args,
            "```json\n" + envelope + "\n```",
            '{"tool_calls":[{"type":"function","function":' + envelope + '}]}',
        ):
            with self.subTest(raw=raw):
                prose, calls, malformed = text_tool_calls(raw)
                self.assertEqual(prose, "")
                self.assertFalse(malformed)
                self.assertEqual(calls[0]["function"]["name"], "memory_write")
                self.assertEqual(json.loads(calls[0]["function"]["arguments"])["content"], "Line 1\nLine 2")
                self.assertEqual(clean_reply(raw), "")
        self.assertEqual(text_tool_calls("artifact_create>{")[::2], ("", True))

    def test_mock_reply_stream_sanitizes_note_excerpt(self):
        self.storage.write("topics/round-two.md", "Start </function> here. <tool_call>internal work</tool_call> Done.")
        events = self.chat("Read topics/round-two.md")
        text = "".join(data["text"] for name, data in events if name == "token")
        self.assertIn("Start  here.", text)
        self.assertIn("Done.", text)
        self.assertNotRegex(text, "function|tool_call|internal work")

    def test_old_replies_are_sanitized_on_read_without_rewriting_history(self):
        threads = self.agent.threads
        raw = "Dinner </function>starts at five. <tool_call>private work</tool_call>"
        with self.storage.lock():
            state = self.storage.load()
            state["messages"] = [{"role": "assistant", "content": raw}]
            self.storage.save(state)
            self.assertEqual(threads.messages("main")[0]["content"], "Dinner starts at five. ")
            self.assertEqual(self.storage.load()["messages"][0]["content"], raw)
            threads.append("main", "user", "Thanks")
            self.assertEqual(threads.messages("main")[0]["content"], "Dinner starts at five. ")
            self.assertIn(raw, threads.path("main").read_text())

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
        for route in ("/api/chat", "/api/approve", "/api/undo", "/api/redo", "/api/threads/create",
                      "/api/connections/rescan", "/api/brain/settings", "/api/memory/forget",
                      "/api/search/test", "/api/artifacts/create", "/api/inbox/poll",
                      "/api/reminders/create", "/api/voice/redact", "/api/voice/transcribe?language=en",
                      "/api/voice/call/token", "/api/scheduler/tick"):
            for headers in ({"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"},
                            {"Origin": "https://other.example"}, {"Origin": "null"}):
                with self.subTest(route=route, headers=headers), self.assertRaises(HTTPError) as error:
                    request(route, {}, headers)
                self.assertEqual(error.exception.code, 403)
        for raw in (b'{"message":"' + b"x" * 24_000 + b'"}', b'{"message":"\\ud800"}',
                    b'{"message":"Hello","extra":NaN}', b'{"message":"Hello","extra":1e999}',
                    b'{"data":' + b"[" * 1500 + b"]" * 1500 + b"}"):
            with self.assertRaises(HTTPError) as error:
                opener.open(Request(base + "/api/chat", data=raw, headers={"Content-Type": "application/json"}))
            self.assertEqual(error.exception.code, 400)
        self.assertFalse(get("/api/state")["messages"])
        with opener.open(base + "/api/state", timeout=5) as response:
            original_tag = response.headers["ETag"]
        self.assertTrue(original_tag)
        with self.assertRaises(HTTPError) as cached:
            request("/api/state", headers={"If-None-Match": original_tag})
        self.assertEqual(cached.exception.code, 304)
        self.assertEqual(cached.exception.read(), b"")
        app.connections.test = Mock()
        for route, payload in (("/api/connections/rescan", {}), ("/api/memory/search", {"query": "vegetarian"}),
                               ("/api/connections/test", {"provider": "huggingface"})):
            ready = threading.Event()
            release = threading.Event()

            def hold_operation():
                with app.operation:
                    ready.set()
                    release.wait(2)

            worker = threading.Thread(target=hold_operation)
            worker.start()
            self.assertTrue(ready.wait(1))
            timer = threading.Timer(0.1, release.set)
            timer.start()
            try:
                self.assertEqual(request(route, payload)[1], 200)
            finally:
                release.set()
                timer.join()
                worker.join()
        app.connections.test.assert_called_once_with("huggingface")
        body, _ = request("/api/chat", {"message": "Wipe topics/thanksgiving.md"})
        self.assertIn("event: token", body)
        self.assertEqual(request("/api/state", headers={"If-None-Match": original_tag})[1], 200)
        approval = get("/api/state")["actions"][-1]
        self.assertEqual(approval["status"], "pending")
        self.assertEqual(get(path)["content"], original)
        result = json.loads(request("/api/approvals/approve", {"id": approval["id"]})[0])
        action = next(row for row in get("/api/state")["actions"] if row["id"] == result["effect_action"])
        timeline = get("/api/timeline")["entries"]
        card, = [row for row in timeline if row.get("action_id") == action["id"]]
        self.assertTrue(card["undoable"])
        self.assertIn("topics/thanksgiving.md", card["title"])
        self.assertFalse(any(row["kind"] == "checkpoint" for row in timeline))
        self.assertTrue(any(row["kind"] == "chat" for row in timeline))
        self.assertEqual(get(path)["body"], "")
        self.assertEqual(get("/api/checkpoints")["checkpoints"][0]["id"], action["checkpoint"]["id"])
        self.assertEqual(request("/api/undo", {"id": action["id"]})[1], 200)
        self.assertEqual(get(path)["content"], original)
        undone, = [row for row in get("/api/timeline")["entries"] if row["id"] == card["id"]]
        self.assertTrue(undone["redoable"])
        self.assertEqual(request("/api/redo", {"id": action["id"]})[1], 200)
        self.assertEqual(get(path)["body"], "")

    def test_timeline_stream_signals_scheduler_writes_and_projects_redacted_history(self):
        app = Application(self.storage, self.checkpoints, self.config)
        with HTTPServer(("127.0.0.1", 0), app) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                opener = build_opener(ProxyHandler({}))
                events = base + "/api/timeline/events"
                with self.assertRaises(HTTPError):
                    opener.open(Request(events, headers={"Origin": "https://elsewhere.example"}), timeout=5)
                with opener.open(events, timeout=5) as stream:
                    self.assertEqual(stream.headers.get_content_type(), "text/event-stream")
                    for expected in (b"event: activity\n", b"data: {}\n", b"\n"):
                        self.assertEqual(stream.readline(), expected)
                    now = datetime.now(timezone.utc)
                    with self.storage.lock():
                        state = self.storage.load()
                        add_job(state, "Check the oven", now - timedelta(seconds=30), at=(now - timedelta(seconds=2)).isoformat())
                        state["messages"] = [
                            {"role": "user", "content": "password: demo-private-value", "at": now.isoformat()},
                            {"role": "assistant", "content": "Hello", "at": now.isoformat()},
                        ]
                        self.storage.save(state)
                    self.assertEqual(run_due(Storage(self.storage.root), now), 1)
                    self.assertEqual(stream.readline(), b"event: activity\n")
                record(self.storage, "gateway", "Connector response", {}, provider="exa",
                       data={"authorization": "demo-private-value"})
                with opener.open(base + "/api/timeline", timeout=5) as response:
                    raw = response.read().decode()
                self.assertNotIn("demo-private-value", raw)
                rows = {row["kind"]: row for row in json.loads(raw)["entries"]}
                self.assertEqual(rows["chat"]["data"]["reply"], "Hello")
                self.assertEqual(rows["reminder"]["data"]["message"], "Check the oven")
                self.assertEqual(rows["gateway"]["connector"], "Exa")
            finally:
                server.shutdown()


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
