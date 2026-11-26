import json
import tempfile
import threading
import unittest
from concurrent.futures import Future
from datetime import datetime
from http.client import HTTPConnection
from unittest.mock import Mock, patch

from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import read_config
from hearth.server import Application, HTTPServer
from hearth.storage import HearthError, ROOT, Storage


class SubsystemStatusTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage = Storage(directory.name)
        config = read_config(ROOT / "config/connectors.json")
        config["brain"] = {"provider": "mock", "model": ""}
        self.app = Application(storage, LocalCheckpoints(storage), config)
        self.server = HTTPServer(("127.0.0.1", 0), self.app)
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)

    def request(self, path, body=None):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            conn.request("GET" if body is None else "POST", path, body,
                         {"Content-Type": "application/json"})
            reply = conn.getresponse()
            data = reply.read()
            return reply.status, json.loads(data) if data else None
        finally:
            conn.close()

    def status(self, subsystem):
        code, data = self.request("/api/status")
        self.assertEqual(code, 200)
        return data["subsystems"][subsystem]

    def test_handler_fault_is_bounded_and_disconnect_and_validation_are_expected(self):
        with patch.object(self.app, "enqueue", side_effect=RuntimeError("private provider fixture")), \
                patch("sys.stderr") as stderr:
            status, data = self.request("/api/chat?marker=private-query", '{"message":"private-body"}')
            self.assertEqual(status, 500)
            self.assertNotIn("private", json.dumps(data))
            http = self.status("http")
            self.assertEqual(http, {"last_success": None, "last_failure": datetime.fromisoformat(
                http["last_failure"]).isoformat(), "last_failure_code": "handler_error", "failure_count": 1})
            stderr.write.assert_not_called()
        self.assertEqual(self.request("/api/chat", '{}')[0], 400)
        with patch.object(self.app, "state_poll", side_effect=BrokenPipeError):
            with self.assertRaises(ConnectionError):
                self.request("/api/state")
        self.assertEqual(self.status("http"), http)
        self.assertEqual(self.request("/api/state")[0], 200)
        recovered = self.status("http")
        datetime.fromisoformat(recovered.pop("last_success"))
        self.assertEqual(recovered, {key: value for key, value in http.items() if key != "last_success"})

    def test_scheduler_loop_counts_storage_errors_and_recovers(self):
        with patch("hearth.server.scheduler.claim_due", side_effect=[
                OSError("private storage fixture"), HearthError("private storage fixture"),
                {"queued_deliveries": 0, "last_tick": "fixture"}]), \
                patch.object(self.app, "kick_scheduler_inbox"), \
                patch.object(self.app.home, "kick"), \
                patch("hearth.server.time.sleep", side_effect=[None, None, StopIteration]):
            with self.assertRaises(StopIteration):
                self.app.background_reminders()
        status = self.status("scheduler")
        self.assertEqual(status["failure_count"], 2)
        self.assertEqual(status["last_failure_code"], "storage_error")
        datetime.fromisoformat(status["last_failure"])
        datetime.fromisoformat(status["last_success"])

    def test_box_listing_and_download_failures_keep_last_success_and_mark_cache_stale(self):
        row = {"id": "box-123", "box_id": "123", "format": "txt", "revision": "first", "title": "Recall fixture"}
        client = Mock()
        client.content.return_value = "Recall test content"
        service = self.app.artifacts

        def refresh(rows, error=None):
            result = Future()
            result.set_result((rows, error))
            with patch.object(service, "refresh_for_read", return_value=(service.box_scope(), client, result, service.epoch)):
                self.app.memory_sync.refresh_box()

        with patch.object(service, "connection", return_value="fixture"):
            refresh({row["id"]: row})
            initial = self.status("box_recall")
            self.assertFalse(initial["stale"])
            datetime.fromisoformat(initial["last_success"])
            cache = self.app.memory_index.box_path
            snapshot = cache.read_bytes()

            refresh({}, error="private listing fixture")
            status = self.status("box_recall")
            self.assertTrue(status["stale"])
            self.assertEqual(status["last_success"], initial["last_success"])
            self.assertEqual(status["last_failure_code"], "refresh_failed")
            self.assertEqual(status["failure_count"], 1)
            self.assertEqual(cache.read_bytes(), snapshot)

            client.content.side_effect = HearthError("private content fixture")
            changed = {row["id"]: {**row, "revision": "second"}}
            refresh(changed)
            status = self.status("box_recall")
            self.assertTrue(status["stale"])
            self.assertEqual(status["last_success"], initial["last_success"])
            self.assertEqual(status["failure_count"], 2)
            self.assertNotIn("private", json.dumps(status))
            self.assertEqual(json.loads(cache.read_bytes())["rows"], json.loads(snapshot)["rows"])

            client.content.side_effect = None
            refresh(changed)
            recovered = self.status("box_recall")
            self.assertFalse(recovered["stale"])
            self.assertEqual(recovered["failure_count"], 2)
            self.assertEqual(json.loads(cache.read_bytes())["rows"][row["id"]]["revision"], "second")

            with patch.object(self.app.memory_index, "replace_box_artifacts", side_effect=OSError):
                refresh(changed)
            failed_write = self.status("box_recall")
            self.assertTrue(failed_write["stale"])
            self.assertEqual(failed_write["last_success"], recovered["last_success"])
            self.assertEqual(failed_write["last_failure_code"], "storage_error")
            self.assertEqual(failed_write["failure_count"], 3)
