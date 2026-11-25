import base64
import json
import tempfile
import threading
import unittest
from io import BytesIO
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import GATEWAY, Gateway, read_config
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage
from hearth.voice import MAX_AUDIO, WHISPER_PATH

WAV = b"RIFF\x18\x00\x00\x00WAVEfmt "


class FakeProvider:
    def __init__(self):
        self.calls = []
        self.status = 200
        self.reply = {"text": "  The password is test-value. Hello. "}

    def open(self, request, timeout):
        self.calls.append(request)
        if self.status != 200:
            raise HTTPError(request.full_url, self.status, "Raw provider detail", {}, BytesIO(b"private debug"))
        return BytesIO(json.dumps(self.reply).encode())


class VoiceTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        storage = Storage(scratch.name)
        gateway = Gateway()
        self.provider = FakeProvider()
        gateway.opener = self.provider
        self.app = Application(storage, LocalCheckpoints(storage), read_config(ROOT / "config/connectors.json"), gateway=gateway)
        self.app.connections.selected = {"huggingface": "qa_connection"}
        self.app.reload_agent()
        self.server = HTTPServer(("127.0.0.1", 0), self.app)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, audio=WAV, mime="audio/wav", path="/api/voice/transcribe", **headers):
        request = Request(f"http://127.0.0.1:{self.server.server_port}{path}", data=audio,
                          headers={"Content-Type": mime, **headers})
        try:
            response = build_opener(ProxyHandler({})).open(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.code, json.load(response)

    def test_raw_wav_uses_gateway_without_authorization_and_redacts_response(self):
        status, response = self.post()
        self.assertEqual(status, 200)
        self.assertEqual(response["text"], 'The password is "[redacted]" Hello.')
        request, = self.provider.calls
        self.assertEqual(request.full_url, f"{GATEWAY}/huggingface/qa_connection/{WHISPER_PATH}")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "audio/wav")
        self.assertFalse(request.has_header("Authorization"))
        self.assertEqual(request.data, WAV)
        self.assertEqual(self.app.threads.messages("main"), [])

    def test_selected_language_uses_parameterized_asr_and_browser_text_is_redacted(self):
        self.assertEqual(self.post(path="/api/voice/transcribe?language=zh")[0], 200)
        request, = self.provider.calls
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data), {
            "inputs": base64.b64encode(WAV).decode(),
            "parameters": {"generation_parameters": {"language": "zh"}},
        })
        status, result = self.post(b'{"text":"password: other-test"}', "application/json", "/api/voice/redact")
        self.assertEqual((status, result), (200, {"text": 'password: "[redacted]"'}))
        self.assertEqual(len(self.provider.calls), 1)

    def test_rejects_invalid_audio_types_sizes_and_cross_site_uploads(self):
        self.assertEqual(self.post(mime="text/plain")[0], 415)
        self.assertEqual(self.post(audio=b"<html>")[0], 415)
        self.assertEqual(self.post(audio=b"")[0], 400)
        self.assertEqual(self.post(**{"Content-Length": str(MAX_AUDIO + 1)})[0], 413)
        self.assertEqual(self.post(**{"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.post(path="/api/voice/transcribe?language=en%0A")[0], 400)
        self.assertEqual(self.provider.calls, [])

    def test_provider_failures_map_to_safe_messages(self):
        for gateway_status, status, hint in (
            (403, 502, "denied"), (415, 422, "decode"), (429, 429, "rate-limiting"),
            (503, 503, "unavailable"), (500, 502, "could not reach"),
        ):
            with self.subTest(gateway_status=gateway_status):
                self.provider.status = gateway_status
                code, result = self.post()
                self.assertEqual(code, status)
                self.assertIn(hint, result["error"])
                self.assertNotIn("private debug", str(result))
        self.provider.status = 200
        self.provider.reply = {"text": " "}
        self.assertEqual(self.post()[0], 422)
        self.provider.reply = {"text": None}
        self.assertEqual(self.post()[0], 502)
        self.app.connections.selected.clear()
        self.app.reload_agent()
        self.assertEqual(self.post()[0], 409)
