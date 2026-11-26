import io
import json
import secrets
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from PIL import Image

from hearth.agent import tool_call
from hearth import page_agent, page_html, page_policy, router
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import ConnectorError, read_config
from hearth.page_public import ShareServer
from hearth.server import Application, HTTPServer
from hearth.storage import HearthError, ROOT, Storage, atomic_write
from hearth.threads import MAIN


DEMO = "Make a page for our Thanksgiving dinner."


def seed_legacy_page(app):
    identity = "a" * 32
    at = "2026-11-24T17:00:00+00:00"
    title = "Weekend market guide"
    raw = page_html.sanitize("<main><h1>Weekend market guide</h1><p>Saturday at 9 AM.</p></main>", title, {})
    with app.storage.lock():
        atomic_write(app.storage.live / "pages" / identity / "v1" / "index.html", raw)
        state = app.storage.load()
        state["pages"] = {identity: {"id": identity, "title": title, "version": 1, "updated_at": at,
                                   "versions": [{"version": 1, "at": at, "note": "Built from chat."}],
                                   "thread_id": MAIN, "thread_title": "Main"}}
        state["actions"][identity] = {"id": identity, "kind": "page", "title": f"Built page · {title}",
                                      "at": at, "status": "complete", "thread_id": MAIN, "thread_title": "Main",
                                      "page_id": identity, "page_version": 1, "previous_version": None}
        app.storage.save(state)
        app.threads.append(MAIN, "assistant", "Your page is ready to preview.",
                           pages=[{"id": identity, "title": title, "version": 1, "updated_at": at, "thread_id": MAIN}])
    return identity, raw


def request(origin, path, payload=None, *, method=None, headers=None, raw=None):
    content = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else raw
    args = {"Content-Type": "application/json"} if payload is not None else {}
    try:
        response = build_opener(ProxyHandler({})).open(
            Request(origin + path, data=content, method=method, headers={**args, **(headers or {})}), timeout=15)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read()


class Running:
    def start(self, server):
        self.addCleanup(server.server_close)
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 5)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"


class PageHTMLTests(unittest.TestCase):
    def test_strips_network_markup_css_and_non_attachment_images(self):
        identity = "a" * 32
        source = f"""<!doctype html><html lang="zh-CN"><head>
        <meta http-equiv="refresh" content="0;url=https://example.invalid">
        <base href="https://example.invalid">
        <style>
          @import "https://example.invalid/a.css";
          @font-face {{src:url("https://example.invalid/font")}}
          p {{ color: #124; background: u\\72l("https://example.invalid/image"); }}
          @media (prefers-color-scheme: dark) {{ p {{ color: #def; --bad:image-set("https://example.invalid") }} }}
        </style></head><body onload="fetch('/api/state')">
        <h1 id="title" onclick="navigator.sendBeacon('/api/state')">野餐</h1>
        <form action="https://example.invalid"><p>水果和水</p><input formaction="/api/undo"></form>
        <iframe src="/api/state"></iframe><script src="/app.js"></script><script>fetch('/api/state')</script>
        <svg><foreignObject><div>discard</div></foreignObject></svg>
        <a href="#title" ping="https://example.invalid">返回顶部</a>
        <a href="https://example.invalid" download="bad">outside</a>
        <img src="https://example.invalid"><img src="data:image/png;base64,AAAA">
        <img src="hearth-image:{identity}" srcset="https://example.invalid 2x" alt="水果">
        <p style="color: #222; background: image-set('https://example.invalid')">散步</p>
        </body></html>"""
        raw = page_html.sanitize(source, "周日野餐", {identity: lambda: b"attachment bytes"}).decode()
        for forbidden in ("example.invalid", "<iframe", "<script", "<form", "<svg", "<input", "onclick",
                          "onload", "sendBeacon", "srcset", "discard", "AAAA"):
            self.assertNotIn(forbidden, raw)
        for expected in ('href="#title"', "水果和水", 'lang="zh-CN"', "#124", "#def", "#222",
                         "data:image/jpeg;base64,YXR0YWNobWVudCBieXRlcw==", 'alt="水果"', "prefers-color-scheme"):
            self.assertIn(expected, raw)
        self.assertIn("hearth-image:" + identity, page_html.editable(raw.encode()))
        self.assertNotIn("base64,", page_html.editable(raw.encode()))

    def test_rejects_missing_or_placeholder_content(self):
        for invalid in ("Sounds good!", "<html><script>noop()</script></html>", "<main>Lorem ipsum</main>"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(HearthError, "HTML|content"):
                page_html.sanitize(invalid, "Custom")


class PageHTTPTests(Running, unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.storage = Storage(folder.name)
        config = read_config(ROOT / "config/connectors.json")
        config["brain"] = {"provider": "mock", "model": ""}
        self.app = Application(self.storage, LocalCheckpoints(self.storage), config)
        self.origin = self.start(HTTPServer(("127.0.0.1", 0), self.app))

    def json(self, path, payload=None, expected=200, **kwargs):
        status, _, body = request(self.origin, path, payload, **kwargs)
        self.assertEqual(status, expected, body)
        return json.loads(body)

    def chat(self, message, thread_id=MAIN):
        status, _, body = request(self.origin, "/api/chat", {"message": message, "thread_id": thread_id})
        self.assertEqual(status, 200)
        events = [packet.split("\ndata: ", 1) for packet in body.decode().strip().split("\n\n")
                  if packet.startswith("event: ")]
        self.assertEqual(events[-1][0], "event: done", events[-1])
        return json.loads(events[-1][1])["message"]

    def build(self):
        message = self.chat(DEMO)
        self.assertEqual(message["content"], "Your page is ready to preview.")
        self.assertEqual(len(message["artifacts"]), 1)
        return message["artifacts"][0]

    def test_mock_build_is_a_page_artifact_with_private_html(self):
        page = self.build()
        identity = page["id"]
        index = self.json("/api/artifacts")
        self.assertEqual(index["artifacts"], [page])
        self.assertEqual((page["kind"], page["format"], page["version_number"]), ("page", "html", 1))
        self.assertEqual(index["timezone"], "America/Los_Angeles")
        status, headers, raw = request(self.origin, f"/pages/{identity}")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Security-Policy"], page_policy.CSP)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn(b"mushroom and lentil pie", raw.lower())
        self.assertIn(b"Maya and Daniel", raw)
        self.assertEqual(raw, (self.storage.live / "pages" / identity / "v1" / "index.html").read_bytes())
        status, headers, downloaded = request(self.origin, f"/pages/{identity}/v/1?download=1")
        self.assertEqual(status, 200)
        self.assertIn("attachment; filename*=UTF-8''Thanksgiving%20dinner.html", headers["Content-Disposition"])
        self.assertEqual(raw, downloaded)
        status, headers, downloaded = request(self.origin, f"/api/artifacts/file?id={identity}")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertEqual(headers["Content-Security-Policy"], page_policy.CSP)
        self.assertTrue(headers["Content-Disposition"].startswith("attachment;"))
        self.assertEqual(raw, downloaded)
        self.json(f"/api/artifacts/file?id={identity}&inline=1", expected=400)
        self.assertEqual(self.json("/api/state")["messages"][-1]["artifacts"], [page])
        self.assertEqual(self.json("/api/home")["builtin"]["files"]["items"],
                         [{"id": identity, "title": page["title"], "format": "html", "kind": "page"}])

    def test_existing_pages_appear_without_rewriting_versions_or_share_links(self):
        identity, raw = seed_legacy_page(self.app)
        token = secrets.token_urlsafe(32)
        with self.storage.lock():
            state = self.storage.load()
            state["pages"][identity]["share"] = {"token": token, "origin": "", "version": 1, "status": "active"}
            self.storage.save(state)
            before = self.storage.state.read_bytes()
        for _ in range(2):
            art = self.json("/api/artifacts")["artifacts"]
            self.assertEqual([(row["id"], row["kind"], row["version_number"]) for row in art], [(identity, "page", 1)])
        detail = self.json(f"/api/artifacts/detail?id={identity}")
        self.assertEqual(detail["versions"][0]["note"], "Built from chat.")
        self.assertEqual(detail["share"]["url"], f"/p/{token}")
        self.assertEqual(raw, request(self.origin, f"/p/{token}")[2])
        self.assertEqual(raw, request(self.origin, f"/pages/{identity}")[2])
        titles = [row["title"] for row in self.json("/api/timeline")["entries"] if row["kind"] == "page"]
        self.assertEqual(titles, ["Page created · Weekend market guide"])
        self.assertEqual(before, self.storage.state.read_bytes())

    def test_edit_revert_and_timeline_undo_are_versioned(self):
        identity = self.build()["id"]
        original = request(self.origin, f"/pages/{identity}/v/1")[2]
        edited = self.chat("Make the header green.")["artifacts"][0]
        self.assertEqual((identity, 2), (edited["id"], edited["version_number"]))
        self.assertEqual(self.json("/api/artifacts")["artifacts"], [edited])
        self.assertIn(b"--hero:#245846", request(self.origin, f"/pages/{identity}")[2])
        detail = self.json(f"/api/artifacts/detail?id={identity}")
        self.assertEqual(detail["versions"][1]["note"], "Made the header green.")
        self.json("/api/pages/revert", {"id": identity, "version": 1, "current": 1}, expected=409)
        reverted = self.json("/api/pages/revert", {"id": identity, "version": 1, "current": 2})
        self.assertEqual(reverted["version"], 3)
        self.assertEqual(original, request(self.origin, f"/pages/{identity}/v/3")[2])
        timeline = [row for row in self.json("/api/timeline")["entries"] if row["kind"] == "page"]
        actions = {row["data"]["page_version"]: row for row in timeline}
        self.assertEqual(len(actions), 3)
        self.assertEqual([actions[n]["title"] for n in (1, 2, 3)], [
            "Page created · Thanksgiving dinner", "Page updated · Thanksgiving dinner", "Page updated · Thanksgiving dinner",
        ])
        self.assertTrue(actions[3]["undoable"])
        self.assertFalse(actions[2]["undoable"])
        self.json("/api/undo", {"id": actions[1]["action_id"]}, expected=409)
        for version in (3, 2, 1):
            result = self.json("/api/undo", {"id": actions[version]["action_id"]})
            self.assertTrue(result["undone"])
        self.assertEqual(self.json("/api/pages")["pages"], [])
        self.assertEqual(self.json("/api/artifacts")["artifacts"], [])
        self.assertEqual(request(self.origin, f"/pages/{identity}")[0], 404)

    def test_share_requires_approval_stays_on_one_version_and_revokes(self):
        identity = self.build()["id"]
        request_data = {"id": identity, "version": 1}
        blocked = request(self.origin, "/api/pages/share", request_data, headers={"Origin": "https://elsewhere.invalid"})
        self.assertEqual(blocked[0], 403)
        action = self.json("/api/pages/share", request_data)
        self.assertEqual(action["status"], "pending")
        detail = self.json(f"/api/artifacts/detail?id={identity}")
        self.assertNotIn("share", detail)
        self.assertEqual(detail["approval"]["id"], action["id"])
        self.json("/api/approve", {"id": action["id"]})
        shared = self.json(f"/api/pages/detail?id={identity}")["share"]["url"]
        self.assertRegex(shared, r"^/p/[A-Za-z0-9_-]{43}$")
        status, headers, approved = request(self.origin, shared)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Security-Policy"], page_policy.PUBLIC_CSP)
        self.assertEqual(request(self.origin, shared, {"change": "x"})[0], 405)
        self.chat("Make the header green.")
        self.assertEqual(approved, request(self.origin, shared)[2])
        self.json("/api/pages/revoke", {"id": identity})
        self.assertEqual(request(self.origin, shared)[0], 404)
        self.json("/api/approve", {"id": action["id"]}, expected=409)

    def test_build_uses_a_single_clarification_and_accepts_the_followup(self):
        model = {"provider": "huggingface", "model": router.KIMI}
        ask = {"content": '{"question":"What time should I list? Did anyone RSVP?"}'}
        build = tool_call("build_page", {"title": "Lunch invite", "brief": "One-page invite", "content": "Noon."})
        html = {"content": ('<html><head><style>@media (prefers-color-scheme: dark) '
                            '{body {color: #eee; background: #111}}</style></head>'
                            '<main><h1>Lunch invite</h1><p>Noon.</p></main></html>')}
        with patch.object(page_agent, "model_candidates", return_value=[model]), \
                patch.object(self.app.agent, "model_completion", side_effect=[ask, build, ask, ask]), \
                patch.object(self.app.gateway, "completion", return_value=html):
            question = self.chat("Make a lunch invite page.")
            self.assertEqual(question["content"], "What time should I list?")
            self.assertTrue(question["page_question"])
            self.assertEqual(self.json("/api/pages")["pages"], [])
            answer = self.chat("Noon.")
            self.assertEqual(answer["artifacts"][0]["title"], "Lunch invite")
            self.chat("Make another lunch invite page.")
            unresolved = self.chat("I don't know.")
            self.assertNotIn("page_question", unresolved)
            self.assertNotIn("?", unresolved["content"])

    def test_generator_can_embed_a_real_chat_attachment(self):
        file = io.BytesIO()
        Image.new("RGB", (18, 18), "green").save(file, format="PNG")
        raw = (b'--upload\r\nContent-Disposition: form-data; name="file"; filename="trail.png"\r\n'
               b'Content-Type: image/png\r\n\r\n' + file.getvalue() + b"\r\n--upload--\r\n")
        status, _, response = request(self.origin, "/api/uploads?thread=main", method="POST", raw=raw,
                                      headers={"Content-Type": "multipart/form-data; boundary=upload"})
        self.assertEqual(status, 201, response)
        identity = json.loads(response)["id"]
        model = {"provider": "huggingface", "model": router.KIMI}
        planned = tool_call("build_page", {"title": "Trail", "brief": "Use my photo", "content": "Trail photo"})
        html = {
            "content": ('<html><head><style>@media (prefers-color-scheme: dark) {body {color:#fff}}</style></head>'
                        f'<main><h1>Trail</h1><img src="hearth-image:{identity}" alt="Trail photo"></main></html>')
        }
        with patch.object(page_agent, "model_candidates", return_value=[model]), \
                patch.object(self.app.agent, "model_completion", return_value=planned), \
                patch.object(self.app.gateway, "completion", return_value=html):
            status, _, response = request(self.origin, "/api/chat", {"message": "Make a trail page with this photo.",
                                                        "thread_id": MAIN, "attachment_ids": [identity]})
        self.assertEqual(status, 200)
        self.assertIn(b"event: done", response, response)
        page = self.json("/api/pages")["pages"][0]
        content = request(self.origin, "/pages/" + page["id"])[2]
        self.assertIn(b'src="data:image/jpeg;base64,', content)
        self.assertIn(b'alt="Trail photo"', content)

    def test_box_upload_is_manual_and_reuses_a_receipt(self):
        class BoxFixture:
            def folders(self, parent, labels):
                folders.append((parent, labels))
                return {"Pages": "123"}

            def upload(self, row, raw, folder):
                receipts.append((row, raw, folder))
                return {"id": "456"}

        folders, receipts = [], []
        fixture = BoxFixture()
        with patch.object(self.app.artifacts, "client", return_value=fixture) as client, \
                patch.object(self.app.artifacts, "bootstrap", return_value={"root": "42"}):
            identity = self.build()["id"]
            client.assert_not_called()
            body = {"id": identity, "version": 1}
            self.assertEqual(self.json("/api/pages/box", body), self.json("/api/pages/box", body))
            with patch.object(self.app.artifacts, "walk", return_value={"box-456": {"box_id": "456"}}):
                artifacts = self.json("/api/artifacts")["artifacts"]
            self.assertEqual([(item["id"], item["sync"]) for item in artifacts], [(identity, "synced")])
            self.assertEqual(artifacts[0]["box_url"], "https://app.box.com/file/456")
        row, raw, folder = receipts[0]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(folders, [("42", ["Pages"])])
        self.assertEqual(folder, "123")
        self.assertTrue(row["filename"].endswith(".html"))
        self.assertIn(b"Thanksgiving dinner", raw)


class PublicServerTests(Running, unittest.TestCase):
    def test_only_capability_route_is_public_and_revoke_survives_retries(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        secret = secrets.token_urlsafe(32)
        origin = self.start(ShareServer(("127.0.0.1", 0), Path(folder.name), secret))
        token = secrets.token_urlsafe(32)
        publish, share = "/_publish/" + token, "/p/" + token
        auth = {"Authorization": "Bearer " + secret}
        raw = b"<!doctype html><h1>Approved page</h1>"
        self.assertEqual(request(origin, publish, method="PUT", raw=raw)[0], 404)
        self.assertEqual(request(origin, share, method="PUT", raw=raw, headers=auth)[0], 404)
        self.assertEqual(request(origin, publish, method="PUT", raw=raw, headers=auth)[0], 204)
        self.assertEqual(request(origin, publish, method="PUT", raw=raw, headers=auth)[0], 204)
        status, headers, received = request(origin, share)
        self.assertEqual((status, received), (200, raw))
        self.assertEqual(headers["Content-Security-Policy"], page_policy.PUBLIC_CSP)
        for route in ("/", "/api/state", "/api/pages", "/pages/" + "a" * 32, publish):
            self.assertEqual(request(origin, route)[0], 404)
        self.assertEqual(request(origin, publish, method="DELETE", headers=auth)[0], 204)
        self.assertEqual(request(origin, publish, method="PUT", raw=raw, headers=auth)[0], 409)
        self.assertEqual(request(origin, share)[0], 404)


class PagePlannerTests(unittest.TestCase):
    def test_clarification_intent_and_edit_precedence(self):
        self.assertEqual(page_agent.intent("Build a website for lunch.", None, None), "build_page")
        self.assertEqual(page_agent.intent("请制作一个中文网页", None, None), "build_page")
        self.assertEqual(page_agent.intent("At home, Saturday at 4.", None, {"page_question": True}), "build_page")
        self.assertEqual(page_agent.intent("Make the header green.", {"id": "abc"}, None), "edit_page")
        self.assertIsNone(page_agent.intent("Make a one-page PDF.", {"id": "abc"}, None))
        self.assertIsNone(page_agent.intent("Read this website.", None, None))

    def test_coding_falls_back_to_deepseek(self):
        class Gateway:
            def completion(self, model, messages, tools, emit, **kwargs):
                calls.append(model["model"])
                if model["model"] == router.KIMI:
                    raise ConnectorError("Fixture timeout.")
                return {"content": ('<html lang="zh"><head><style>@media (prefers-color-scheme: dark) '
                                    '{body {color: #eee; background: #111}}</style></head>'
                                    '<main><h1>野餐</h1></main></html>')}

        class Agent:
            tools = type("Tools", (), {"gateway": Gateway()})()

        calls = []
        models = [{"model": name} for name in (router.KIMI, router.PRO)]
        raw, used = page_agent.code(Agent(), models, "野餐", {"content": "野餐"}, {}, {})
        self.assertEqual(calls, [router.KIMI, router.PRO])
        self.assertEqual(used["model"], router.PRO)
        self.assertIn("野餐".encode(), raw)


if __name__ == "__main__":
    unittest.main()
