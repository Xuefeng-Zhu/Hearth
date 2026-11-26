import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from hearth.agent import Agent
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import read_config
from hearth.scheduler import run_due
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage


class ThreadTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.storage = Storage(scratch.name)
        self.checkpoints = LocalCheckpoints(self.storage)
        self.config = read_config(ROOT / "config/connectors.json")
        self.app = Application(self.storage, self.checkpoints, self.config)
        self.threads = self.app.threads
        self.server = HTTPServer(("127.0.0.1", 0), self.app)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path, body=None, *, on_event=None):
        data = json.dumps(body).encode() if body is not None else None
        request = Request(f"http://127.0.0.1:{self.server.server_port}{path}", data=data,
                          headers={"Content-Type": "application/json"})
        with build_opener(ProxyHandler({})).open(request, timeout=8) as response:
            if response.headers.get_content_type() != "text/event-stream":
                return json.load(response)
            events = []
            for raw in response:
                line = raw.decode().rstrip("\n")
                if line.startswith("event: "):
                    name = line[7:]
                elif line.startswith("data: "):
                    payload = json.loads(line[6:])
                    events.append((name, payload))
                    if on_event:
                        on_event(name, payload)
            return events

    def chat(self, text, thread_id="main"):
        return self.request("/api/chat", {"message": text, "thread_id": thread_id})

    def state(self, thread_id="main"):
        return self.request(f"/api/state?thread={thread_id}")

    def test_legacy_main_migration_and_side_lifecycle(self):
        legacy = {"id": "old", "role": "user", "content": "A legacy Main entry", "at": "2026-11-25T00:00:00+00:00"}
        state = self.storage.load()
        self.storage.save({**state, "messages": [legacy]})
        self.assertEqual(self.state()["messages"], [legacy])
        events = self.chat("/side Read USER.md")
        side = events[0][1]["thread"]["id"]
        self.assertEqual(events[-1][0], "done")
        self.assertEqual(self.state()["messages"], [legacy])
        self.assertEqual(self.state()["threads"], [
            {"id": "main", "title": "Main", "busy": False, "last_reply": None},
            {"id": side, "title": "Read USER.md", "busy": False, "last_reply": events[-1][1]["message"]["id"]},
        ])
        self.request("/api/threads/rename", {"thread_id": side, "title": "Profile notes"})
        side_state = self.state(side)
        self.assertEqual(side_state["threads"][1]["title"], "Profile notes")
        reply = side_state["messages"][-1]
        self.assertTrue(reply["content"].startswith("# Demo profile"))
        shared = self.request("/api/threads/share", {"thread_id": side, "message_id": reply["id"]})
        self.assertTrue(shared["content"].startswith("Shared from Profile notes\n\n> "))
        self.assertEqual(self.state()["messages"], [legacy, shared])
        self.assertNotIn("messages", self.storage.load())
        self.assertEqual(self.threads.path("main").read_text().count("\n"), 2)

        for suffix, body in [("delete", {}), ("rename", {"title": "No"}), ("share", {"message_id": "old"})]:
            with self.assertRaises(HTTPError) as blocked:
                self.request(f"/api/threads/{suffix}", {"thread_id": "main", **body})
            self.assertEqual(blocked.exception.code, 400)
        with self.storage.lock():
            self.threads.save_summary(side, {"text": "Earlier profile decision.", "cursor": side_state["messages"][0]["id"]})
        self.assertEqual(self.request(f"/api/threads/summary?thread={side}"), {"summary": "Earlier profile decision."})
        self.assertIn("Earlier profile decision.", self.threads.context("main")[1][0]["earlier"])
        action = self.request("/api/threads/summary/reset", {"thread_id": side})["action"]
        self.assertTrue(self.app.agent.can_undo(action))
        self.assertEqual(self.request(f"/api/threads/summary?thread={side}"), {"summary": ""})
        self.assertEqual(self.state(side)["messages"], side_state["messages"])
        saved_path = self.threads.summary_path(side).relative_to(self.storage.live)
        backup = self.checkpoints.root / action["checkpoint"]["id"] / "live" / saved_path
        saved_summary = json.loads(backup.read_text())
        self.assertEqual(saved_summary["text"], "Earlier profile decision.")
        with self.storage.lock():
            self.threads.save_summary(side, saved_summary)
        self.request("/api/threads/summary/reset", {"thread_id": "main"})
        deletion = self.request("/api/threads/delete", {"thread_id": side})
        self.assertEqual(deletion["thread_title"], "Profile notes")
        self.assertEqual(self.state(side)["thread_id"], "main")
        self.assertFalse(self.threads.path(side).exists())
        self.assertFalse(self.threads.summary_path(side).exists())
        self.assertTrue((self.checkpoints.root / deletion["checkpoint"]["id"] / "live" / "threads" /
                         f"{side}.jsonl").is_file())
        self.request("/api/undo", {"id": deletion["id"]})
        until = time.monotonic() + 3
        while self.state(side)["thread_id"] != side and time.monotonic() < until:
            time.sleep(0.05)
        self.assertEqual(self.state(side)["messages"], side_state["messages"])
        self.assertEqual(self.request(f"/api/threads/summary?thread={side}"), {"summary": saved_summary["text"]})
        resumed = Application(Storage(self.storage.root), self.checkpoints, self.config)
        self.assertEqual(resumed.info(side)["threads"][1]["title"], "Profile notes")

    def test_last_reply_from_legacy_and_large_thread_messages(self):
        legacy = {"id": "legacy-answer", "role": "assistant", "content": "A saved answer"}
        state = self.storage.load()
        self.storage.save({**state, "messages": [legacy]})
        self.assertEqual(self.state()["threads"][0]["last_reply"], legacy["id"])
        with self.storage.lock():
            side = self.threads.create()["id"]
            reply = self.threads.append(side, "assistant", "☕" * 8000)
            self.threads.append(side, "user", "follow-up " * 1500)
        self.assertEqual(self.state()["threads"][1]["last_reply"], reply["id"])

    def test_shared_actions_reminders_memory_and_deleted_source(self):
        side_id = self.chat("/btw Remember topics/garden.md: Grow late mint")[0][1]["thread"]["id"]
        self.request("/api/threads/rename", {"thread_id": side_id, "title": "Garden"})
        self.chat("Remind me to water the mint in 1 minute", side_id)
        self.chat("Email guest@example.invalid | Garden | Water the mint", side_id)
        self.assertEqual(self.state()["messages"], [])
        self.assertEqual(self.request("/api/memory?path=topics%2Fgarden.md")["body"], "Grow late mint")
        memory, reminder, approval = self.state()["actions"]
        for action in (memory, reminder, approval):
            self.assertEqual(action["thread_id"], side_id)
        self.assertEqual(approval["thread_title"], "Garden")
        self.assertEqual(self.request("/api/checkpoints")["checkpoints"][0]["thread_id"], side_id)
        run_due(self.storage, datetime.now(timezone.utc) + timedelta(minutes=2))
        self.assertEqual(self.state()["reminders"][0]["thread_title"], "Garden")
        self.request("/api/threads/delete", {"thread_id": side_id})
        self.assertEqual(self.request("/api/approve", {"id": approval["id"]})["status"], "simulated")
        self.assertEqual(self.state()["actions"][2]["thread_title"], "Garden")

    def test_separate_context_with_memory_main_excerpt_and_side_summary(self):
        calls = []
        self.storage.write("USER.md", "# Frank\n\nI keep a garden plan.")

        class Gateway:
            def completion(self, model, messages, tools, emit):
                calls.append(messages)
                if messages[0]["content"].startswith("Summarize this side chat"):
                    answer = "The user chose a Saturday garden plan."
                else:
                    answer = "More detail lives in the transcript only. DETAILS-ONLY"
                    emit(answer)
                return {"role": "assistant", "content": answer}

        self.config["llm"][0]["connection_id"] = "test-connector"
        self.app.agent = Agent(self.storage, self.checkpoints, self.config, Gateway())
        self.chat("Main anchor reference")
        side_id = self.chat("/side Garden plan")[0][1]["thread"]["id"]
        self.chat("Check awareness in Main")
        side_prompt = calls[1][0]["content"]
        main_prompt = calls[-1][0]["content"]
        self.assertIn("Recent Main excerpts for read-only reference", side_prompt)
        self.assertIn("Main anchor reference", side_prompt)
        self.assertIn("USER.md", side_prompt)
        self.assertIn('"title": "Garden plan"', main_prompt)
        self.assertIn("The user chose a Saturday garden plan.", main_prompt)
        self.assertNotIn("DETAILS-ONLY", main_prompt)
        self.assertEqual(len(self.state(side_id)["messages"]), 2)
        self.assertNotIn("Garden plan", [message["content"] for message in self.state()["messages"]])

    def test_busy_main_queues_followup_while_a_side_chat_finishes(self):
        main_token = threading.Event()
        release_main = threading.Event()
        followup_waiting = threading.Event()
        reported_history = []

        class Gateway:
            def completion(self, model, messages, tools, emit):
                prompt = messages[-1]["content"]
                if prompt == "Hold the Main stream":
                    emit("Main is mid-stream")
                    if not release_main.wait(6):
                        raise RuntimeError("Main was held too long")
                if prompt == "Queued follow-up":
                    reported_history.extend(messages)
                answer = "Reply complete"
                emit(answer)
                return {"role": "assistant", "content": answer}

        self.config["llm"][0]["connection_id"] = "test-connector"
        self.app.agent = Agent(self.storage, self.checkpoints, self.config, Gateway())
        with ThreadPoolExecutor() as executor:
            main = executor.submit(self.request, "/api/chat", {"message": "Hold the Main stream"},
                                   on_event=lambda name, _: main_token.set() if name == "token" else None)
            try:
                self.assertTrue(main_token.wait(3))
                self.assertTrue(self.state()["threads"][0]["busy"])
                followup = executor.submit(self.request, "/api/chat", {"message": "Queued follow-up"},
                                           on_event=lambda name, _: followup_waiting.set() if name == "queued" else None)
                self.assertTrue(followup_waiting.wait(3))
                side = self.chat("/btw Parallel side")
                self.assertEqual(side[-1][0], "done")
                self.assertFalse(main.done())
                self.assertFalse(followup.done())
                self.assertEqual([message["content"] for message in self.state()["messages"]],
                                 ["Hold the Main stream"])
            finally:
                release_main.set()
            self.assertEqual(main.result(3)[-1][0], "done")
            self.assertEqual(followup.result(3)[-1][0], "done")
        self.assertEqual([item["content"] for item in reported_history[1:]],
                         ["Hold the Main stream", "Reply complete", "Queued follow-up"])
        self.assertFalse(self.state()["threads"][0]["busy"])
