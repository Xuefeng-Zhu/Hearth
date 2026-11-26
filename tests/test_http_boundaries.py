import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from unittest.mock import patch

from hearth.checkpoints import LocalCheckpoints
from hearth.http_requests import read_json
from hearth.http_routes import POST
from hearth.connectors import read_config
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage


class HTTPBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        storage = Storage(directory.name)
        config = read_config(ROOT / "config/connectors.json")
        config["brain"] = {"provider": "mock", "model": ""}
        cls.app = Application(storage, LocalCheckpoints(storage), config)
        cls.server = HTTPServer(("127.0.0.1", 0), cls.app)
        cls.addClassCleanup(cls.server.server_close)
        thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(cls.server.shutdown)

    def request(self, method, path, body=b"", **headers):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, body, {"Content-Type": "application/json", **headers})
            reply = connection.getresponse()
            data = reply.read()
            if data and reply.headers.get_content_type() == "application/json":
                data = json.loads(data)
            return reply.status, reply.headers, data
        finally:
            connection.close()

    def test_canonical_paths(self):
        for method, path, body, expected in (
            ("GET", "/health?probe=1", b"", 200),
            ("GET", "/health/extra", b"", 404),
            ("GET", "//health", b"", 404),
            ("GET", "/api/state/", b"", 404),
            ("GET", "/api/browse/screenshots/demo.png", b"", 200),
            ("GET", "/api/browse/screenshots/demo.png/extra", b"", 404),
            ("GET", "/api/browse/screenshots/extra/demo.png", b"", 404),
            ("GET", "/pages/" + "a" * 32 + "/v/1/extra", b"", 404),
            ("GET", "/p/" + "a" * 43 + "/extra", b"", 404),
            ("POST", "/api/chat/stop?unused=1", {"thread_id": "main", "reply_id": "sample"}, 200),
            ("POST", "/api/tasks/nested/preview", {}, 404),
            ("POST", "/api/event-automations/create/extra", {}, 404),
            ("POST", "/api/approvals/nested/settings", {}, 404),
            ("POST", "/api/threads/nested/summary/reset", {}, 404),
            ("POST", "/api/proactivity/nested/pass", {}, 404),
            ("POST", "/api/goals/nested/create", {}, 404),
            ("POST", "/api/reminders/nested/create", {}, 404),
            ("POST", "/api/inbox/nested/poll", {}, 404),
            ("POST", "/api/home/settings/", {}, 404),
            ("POST", "/api/uploads/nested/box", {}, 404),
            ("POST", "/api/chat%2fstop", {}, 404),
        ):
            with self.subTest(method=method, path=path):
                self.assertEqual(self.request(method, path, body)[0], expected)

    def test_known_path_with_wrong_method(self):
        for method, path, allow in (
            ("POST", "/health", "GET"),
            ("GET", "/api/chat", "POST"),
            ("PATCH", "/api/tasks", "GET"),
            ("DELETE", "/api/home/settings", "GET, POST"),
            ("POST", "/api/browse/screenshots/demo.png", "GET"),
            ("POST", "/pages/" + "a" * 32 + "/v/1", "GET"),
            ("HEAD", "/p/" + "a" * 43, "GET"),
        ):
            with self.subTest(method=method, path=path):
                status, headers, data = self.request(method, path)
                self.assertEqual((status, headers.get("Allow")), (405, allow))
                self.assertEqual(data, b"" if method == "HEAD" else {"error": "Method not allowed."})
        self.assertEqual(self.request("PATCH", "/api/missing")[0], 404)

    def test_json_shape_types_and_extra_fields(self):
        for path, body, expected in (
            ("/api/chat", b"null", 400),
            ("/api/chat", b"[]", 400),
            ("/api/chat", b'{"message":"hi","extra":NaN}', 400),
            ("/api/chat", b'{"message":"hi","message":"bye"}', 400),
            ("/api/chat", {"message": 7}, 400),
            ("/api/chat", {"message": "hi", "attachment_ids": [{}]}, 400),
            ("/api/chat", {"message": "hi", "extra": True}, 400),
            ("/api/chat/stop", {"thread_id": "main", "reply_id": "sample", "extra": 0}, 400),
            ("/api/threads/rename", {"thread_id": "main"}, 400),
            ("/api/threads/rename", {"thread_id": "main", "title": []}, 400),
            ("/api/threads/create", {"extra": True}, 400),
            ("/api/voice/redact", {"text": "hello", "extra": 1}, 400),
            ("/api/uploads/box", {"thread_id": [], "id": "sample"}, 400),
            ("/api/home/chat", {"id": {}, "extra": "sample"}, 400),
            ("/api/approvals/approve", {"id": "sample", "changes": []}, 400),
            ("/api/tasks/update", {"schedule": {}, "id": []}, 400),
            ("/api/tasks/preview", {"name": "n", "instruction": "i", "schedule": {"type": "interval",
                                    "minutes": True}}, 400),
            ("/api/tasks/preview", {"name": "n", "instruction": "i", "schedule": {"type": "interval",
                                    "minutes": 0}}, 400),
            ("/api/tasks/preview", {"name": "n", "instruction": "i", "schedule": {"type": "once",
                                    "at": "9999-12-31T23:59:59-23:59"}}, 400),
            ("/api/tasks/preview", {"name": "n", "instruction": "i", "schedule": {"type": "weekly",
                                    "days": [1], "time": "09:00", "cron": "0 9 * * 1"}}, 200),
            ("/api/tasks/preview", {"name": "n", "instruction": "i", "schedule": {"type": "interval",
                                    "minutes": 2, "extra": 1}}, 400),
            ("/api/event-automations/create", {"name": "Example", "trigger": {"type": []},
                                              "actions": []}, 400),
            ("/api/voice/redact", {"text": "hello"}, 200),
        ):
            with self.subTest(path=path, body=body):
                self.assertEqual(self.request("POST", path, body)[0], expected)

    def test_every_json_route_requires_an_object_and_rejects_unknown_fields(self):
        with patch.object(self.app.reminders, "tick_token", "test-tick"):
            for path, route in POST.items():
                if route.media != "json":
                    continue
                for body in (b"false", {"unexpected_field": 1}):
                    with self.subTest(path=path, body=body):
                        status, _, _ = self.request("POST", path, body, **{"X-Hearth-Tick-Token": "test-tick"})
                        self.assertEqual(status, 400)

    def test_body_limits_and_framing(self):
        for path, limit, mime in (
            ("/api/chat/stop", 24_000, "application/json"),
            ("/api/event-automations/update", 48_000, "application/json"),
            ("/api/memory/profile", 160_000, "application/json"),
            ("/api/voice/call/report", 512 * 1024, "application/json"),
            ("/api/voice/transcribe", 8 * 1024 * 1024, "audio/webm"),
            ("/api/uploads", 20 * 1024 * 1024 + 2 * 8192, "multipart/form-data; boundary=example"),
        ):
            with self.subTest(path=path):
                status, _, data = self.request("POST", path, **{
                    "Content-Length": str(limit + 1), "Content-Type": mime})
                self.assertEqual(status, 413)
                self.assertIn("error", data)
        raw = b'{"thread_id":"main","reply_id":"sample"}'
        self.assertEqual(self.request("POST", "/api/chat/stop", raw.ljust(24_000))[0], 200)
        self.assertEqual(self.request("POST", "/api/chat/stop", raw, **{"Content-Type": "text/plain"})[0], 400)
        self.assertEqual(self.request("POST", "/api/chat/stop", raw, **{"Transfer-Encoding": "chunked"})[0], 400)

    def test_automation_storage_failure_is_sanitized(self):
        for path, body in (
            ("/api/tasks/preview", {"name": "Example", "instruction": "Say hello",
                                    "schedule": {"type": "interval", "minutes": 10}}),
            ("/api/event-automations/create", {"name": "Example", "trigger": {"type": "email"},
                                              "actions": [{"type": "reminder", "message": "Check it",
                                                           "delay_minutes": 10}]}),
            ("/api/approvals/settings", {"send": "ask"}),
        ):
            with self.subTest(path=path):
                self.assertEqual(self.request("POST", path, {**body, "extra": "invalid"})[0], 400)
                for error in (OSError("storage detail"), ValueError("invalid stored data")):
                    with patch.object(self.app.storage, "load", side_effect=error):
                        status, _, data = self.request("POST", path, body)
                    self.assertEqual(status, 500)
                    self.assertEqual(data, {"error": "Hearth could not update automation data."})

    def test_restore_policy(self):
        self.app.restore = {"action_id": "sample", "status": "restoring"}
        try:
            for method, path in (
                ("GET", "/api/tasks"), ("GET", "/api/approvals"),
                ("POST", "/api/chat"), ("POST", "/api/home/refresh"),
                ("POST", "/api/feed/refresh"), ("POST", "/api/inbox/poll"),
                ("POST", "/api/voice/redact"), ("POST", "/api/uploads"),
                ("POST", "/api/scheduler/tick"), ("POST", "/api/proactivity/pass"),
            ):
                with self.subTest(path=path):
                    with patch.object(self.app.reminders, "tick_token", "test-tick"):
                        status, headers, data = self.request(method, path, **{"X-Hearth-Tick-Token": "test-tick"})
                    self.assertEqual((status, headers.get("Retry-After")), (503, "2"))
                    self.assertEqual(data, {"error": "A checkpoint is being restored."})
            for path in ("/", "/health", "/api/state", "/api/home"):
                with self.subTest(path=path):
                    self.assertEqual(self.request("GET", path)[0], 200)
            self.assertEqual(self.request("POST", "/api/scheduler/tick")[0], 401)
        finally:
            self.app.restore = None

    def test_restore_started_while_reading_body_is_rechecked(self):
        def begin_restore(stream, length):
            body = read_json(stream, length)
            self.app.restore = {"action_id": "sample", "status": "restoring"}
            return body

        for path, body in (("/api/home/refresh", {"id": "weather"}), ("/api/threads/create", {})):
            with self.subTest(path=path), patch("hearth.server.read_json", side_effect=begin_restore):
                try:
                    status, headers, _ = self.request("POST", path, body)
                    self.assertEqual((status, headers.get("Retry-After")), (503, "2"))
                finally:
                    self.app.restore = None
