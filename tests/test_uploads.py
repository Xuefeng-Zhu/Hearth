import io
import json
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from PIL import Image
from reportlab.pdfgen import canvas

from hearth import office, uploads
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import ConnectorError, read_config
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage


def image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (40, 25), "purple").save(output, "PNG")
    return output.getvalue()


def pdf_bytes():
    output = io.BytesIO()
    pdf = canvas.Canvas(output)
    pdf.drawString(100, 700, "The library book club meets Saturday. Bring a favorite book.")
    pdf.save()
    return output.getvalue()


def multipart(filename, data, claimed="application/octet-stream"):
    boundary = "hearth-test-boundary"
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {claimed}\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


class UploadsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.storage = Storage(temporary.name)
        config = read_config(ROOT / "config/connectors.json")
        self.app = Application(self.storage, LocalCheckpoints(self.storage), config)
        self.server = HTTPServer(("127.0.0.1", 0), self.app)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def request(self, path, *, body=None, raw=None, content_type="application/json", origin=None):
        if body is not None:
            raw = json.dumps(body, ensure_ascii=False).encode()
        headers = {"Content-Type": content_type, "Origin": origin or self.base}
        request = Request(self.base + path, data=raw, headers=headers)
        return build_opener(ProxyHandler({})).open(request, timeout=25)

    def data(self, path, **kwargs):
        with self.request(path, **kwargs) as response:
            return json.load(response)

    def upload(self, filename, data, *, thread="main", claimed="text/plain", origin=None):
        raw, content_type = multipart(filename, data, claimed)
        with self.request("/api/uploads?" + urlencode({"thread": thread}), raw=raw,
                          content_type=content_type, origin=origin) as response:
            self.assertEqual(response.status, 201)
            return json.load(response)

    def turn(self, items, prompt=""):
        with self.request("/api/chat", body={"message": prompt, "attachment_ids": [item["id"] for item in items]}) as response:
            packets = [packet.splitlines() for packet in response.read().decode().strip().split("\n\n")]
            return {lines[0][7:]: json.loads(lines[1][6:]) for lines in packets}

    def test_limit_exact_and_over_and_truncated_envelope(self):
        raw = b"a" * uploads.MAX_BYTES
        item = self.upload("notes.txt", raw)
        self.assertEqual(item["size"], uploads.MAX_BYTES)
        with self.assertRaises(HTTPError) as bad:
            self.upload("too-long.txt", raw + b"a")
        self.assertEqual(bad.exception.code, 413)
        bad.exception.close()
        body, content_type = multipart("interrupted.txt", b"hello")
        with self.assertRaises(uploads.UploadError):
            uploads.receive(io.BytesIO(body[:-9]), len(body) - 9, content_type, io.BytesIO())
        self.assertEqual(len(list(self.app.uploads.directory("main").iterdir())), 1)
        self.assertEqual(len(self.data("/api/timeline")["entries"]), 1)

    def test_sniffing_path_scope_and_origin(self):
        item = self.upload("../../图书/photo.png", image_bytes(), claimed="text/html")
        self.assertEqual((item["filename"], item["mime"]), ("photo.png", "image/png"))
        query = urlencode({"thread": "main", "id": item["id"]})
        with self.request("/api/uploads/file?" + query) as response:
            self.assertEqual(response.read(), image_bytes())
            self.assertIn("attachment", response.headers["Content-Disposition"])
        with self.request("/api/uploads/file?" + query + "&thumbnail=1") as response:
            self.assertEqual(response.headers.get_content_type(), "image/jpeg")
            self.assertTrue(response.read().startswith(b"\xff\xd8"))
        side = self.data("/api/threads/create", body={})["id"]
        for call, status in (
            (lambda: self.upload("sheet.xlsx", b"MZ\x00not Excel"), 415),
            (lambda: self.upload("photo.svg", b"<svg></svg>"), 415),
            (lambda: self.upload("notes.txt", b"\x00binary"), 415),
            (lambda: self.upload("photo.png", image_bytes(), thread="../../main"), 400),
            (lambda: self.upload("photo.png", image_bytes(), origin="https://elsewhere.invalid"), 403),
            (lambda: self.data("/api/uploads/detail?" + urlencode({"thread": side, "id": item["id"]})), 404),
            (lambda: self.data("/api/uploads/detail?thread=main&id=../state.json"), 404),
            (lambda: self.data("/api/chat", body={"message": "Read", "thread_id": side,
                                                  "attachment_ids": [item["id"]]}), 400),
        ):
            with self.subTest(status=status), self.assertRaises(HTTPError) as bad:
                call()
            self.assertEqual(bad.exception.code, status)
            bad.exception.close()

    def test_chinese_office_pdf_and_text_extraction(self):
        document = {"title": "社区活动", "sections": [{"heading": "图书馆", "paragraphs": ["欢迎参加读书会。"]}]}
        sheets = {"title": "花费", "sheets": [
            {"name": "预算", "headers": ["物品", "价钱"], "rows": [["红茶", 48]]},
            {"name": "审核", "headers": ["批准人"], "rows": [["林晓"]]},
        ]}
        slides = {"title": "旅行", "slides": [{"title": "博物馆", "bullets": ["下午集合"]}]}
        fixtures = {
            "docx": (office.generate("docx", office.prepare("docx", document)), "欢迎参加读书会"),
            "pdf": (pdf_bytes(), "Bring a favorite book"),
            "xlsx": (office.generate("xlsx", office.prepare("xlsx", sheets)), "林晓"),
            "pptx": (office.generate("pptx", office.prepare("pptx", slides)), "下午集合"),
            "txt": ("社区活动".encode("gb18030"), "社区活动"),
            "md": ("# 中文标题".encode("utf-16"), "中文标题"),
            "csv": ("名称,价钱\n红茶,48".encode(), "红茶,48"),
        }
        for fmt, (raw, expected) in fixtures.items():
            with self.subTest(fmt=fmt):
                item = self.upload(f"样例.{fmt}", raw)
                row, directory = self.app.uploads.get("main", item["id"])
                text, truncated = uploads.extract(directory / "file", row)
                self.assertEqual(item["format"], fmt)
                self.assertIn(expected, text)
                self.assertFalse(truncated)
        self.assertEqual(uploads.capped_text(["中" * (uploads.MAX_TEXT + 1)]), ("中" * uploads.MAX_TEXT, True))

    def test_mock_multipart_message_history_citations_and_explicit_box_save(self):
        image = self.upload("Waterfront.png", image_bytes())
        pdf = self.upload("Book club.pdf", pdf_bytes())
        with patch("hearth.uploads.vision") as vision, patch.object(self.app.artifacts, "client") as client:
            done = self.turn([image, pdf])["done"]["message"]
            vision.assert_not_called()
            client.assert_not_called()
        self.assertIn("Demo image description", done["content"])
        self.assertIn("Demo PDF summary", done["content"])
        self.assertIn("library book club", done["content"])
        self.assertEqual(done["attachment_citations"], [image["id"], pdf["id"]])
        state = self.data("/api/state")
        self.assertEqual(state["messages"][0]["attachment_ids"], [image["id"], pdf["id"]])
        self.assertEqual(state["message_uploads"], {item["id"]: item for item in (image, pdf)})
        followup = self.turn([pdf], "Can you make a summary of the attached PDF?")["done"]["message"]
        self.assertIn("Demo PDF summary", followup["content"])
        self.assertNotIn("artifacts", followup)
        client = Mock()
        client.folders.return_value = {"Attachments": "77"}
        client.upload.return_value = {"id": "1234"}
        with patch.object(self.app.artifacts, "client", return_value=client), \
                patch.object(self.app.artifacts, "bootstrap", return_value={"root": "10"}):
            for _ in range(2):
                saved = self.data("/api/uploads/box", body={"thread_id": "main", "id": pdf["id"]})
                self.assertEqual(saved["box_url"], "https://app.box.com/file/1234")
        client.upload.assert_called_once()
        stored, data, folder = client.upload.call_args.args
        self.assertEqual((stored["mime"], folder), ("application/pdf", "77"))
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual([call[0] for call in client.method_calls], ["folders", "upload"])
        entries = [row for row in self.data("/api/timeline")["entries"] if row["kind"] == "upload"]
        self.assertEqual(len(entries), 3)

    def test_image_vision_fallback_and_audio_use_existing_whisper(self):
        png = self.upload("scene.png", image_bytes())
        wav = self.upload("speech.wav", b"RIFF\x04\x00\x00\x00WAVE")
        models = Mock()
        models.completion.side_effect = [ConnectorError("unavailable", 503), {"content": "紫色背景"}]
        connection = {"provider": "huggingface", "connection_id": "fixture"}
        with patch("hearth.uploads.voice.transcribe", return_value="我喜欢图书馆") as whisper:
            sources = self.app.uploads.understand("main", [{"attachment_ids": [png["id"], wav["id"]]}],
                                                  "有什么？", gateway=models, connection=connection, mock=False)
        self.assertEqual([source["text"] for source in sources], ["紫色背景", "我喜欢图书馆"])
        self.assertEqual([call.args[0]["model"] for call in models.completion.call_args_list],
                         list(uploads.VISION_MODELS))
        self.assertTrue(models.completion.call_args.args[1][0]["content"][1]["image_url"]["url"]
                        .startswith("data:image/jpeg;base64,"))
        whisper.assert_called_once_with(models, connection, b"RIFF\x04\x00\x00\x00WAVE", "audio/wav", "auto")


if __name__ == "__main__":
    unittest.main()
