import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from urllib.parse import urlencode
from unittest.mock import patch
from zoneinfo import ZoneInfo

from hearth import scheduler, timeline
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import read_config
from hearth.reminder_config import saved
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage, atomic_write, iso
from hearth.threads import SIDEBAR_SIZE, TRANSCRIPT_SIZE


class PollingTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = Storage(directory.name)
        config = read_config(ROOT / "config/connectors.json")
        config["brain"] = {"provider": "mock", "model": ""}
        self.app = Application(self.storage, LocalCheckpoints(self.storage), config)
        self.server = HTTPServer(("127.0.0.1", 0), self.app)
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)

    def get(self, route, tag=None, **query):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            params = f"?{urlencode(query)}" if query else ""
            connection.request("GET", f"/api/{route}{params}", headers={"If-None-Match": tag} if tag else {})
            response = connection.getresponse()
            body = response.read()
            return response.status, response.getheader("ETag"), json.loads(body) if body else None
        finally:
            connection.close()

    def seed_chat(self, thread, rows):
        atomic_write(self.app.threads.path(thread), "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))

    def message(self, i, at, **fields):
        return {"id": f"message-{i}", "role": "assistant" if i % 2 else "user",
                "content": f"Message {i} " + "苗" * 300, "at": iso(at), **fields}

    def test_unchanged_requests_skip_build_serialization_and_storage_lock(self):
        with patch("hearth.server.datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime.now(timezone.utc)
            for route in ("state", "home"):
                with self.subTest(route=route):
                    status, tag, _ = self.get(route)
                    self.assertEqual(status, 200)
                    with (patch.object(self.storage, "lock", side_effect=AssertionError),
                          patch.object(self.app, "state_snapshot", side_effect=AssertionError),
                          patch.object(self.app.home, "build_snapshot", side_effect=AssertionError),
                          patch("hearth.server.json.dumps", side_effect=AssertionError)):
                        self.assertEqual(self.get(route, f'"other", W/{tag}'), (304, tag, None))

    def test_revision_tracks_workspace_writes_from_another_storage_instance(self):
        _, tag, _ = self.get("state")
        writer = Storage(self.storage.root)
        now = datetime.now(timezone.utc)

        def save_action(state):
            state["actions"]["sample"] = {"id": "sample", "kind": "memory", "status": "complete",
                                          "title": "Saved note", "at": iso(now)}

        def save_activity(state):
            state.setdefault("activity", []).append(timeline.entry("tool", "Saved note", {}, id="event", at=iso(now)))

        for write in (save_action, save_activity, lambda state: scheduler.add_job(
                      state, "Water the garden", clock=now, at=iso(now + timedelta(days=1)))):
            previous, sidebar = writer.revisions()
            with writer.lock():
                state = writer.load()
                write(state)
                writer.save(state)
            self.assertEqual(writer.revisions(), (previous + 1, sidebar))
            status, tag, _ = self.get("state", tag)
            self.assertEqual(status, 200)

        previous, _ = writer.revisions()
        with writer.lock():
            side = self.app.threads.create()["id"]
        self.assertEqual(writer.revisions(), (previous + 1, previous + 1))
        status, tag, state = self.get("state", tag)
        self.assertEqual(status, 200)
        self.assertEqual(state["threads"][-1]["id"], side)
        with writer.lock():
            self.app.threads.rename(side, "Garden")
        status, tag, state = self.get("state", tag)
        self.assertEqual((status, state["threads"][-1]["title"]), (200, "Garden"))
        with writer.lock():
            row = self.app.threads.append(side, "assistant", "Try mint.")
        status, tag, state = self.get("state", tag)
        self.assertEqual((status, state["threads"][-1]["last_reply"]), (200, row["id"]))
        with self.app.turn_lock:
            self.app.turns[side] = []
            self.app.turn_activity[side] = {"pose": "working"}
        status, tag, state = self.get("state", tag)
        self.assertEqual((status, state["threads"][-1]["activity"]), (200, {"pose": "working"}))
        with self.app.turn_lock:
            del self.app.turns[side]
        with writer.lock():
            self.app.threads.delete(side)
        status, _, state = self.get("state", tag)
        self.assertEqual((status, [row["id"] for row in state["threads"]]), (200, ["main"]))

    def test_pending_approval_expires_without_another_write(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with self.storage.lock():
            state = self.storage.load()
            state["actions"]["approval"] = {"id": "approval", "kind": "approval", "status": "pending",
                "tool": "memory_edit", "title": "Edit a note", "categories": ["destructive"], "at": iso(now),
                "expires_at": iso(now + timedelta(minutes=1))}
            self.storage.save(state)
        with patch("hearth.server.datetime", wraps=datetime) as clock:
            clock.now.return_value = now
            _, tag, state = self.get("state")
            self.assertTrue(state["active_work"])
            clock.now.return_value = now + timedelta(minutes=1)
            status, _, state = self.get("state", tag)
        self.assertEqual(status, 200)
        self.assertEqual(state["actions"][0]["status"], "expired")
        self.assertFalse(state["active_work"])

    def test_checkpoint_restore_invalidates_state_and_home(self):
        with self.storage.lock():
            kept = self.app.threads.append("main", "assistant", "Before the checkpoint.")
            checkpoint = self.app.checkpoints.create("Polling fixture")
            self.app.threads.append("main", "assistant", "After the checkpoint.")
            state = self.storage.load()
            state["actions"]["restore"] = {"id": "restore", "kind": "tool", "status": "complete",
                                           "title": "Polling fixture", "at": iso(), "checkpoint": checkpoint}
            self.storage.save(state)
        _, state_tag, current = self.get("state")
        _, home_tag, home = self.get("home")
        revision, _ = self.storage.revisions()
        restored = threading.Event()
        restore = self.app.restore_checkpoint

        def finish(*args):
            try:
                restore(*args)
            finally:
                restored.set()

        with (patch.object(self.app, "restore_checkpoint", side_effect=finish),
              patch.object(self.app.memory_sync, "request")):
            self.app.start_restore("restore")
            self.assertTrue(restored.wait(5))

        self.assertIsNone(self.app.restore)
        self.assertEqual(self.storage.revisions(), (revision + 1, revision + 1))
        status, tag, state = self.get("state", state_tag)
        self.assertEqual(status, 200)
        self.assertNotEqual(state["thread_revision"], current["thread_revision"])
        self.assertEqual(state["messages"], [kept])
        self.assertEqual(state["threads"][0]["last_reply"], kept["id"])
        self.assertEqual(self.get("state", tag), (304, tag, None))
        status, tag, state = self.get("home", home_tag)
        self.assertEqual(status, 200)
        self.assertNotEqual(state["builtin"]["activity"], home["builtin"]["activity"])
        self.assertEqual(self.get("home", tag), (304, tag, None))

    def test_transcript_cursors_bound_pages_and_survive_appends(self):
        now = datetime.now(timezone.utc)
        total = 2 * TRANSCRIPT_SIZE + 7
        rows = [self.message(i, now + timedelta(seconds=i)) for i in range(total)]
        rows[3]["action_ids"] = ["old"]
        with self.storage.lock():
            self.seed_chat("main", rows)
            state = self.storage.load()
            state["actions"] = {identity: {"id": identity, "kind": "memory", "status": "complete",
                "title": "Saved note", "at": iso(now)} for identity in ["old", *(f"new-{i}" for i in range(40))]}
            self.storage.save(state)
        _, tag, latest = self.get("state")
        self.assertEqual(latest["messages"], rows[-TRANSCRIPT_SIZE:])
        self.assertNotIn("old", {action["id"] for action in latest["actions"]})
        self.assertEqual(latest["previous_prompt"]["content"], rows[total - TRANSCRIPT_SIZE - 1]["content"])
        with self.storage.lock():
            self.app.threads.append("main", "assistant", "New reply")
        status, _, middle = self.get("transcript", before=latest["before"])
        self.assertEqual((status, middle["messages"]), (200, rows[7:-TRANSCRIPT_SIZE]))
        _, _, oldest = self.get("transcript", before=middle["before"])
        self.assertEqual(oldest["messages"], rows[:7])
        self.assertEqual([action["id"] for action in oldest["actions"]], ["old"])
        self.assertIsNone(oldest["before"])
        self.assertEqual(self.get("transcript", before=latest["before"] + "0")[0], 400)
        self.assertEqual(self.get("state", tag)[0], 200)

    def test_legacy_messages_and_sidebar_overflow_are_accessible(self):
        now = datetime.now(timezone.utc)
        with self.storage.lock():
            state = self.storage.load()
            state["messages"] = [self.message(i, now) for i in range(TRANSCRIPT_SIZE + 1)]
            self.storage.save(state)
            index = self.app.threads.load_index()
            for i in range(SIDEBAR_SIZE + 2):
                index[f"{i:032x}"] = {"title": f"Chat {i}"}
            self.app.threads.save_index(index)
        _, _, main = self.get("state")
        self.assertEqual(len(main["threads"]), SIDEBAR_SIZE)
        self.assertEqual(main["threads"][0]["last_reply"], f"message-{TRANSCRIPT_SIZE - 1}")
        _, _, oldest = self.get("transcript", before=main["before"])
        self.assertEqual([row["id"] for row in oldest["messages"]], ["message-0"])
        _, _, tail = self.get("threads", offset=main["next_thread_offset"])
        self.assertEqual(tail["thread_revision"], main["thread_revision"])
        self.assertIsNone(tail["next_thread_offset"])
        self.assertEqual(len(tail["threads"]), 3)
        thread = tail["threads"][-1]["id"]
        _, _, selected = self.get("state", thread=thread)
        self.assertEqual((selected["thread_id"], selected["threads"][-1]["id"]), (thread, thread))
        self.assertEqual(self.get("transcript", thread=thread, before=main["before"])[0], 400)

    def test_latest_reply_has_attachment_metadata_when_the_upload_message_is_older(self):
        now = datetime.now(timezone.utc)
        identity = "a" * 32
        attachment = {"id": identity, "thread_id": "main", "filename": "garden.txt", "format": "txt"}
        rows = [self.message(i, now) for i in range(TRANSCRIPT_SIZE + 1)]
        rows[0]["attachment_ids"] = [identity]
        rows[1]["attachment_citations"] = [identity]
        with self.storage.lock():
            self.seed_chat("main", rows)
            self.app.uploads.write(self.app.uploads.directory("main") / identity, attachment)
        _, _, latest = self.get("state")
        self.assertEqual(latest["messages"][0]["attachment_citations"], [identity])
        self.assertEqual(latest["previous_prompt"]["attachment_ids"], [identity])
        self.assertEqual(latest["message_uploads"], {identity: attachment})
        _, _, older = self.get("transcript", before=latest["before"])
        self.assertEqual(older["message_uploads"], {identity: attachment})

    def test_home_matches_timeline_and_reuses_unchanged_thread_projections(self):
        now = datetime.now(timezone.utc)
        with self.storage.lock():
            side = self.app.threads.create(title="Garden")["id"]
            old = now - timedelta(days=8)
            for thread in ["main", side]:
                self.seed_chat(thread, [self.message(i, old + timedelta(seconds=i)) for i in range(400)]
                               + [self.message(i, now, id=f"{thread}-{i}") for i in range(4)])
            state = self.storage.load()
            scheduler.add_job(state, "Water mint", clock=now, at=iso(now + timedelta(days=1)))
            state["activity"] = [
                timeline.entry("tool", "Chat interrupted", {}, id="error", at=iso(now), error=True),
                timeline.entry("tool", "Other tool", {}, id="diagnostic", at=iso(now), error=True),
            ]
            self.storage.save(state)
        full = sorted((row for row in self.app.timeline_info()["entries"] if row["at"] and not row.get("diagnostic")),
                      key=lambda row: row["at"], reverse=True)
        zone = ZoneInfo(saved(state)["timezone"])
        today = [row for row in full if datetime.fromisoformat(row["at"]).astimezone(zone).date() == now.astimezone(zone).date()]
        with (patch.object(self.app, "timeline_info", side_effect=AssertionError),
              patch.object(self.app.threads, "messages", side_effect=AssertionError),
              patch.object(self.app.threads, "recent_messages", wraps=self.app.threads.recent_messages) as recent):
            _, tag, snapshot = self.get("home")
            activity = snapshot["builtin"]["activity"]
            self.assertEqual(activity, {"count": len(today), "errors": 1,
                "items": [{key: row[key] for key in ("at", "title", "kind")} for row in full[:5]]})
            self.assertEqual(recent.call_count, 2)
            with self.storage.lock():
                self.app.threads.append(side, "user", "Any more mint?")
            status, tag, changed = self.get("home", tag)
            self.assertEqual(status, 200)
            self.assertEqual(changed["builtin"]["activity"]["count"], len(today) + 1)
            self.assertEqual(recent.call_count, 3)
            self.assertEqual(recent.call_args.args[0], side)
            self.assertEqual(self.get("home", tag), (304, tag, None))
        for thread in ["main", side]:
            tail = self.app.threads.recent_messages(thread, now - timedelta(minutes=1), ())
            self.assertLessEqual(len(tail), 18)


if __name__ == "__main__":
    unittest.main()
