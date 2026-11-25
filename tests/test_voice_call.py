import json
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import GATEWAY, Gateway, read_config
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage, iso

TOKEN = "synthetic-room-credential"
PATH = "/api/voice/call"
ROOM_URL = "wss://hearth-test.livekit.cloud"


class FakeGateway:
    def __init__(self):
        self.calls = []
        self.error = None
        self.reply = {"livekit_url": ROOM_URL, "token": TOKEN, "room_name": "test-room", "expires_in": 28,
                      "extra": "discard me"}

    def open(self, request, timeout):
        self.calls.append(request)
        if self.error == "timeout":
            raise TimeoutError()
        if self.error:
            raise HTTPError(request.full_url, self.error, "Upstream", {}, BytesIO(TOKEN.encode()))
        return BytesIO(json.dumps(self.reply).encode())


class VoiceCallTest(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.storage = Storage(workspace.name)
        self.provider = FakeGateway()
        gateway = Gateway()
        gateway.opener = self.provider
        config = read_config(ROOT / "config/connectors.json")
        self.app = Application(self.storage, LocalCheckpoints(self.storage), config, gateway=gateway)
        self.app.connections.selected = {"vocalbridge": "test_connector"}
        self.app.connections.last_scan = iso()
        self.app.reload_agent()
        self.server = HTTPServer(("127.0.0.1", 0), self.app)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.origin = f"http://127.0.0.1:{self.server.server_port}"

    def request(self, path, body=None, **headers):
        data = None if body is None else json.dumps(body).encode()
        request = Request(self.origin + path, data=data, headers={"Content-Type": "application/json", **headers})
        try:
            response = build_opener(ProxyHandler({})).open(request, timeout=8)
        except HTTPError as error:
            response = error
        with response:
            return response.code, response.headers, json.load(response)

    def test_token_response_is_normalized_and_never_stored_or_logged(self):
        output = StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            status, headers, response = self.request(PATH + "/token", {}, Origin=self.origin)
            self.assertEqual(status, 200)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(response, {"url": ROOM_URL, "token": TOKEN, "room_name": "test-room", "expires_in": 28})
            request, = self.provider.calls
            self.assertEqual(request.full_url, f"{GATEWAY}/vocalbridge/test_connector/api/v1/token")
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(json.loads(request.data), {"participant_name": "Demo profile"})
            self.assertFalse(request.has_header("Authorization"))
            self.assertFalse(request.has_header("X-api-key"))
            _, _, status = self.request(PATH + "/status")
        self.assertEqual(status["last_check"]["status"], "passed")
        self.assertNotIn(TOKEN, json.dumps(status) + output.getvalue())
        for file in self.storage.root.rglob("*"):
            if file.is_file():
                self.assertNotIn(TOKEN.encode(), file.read_bytes())
        self.assertNotIn("vocalbridge", self.app.agent.gateway_connections)

    def test_missing_connector_has_setup_hint_and_skips_gateway(self):
        self.app.connections.selected.clear()
        code, _, result = self.request(PATH + "/token", {})
        self.assertEqual(code, 409)
        self.assertIn("Name Prefix hearth", result["error"])
        self.assertFalse(self.request(PATH + "/status")[2]["configured"])
        self.assertFalse(self.provider.calls)

    def test_token_rejects_cross_origin_and_invalid_json_bodies(self):
        for headers in (
            {"Origin": "https://other.invalid"}, {"Origin": self.origin.replace("http", "https")},
            {"Sec-Fetch-Site": "same-site"}, {"Sec-Fetch-Site": "cross-site"}, {"Origin": "null"},
        ):
            with self.subTest(headers=headers):
                self.assertEqual(self.request(PATH + "/token", {}, **headers)[0], 403)
        self.assertEqual(self.request(PATH + "/token", {"participant_name": "Injected"})[0], 400)
        self.assertEqual(self.request(PATH + "/token", {}, **{"Content-Type": "text/plain"})[0], 400)
        self.assertFalse(self.provider.calls)

    def test_gateway_errors_are_actionable_and_redact_upstream_details(self):
        for upstream, expected, hint in (
            (404, 503, "Deploy"), (402, 403, "usage"), (403, 403, "usage"), (401, 502, "agent-scoped"),
            (429, 429, "rate-limiting"), (504, 504, "timed out"), ("timeout", 504, "timed out"),
            (500, 502, "through Fly"),
        ):
            with self.subTest(upstream=upstream):
                self.provider.error = upstream
                code, _, result = self.request(PATH + "/token", {})
                self.assertEqual(code, expected)
                self.assertIn(hint, result["error"])
                self.assertNotIn(TOKEN, json.dumps(result))

    def test_token_rejects_incomplete_or_non_livekit_response(self):
        self.provider.reply["livekit_url"] = "wss://other.invalid"
        self.assertEqual(self.request(PATH + "/token", {})[0], 502)
        self.provider.reply["livekit_url"] = ROOM_URL
        self.provider.reply["expires_in"] = False
        self.assertEqual(self.request(PATH + "/token", {})[0], 502)

    def test_voice_query_runs_normal_turn_in_side_chat_with_routing_and_undo(self):
        side = self.request("/api/threads/create", {})[2]["id"]
        code, _, response = self.request(PATH + "/query", {
            "thread_id": side, "query": "Remember topics/call-test.md: Test the call bridge",
        })
        self.assertEqual(code, 200)
        self.assertTrue(response["reply"])
        _, _, state = self.request(f"/api/state?thread={side}")
        self.assertEqual([(item["role"], item["source"]) for item in state["messages"]],
                         [("user", "voice-call"), ("assistant", "voice-call")])
        for record in (state["routing"][-1], state["actions"][-1]):
            self.assertEqual((record["source"], record["thread_id"]), ("voice-call", side))
        self.assertEqual(self.storage.read("topics/call-test.md"), "Test the call bridge")
        checkpoint = state["actions"][-1]
        self.assertIn("checkpoint", checkpoint)
        self.app.checkpoints.restore(checkpoint["checkpoint"]["id"])
        self.assertFalse((self.storage.live / "memory/topics/call-test.md").exists())
        self.assertEqual(self.app.threads.messages("main"), [])

    def test_report_is_redacted_idempotent_and_skipped_by_model_history(self):
        body = {"id": "a" * 32, "thread_id": "main", "duration": 45, "demo": False,
                "lines": [{"role": "user", "text": "password: test-value"}, {"role": "agent", "text": "Hello"}]}
        code, _, first = self.request(PATH + "/report", body)
        self.assertEqual(code, 200)
        self.assertEqual(first["lines"][0]["text"], 'password: "[redacted]"')
        self.assertEqual(self.request(PATH + "/report", body)[2], first)
        self.assertEqual(self.app.threads.messages("main"), [first])
        self.assertEqual(self.app.threads.messages("main", dialogue_only=True), [])
        self.assertEqual(self.request(PATH + "/report", {**body, "duration": True})[0], 400)
        self.assertEqual(self.request(PATH + "/report", {**body, "lines": [{"role": "system", "text": "invalid"}]})[0], 400)
