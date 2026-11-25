import hashlib
import json
import tempfile
import threading
import unittest
from email import policy
from email.parser import BytesParser
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from unittest.mock import patch

from hearth import box, office
from hearth.agent import FILE_TOOL_MODES, tool_call
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import Gateway, read_config
from hearth.server import Application, HTTPServer
from hearth.storage import HearthError, ROOT, Storage, iso, new_id


class MockBox:
    """Simulate the gateway at the HTTP boundary, including multipart uploads."""

    def __init__(self):
        self.requests = []
        self.next_id = 100
        self.folders = {"0": {"id": "0", "name": "All Files", "type": "folder", "parent": None}}
        self.files = {}
        self.reject_upload = None
        self.reject_versions = False

    def allocate(self):
        self.next_id += 1
        return str(self.next_id)

    def add_file(self, parent, name, content):
        identity = self.allocate()
        item = {"id": identity, "name": name, "type": "file", "parent": parent,
                "created_at": iso(), "versions": [], "trashed": False}
        self.files[identity] = item
        self.add_version(item, content)
        return item

    def add_version(self, item, content):
        item["versions"].append({"id": self.allocate(), "modified_at": iso(), "content": content,
                                 "version_number": str(len(item["versions"]) + 1)})

    def metadata(self, item):
        current = item["versions"][-1]
        return {**{key: item[key] for key in ("id", "name", "type", "created_at")},
                "version_number": current["version_number"], "file_version": {"id": current["id"]},
                "etag": current["version_number"], "modified_at": current["modified_at"],
                "size": len(current["content"]), "sha1": hashlib.sha1(current["content"]).hexdigest()}

    @staticmethod
    def response(data):
        return BytesIO(json.dumps(data).encode())

    @staticmethod
    def fail(request, status, body=None):
        raise HTTPError(request.full_url, status, "Private connector detail", {},
                        BytesIO(json.dumps(body or {"message": "private-provider-details"}).encode()))

    def open(self, request, timeout):
        self.requests.append(request)
        assert not request.has_header("Authorization")
        url, method = urlsplit(request.full_url), request.get_method()
        assert url.netloc == "api.sprites.dev"
        if url.path == "/v1/gateway/list":
            return self.response({"connections": [
                {"provider": "box", "authorized": True, "gateway_base_url": "https://api.sprites.dev/v1/gateway/box/qa_Box"}]})
        assert url.path.startswith("/v1/gateway/box/qa_Box/")
        route, *parts = url.path.split("/")[5:]
        upload = method == "POST" and parts[-1] == "content"
        assert route == ("upload" if upload else "2.0")
        if method == "GET" and len(parts) == 3 and parts[0] == "folders":
            parent = parts[1]
            if parent not in self.folders:
                self.fail(request, 404)
            entries = [item for item in self.folders.values() if item["parent"] == parent]
            entries.extend(self.metadata(item) for item in self.files.values()
                           if item["parent"] == parent and not item["trashed"])
            offset = int(parse_qs(url.query).get("marker", ["0"])[0])
            return self.response({"entries": entries[offset:offset + 3],
                                  "next_marker": str(offset + 3) if offset + 3 < len(entries) else None})
        if method == "POST" and parts == ["folders"]:
            data = json.loads(request.data)
            parent, name = data["parent"]["id"], data["name"]
            if any(item["parent"] == parent and item["name"].casefold() == name.casefold()
                   for item in self.folders.values()):
                self.fail(request, 409)
            identity = self.allocate()
            self.folders[identity] = item = {"id": identity, "name": name, "type": "folder", "parent": parent}
            return self.response(item)
        assert parts[0] == "files"
        if method == "POST" and parts[-1] == "content":
            if self.reject_upload:
                status, body = self.reject_upload
                self.fail(request, status, body)
            envelope = f"Content-Type: {request.get_header('Content-type')}\r\n\r\n".encode() + request.data
            fields = list(BytesParser(policy=policy.default).parsebytes(envelope).iter_parts())
            assert [part.get_param("name", header="Content-Disposition") for part in fields] == ["attributes", "file"]
            attributes = json.loads(fields[0].get_payload(decode=True))
            content = fields[1].get_payload(decode=True)
            suffix = fields[1].get_filename().rpartition(".")[-1]
            assert fields[1].get_content_type() == box.FORMATS[suffix]
            if len(parts) == 2:
                assert fields[1].get_filename() == attributes["name"]
                parent = attributes["parent"]["id"]
                if parent not in self.folders:
                    self.fail(request, 404)
                if any(item["parent"] == parent and item["name"] == attributes["name"] and not item["trashed"]
                       for item in self.files.values()):
                    self.fail(request, 409)
                item = self.add_file(parent, attributes["name"], content)
            else:
                item = self.files[parts[1]]
                assert attributes == {}
                assert request.get_header("If-match") == self.metadata(item)["etag"]
                self.add_version(item, content)
            return self.response({"entries": [self.metadata(item)]})
        item = self.files.get(parts[1])
        if not item:
            self.fail(request, 404)
        assert method == "GET"
        if len(parts) == 2:
            return self.response(self.metadata(item))
        if parts[2] == "versions":
            if self.reject_versions:
                self.fail(request, 403, {"error": "request is not supported by this connector"})
            return self.response({"entries": [{key: value for key, value in version.items() if key != "content"}
                                               for version in reversed(item["versions"][:-1])]})
        assert parts[2] == "content"
        version_id = parse_qs(url.query).get("version", [item["versions"][-1]["id"]])[0]
        return BytesIO(next(version["content"] for version in item["versions"] if version["id"] == version_id))


class ArtifactTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.provider = MockBox()
        gateway = Gateway()
        gateway.opener = self.provider
        self.storage = Storage(scratch.name)
        self.app = Application(self.storage, LocalCheckpoints(self.storage),
                               read_config(ROOT / "config/connectors.json"), gateway=gateway)
        self.app.scan_connections()
        self.server = HTTPServer(("127.0.0.1", 0), self.app)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.origin = f"http://127.0.0.1:{self.server.server_port}"

    def request(self, path, data=None, **headers):
        raw = None if data is None else json.dumps(data).encode()
        request = Request(self.origin + path, data=raw,
                          headers={"Content-Type": "application/json", "Origin": self.origin, **headers})
        try:
            response = build_opener(ProxyHandler({})).open(request, timeout=8)
        except HTTPError as error:
            response = error
        with response:
            if response.headers.get_content_type() == "text/event-stream":
                return response.status, [json.loads(line[6:]) for line in response.read().decode().splitlines()
                                         if line.startswith("data: ")]
            return response.status, json.load(response)

    def endpoint(self, path="", data=None, **headers):
        return self.request("/api/artifacts" + path, data, **headers)

    def create(self, title="Dinner plan", content="Dinner at six.", fmt="docx"):
        return self.app.artifacts.create(fmt, {"title": title, "sections": [{"paragraphs": [content]}]},
                                         kind="plan", origin={"thread_id": "main", "thread_title": "Main"})

    def update(self, item, content="Updated dinner."):
        return self.app.artifacts.update(item["format"], item["id"], item["revision"],
                                         {"title": item["title"], "sections": [{"paragraphs": [content]}]})

    def download(self, item, inline=False):
        suffix = "&inline=1" if inline else ""
        with build_opener(ProxyHandler({})).open(
                self.origin + "/api/artifacts/file?id=" + item["id"] + suffix, timeout=5) as response:
            return response.headers, response.read()

    def detail(self, item):
        status, detail = self.endpoint("/detail?id=" + item["id"])
        self.assertEqual(status, 200, detail)
        return detail

    def undo(self, operation):
        rows = self.request("/api/timeline")[1]["entries"]
        action = next(item for item in reversed(rows) if item["title"].startswith("Artifact " + operation))
        return self.endpoint("/undo", {"id": action["action_id"]})

    def test_bootstrap_upload_new_version_local_receipts_and_undo(self):
        self.assertEqual(len(self.provider.folders), 1)
        item = self.create(title="../Dinner\r\nplan", content="Dinner at six.\npassword: demo-secret")
        self.assertEqual(item["sync"], "synced")
        self.assertEqual(item["box_url"], "https://app.box.com/file/" + item["box_id"])
        self.assertNotIn("/", item["filename"])
        self.assertNotIn("\n", item["filename"])
        folders = json.loads(self.app.connections.path.read_text())["box_folders"]
        self.assertEqual(set(folders["kinds"]), set(box.FOLDERS))
        self.assertEqual(self.app.connections.load()["box_folders"], folders)
        self.assertEqual(len(self.provider.folders), 7)
        detail = self.detail(item)
        self.assertIn("[redacted]", detail["preview"]["blocks"][1]["text"])
        self.assertNotIn("demo-secret", str(detail))
        headers, raw = self.download(item)
        self.assertEqual(headers.get_content_type(), office.MIME_TYPES["docx"])
        self.assertIn("attachment;", headers["Content-Disposition"])
        self.assertEqual(raw, self.provider.files[item["box_id"]]["versions"][0]["content"])
        self.assertEqual(raw, self.app.artifacts.file_path(self.app.artifacts.find(item["id"])).read_bytes())

        updated = self.update(detail)
        self.assertEqual(updated["box_id"], item["box_id"])
        self.assertEqual(updated["version_number"], 2)
        self.assertNotEqual(self.download(item)[1], raw)
        self.provider.reject_versions = True
        fallback = self.detail(item)
        self.assertEqual(fallback["version_source"], "hearth")
        self.assertEqual([row["number"] for row in fallback["versions"]], [2, 1])
        self.assertEqual([row["box_version_id"] for row in fallback["versions"]],
                         [updated["version_id"], item["version_id"]])
        self.assertEqual(fallback["warnings"], [])
        self.assertEqual([row["id"] for row in self.endpoint()[1]["artifacts"]], [item["id"]])
        with self.assertRaisesRegex(HearthError, "changed"):
            self.update(detail, "Stale")
        self.assertEqual(self.undo("updated")[0], 200)
        self.assertEqual(self.download(item)[1], raw)
        self.assertEqual([row["number"] for row in self.detail(item)["versions"]], [3, 2, 1])
        self.assertEqual(len(self.provider.folders), 7)

    def test_pdf_download_and_inline_security_headers(self):
        item = self.create(fmt="pdf", title="Dinner.pdf")
        self.assertEqual(item["filename"], "Dinner.pdf")
        detail = self.detail(item)
        self.assertTrue(detail["inline_pdf"])
        headers, raw = self.download(item)
        self.assertEqual(headers.get_content_type(), "application/pdf")
        self.assertTrue(raw.startswith(b"%PDF"))
        inline_headers, inline_raw = self.download(item, inline=True)
        self.assertEqual(raw, inline_raw)
        self.assertTrue(inline_headers["Content-Disposition"].startswith("inline;"))
        self.assertIn("frame-ancestors 'self'", inline_headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_box_items_recursive_listing_and_trash_restore(self):
        self.create()
        folders = self.app.connections.config["box_folders"]
        child_id = self.provider.allocate()
        self.provider.folders[child_id] = {"id": child_id, "parent": folders["kinds"]["list"],
                                          "type": "folder", "name": "Kitchen"}
        outside = self.provider.add_file("0", "private.txt", b"outside tree")
        external = self.provider.add_file(child_id, "Shopping.csv", b"Item,Quantity\nCranberries,1\n")
        other = self.provider.add_file(folders["root"], "Menu.pdf", b"PDF")
        items = {item["title"]: item for item in self.endpoint()[1]["artifacts"]}
        self.assertEqual(set(items), {"Dinner plan", "Menu", "Shopping"})
        self.assertEqual(self.endpoint("/detail?id=box-" + outside["id"])[0], 400)
        self.assertEqual(items["Shopping"]["source"], "Box")
        self.assertEqual(items["Shopping"]["kind"], "list")
        self.assertEqual(items["Menu"]["box_id"], other["id"])
        self.assertNotIn("content", self.detail(items["Menu"]))
        detail = self.detail(items["Shopping"])
        self.assertEqual(detail["content"], "Item,Quantity\nCranberries,1\n")
        request_count = len(self.provider.requests)
        status, deleted = self.endpoint("/delete", {"id": detail["id"], "revision": detail["revision"]})
        self.assertEqual(status, 200)
        self.assertIn("file remains in Box", deleted["sync_message"])
        self.assertEqual(len(self.provider.requests), request_count)
        self.assertFalse(external["trashed"])
        self.assertEqual(len(self.endpoint()[1]["artifacts"]), 2)
        self.assertEqual(self.endpoint("/detail?id=" + detail["id"])[0], 400)
        self.assertEqual(self.undo("deleted")[0], 200)
        self.assertFalse(external["trashed"])
        self.assertEqual(len(self.endpoint()[1]["artifacts"]), 3)

    def test_upload_fallback_error_mapping_and_retry(self):
        self.provider.reject_upload = 403, {"error": "endpoint is not supported by the Box connector"}
        item = self.create()
        self.assertEqual(item["sync"], "local")
        self.assertEqual(item["sync_message"], box.UNAVAILABLE)
        self.assertEqual(self.detail(item)["preview"]["blocks"][1]["text"], "Dinner at six.")
        self.assertNotIn("box_id", item)
        self.provider.reject_upload = 403, {"message": "private-provider-details"}
        status, failed = self.endpoint("/retry", {"id": item["id"]})
        self.assertEqual(status, 200)
        self.assertEqual(failed["sync"], "error")
        self.assertIn("denied", failed["sync_message"])
        self.assertNotIn("private-provider-details", str(failed))
        self.provider.reject_upload = None
        self.assertEqual(self.endpoint("/retry", {"id": item["id"]})[1]["sync"], "synced")
        self.assertEqual(len(self.provider.files), 1)

    def test_box_upload_limit_counts_bytes(self):
        self.assertEqual(box.MAX_UPLOAD_BYTES, 50 * 1024 * 1024)
        client = self.app.artifacts.client()
        row = {"filename": "note.txt", "format": "txt"}
        raw = "ééé".encode()
        with patch.object(box, "MAX_UPLOAD_BYTES", 5):
            with self.assertRaisesRegex(HearthError, "50 MiB"):
                client.upload(row, raw, "0")
        with patch.object(box, "MAX_UPLOAD_BYTES", 6):
            client.upload(row, raw, "0")
        self.assertEqual(next(iter(self.provider.files.values()))["versions"][0]["content"], raw)

    def test_failed_version_sync_preserves_local_file_and_retry_receipt(self):
        item = self.create()
        old_raw = self.download(item)[1]
        self.provider.reject_upload = 403, {"error": "endpoint is not supported by the Box connector"}
        updated = self.update(item, "Local edit")
        self.assertEqual(updated["sync"], "local")
        self.assertNotEqual(self.download(item)[1], old_raw)
        self.assertEqual(self.detail(item)["preview"]["blocks"][1]["text"], "Local edit")
        self.assertEqual(self.detail(item)["versions"][1]["box_version_number"], "1")
        self.assertNotIn("box_version_id", self.detail(item)["versions"][0])
        self.provider.reject_upload = None
        self.assertEqual(self.endpoint("/retry", {"id": item["id"]})[1]["version_number"], 2)
        self.assertEqual(self.detail(item)["versions"][0]["box_version_number"], "2")

    def test_undo_first_sync_keeps_box_file_and_restores_previous_bytes(self):
        self.provider.reject_upload = 403, {"error": "request is not supported by this connector"}
        item = self.create()
        old_raw = self.download(item)[1]
        self.provider.reject_upload = None
        updated = self.update(item)
        self.assertEqual(updated["sync"], "synced")
        self.assertEqual(self.undo("updated")[0], 200)
        restored = self.detail(item)
        self.assertEqual(restored["box_id"], updated["box_id"])
        self.assertEqual(restored["versions"][0]["number"], 3)
        self.assertEqual(restored["versions"][0]["box_version_number"], "2")
        self.assertEqual(self.download(item)[1], old_raw)

    def test_external_box_version_cannot_be_overwritten_by_stale_tool(self):
        item = self.create()
        self.provider.add_version(self.provider.files[item["box_id"]], b"External edit")
        with self.assertRaisesRegex(HearthError, "changed in Box"):
            self.update(item)
        self.assertEqual(self.detail(item)["versions"][0]["number"], 1)

    def test_same_named_files_get_separate_box_ids(self):
        first = self.create()
        second = self.create()
        self.assertEqual(first["sync"], "synced")
        self.assertEqual(second["sync"], "synced")
        self.assertNotEqual(first["box_id"], second["box_id"])
        self.assertNotEqual(first["filename"], second["filename"])

    def test_settings_migrate_and_save_message_is_gone(self):
        self.app.connections.path.write_text(json.dumps({"artifacts": {
            "auto_save": False, "format": "csv", "folder_name": "Kitchen"}}))
        self.assertEqual(self.app.connections.load()["artifacts"],
                         {"auto_save": False, "folder_name": "Kitchen"})
        self.app.scan_connections()
        self.assertEqual(self.endpoint("/settings", {"auto_save": False, "folder_name": "Kitchen"})[0], 200)
        self.assertEqual(self.endpoint("/settings")[1]["settings"],
                         {"auto_save": False, "folder_name": "Kitchen"})
        self.assertEqual(self.endpoint("/settings", {"folder_name": "../nested"})[0], 400)
        self.assertEqual(self.endpoint("/settings", {"folder_name": "Okay"}, Origin="https://elsewhere.invalid")[0], 403)
        self.assertEqual(self.endpoint("/save-message", {"thread_id": "main", "message_id": "old"})[0], 404)
        self.assertEqual(self.endpoint("/update", {"id": "old", "content": "text"})[0], 404)

    def test_message_saved_text_is_listed_as_legacy_without_a_chip(self):
        self.create()
        folder = self.app.connections.config["box_folders"]["kinds"]["note"]
        remote = self.provider.add_file(folder, "Legacy chat.md", b"# Old reply")
        identity, message_id = new_id(), new_id()
        with self.storage.lock():
            state = self.storage.load()
            state["artifacts"][identity] = {
                "id": identity, "title": "Legacy chat", "kind": "note", "filename": "Legacy chat.md",
                "format": "md", "source": "Hearth", "content": "# Old reply", "size": 11, "sync": "synced",
                "created_at": iso(), "updated_at": iso(), "revision": new_id(), "thread_id": "main",
                "message_id": message_id, "from_message": True, "box_id": remote["id"],
                "box_connection": self.app.artifacts.connection(), "version_id": remote["versions"][0]["id"],
            }
            self.storage.save(state)
        legacy = next(row for row in self.endpoint()[1]["artifacts"] if row["id"] == identity)
        self.assertTrue(legacy["legacy"])
        self.assertNotIn(message_id, self.request("/api/state")[1]["message_artifacts"])
        detail = self.detail(legacy)
        self.assertEqual(detail["content"], "# Old reply")
        self.assertEqual(self.download(legacy)[1], b"# Old reply")
        self.assertEqual(self.endpoint("/delete", {"id": identity, "revision": detail["revision"]})[0], 200)
        self.assertFalse(remote["trashed"])

    def test_mock_thanksgiving_creates_two_real_files_with_reply_chips(self):
        _, events = self.request("/api/chat", {"message": "Plan Thanksgiving dinner"})
        done = events[-1]["message"]
        items = done["artifacts"]
        self.assertEqual({item["filename"] for item in items}, {"Thanksgiving plan.pdf", "Shopping list.xlsx"})
        self.assertTrue(any(event.get("title") == "Creating a file" for event in events))
        self.assertTrue(all(item["sync"] == "synced" for item in items))
        self.assertEqual(len(self.request("/api/state")[1]["message_artifacts"][done["id"]]), 2)

    def test_seattle_slide_retries_leaked_legacy_call_on_kimi_and_uses_real_result(self):
        from hearth import router

        prompt = "Can you create a slide for Seattle trip"
        # The reported bubble exposed `artifact_create>{"format": "markdown", ... "path": ...}`
        # with literal escaped newlines and a fabricated Markdown save.
        leaked = (
            'artifact_create>{"format": "markdown", "content": "# Seattle Trip\\n- Space Needle", '
            '"path": "Seattle Trip.md"}\nI saved the Markdown artifact. I can export to PDF or PNG.'
        )
        calls = []
        agent = self.app.agent
        agent.brain_mode = "huggingface"
        agent.models = [{"provider": "huggingface", "model": name, "tags": router.model_tags(
            {"provider": "huggingface", "model": name}, agent.config["brain_tags"])}
            for name in (router.KIMI, router.FLASH)]

        def completion(model, messages, tools, emit):
            calls.append(model["model"])
            if len(calls) == 1:
                for chunk in (leaked[:13], leaked[13:25], leaked[25:]):
                    emit(chunk)
                return {"role": "assistant", "content": leaked}
            if messages[-1]["role"] == "user":
                self.assertIn("structured tool calls", messages[0]["content"])
                return tool_call("create_presentation", {"title": "Seattle trip", "slides": [
                    {"title": "Seattle trip", "bullets": ["Pike Place Market"]}]})
            return {"role": "assistant", "content": "I also saved a Markdown and PNG version."}

        with patch.object(agent.tools.gateway, "completion", side_effect=completion):
            _, events = self.request("/api/chat", {"message": prompt})
        self.assertEqual(calls, [router.KIMI] * 3)
        self.assertEqual(events[-1]["message"]["artifacts"][0]["filename"], "Seattle trip.pptx")
        self.assertNotRegex(str(events), r"artifact_create|Markdown save|export to PDF or PNG|PNG version")
        self.assertEqual(len(events[-1]["message"]["artifacts"]), 1)

    def test_agent_gates_creation_and_updates_and_links_both_replies(self):
        agent = self.app.agent
        agent.models = [{"provider": "test-brain", "model": "test"}]
        observed = []

        def completion(model, messages, tools, emit):
            names = {tool["function"]["name"] for tool in tools} & FILE_TOOL_MODES.keys()
            prompt = next(message["content"] for message in reversed(messages) if message["role"] == "user")
            observed.append((prompt, names))
            last = messages[-1]
            if prompt.startswith("Make") and last["role"] == "user":
                return tool_call("create_presentation", {"title": "Dinner deck", "slides": [
                    {"title": "Main dishes", "bullets": ["Turkey"]}]})
            if prompt.startswith("add"):
                if last["role"] == "user":
                    original = self.app.artifacts.recent("main")[0]
                    return tool_call("read_artifact", {"artifact_id": original["id"]})
                current = json.loads(last["content"])
                if "slides" in current:
                    return tool_call("update_presentation", {"artifact_id": current["id"], "revision": current["revision"],
                        "title": current["title"], "slides": [*current["slides"], {"title": "Desserts", "bullets": ["Pie"]}]})
            return {"role": "assistant", "content": "Done."}

        with patch.object(agent, "model_completion", side_effect=completion):
            _, plain = self.request("/api/chat", {"message": "Give me dessert ideas"})
            _, created = self.request("/api/chat", {"message": "Make a slide deck about dinner"})
            _, updated = self.request("/api/chat", {"message": "add a slide about desserts"})
        self.assertNotIn("artifacts", plain[-1]["message"])
        self.assertFalse(observed[0][1])
        self.assertEqual(observed[1][1], {name for name, mode in FILE_TOOL_MODES.items() if mode == "create"})
        self.assertEqual(observed[-1][1], {name for name, mode in FILE_TOOL_MODES.items() if mode == "update"})
        original, edited = (events[-1]["message"]["artifacts"][0] for events in (created, updated))
        self.assertEqual(original["id"], edited["id"])
        self.assertEqual(original["box_id"], edited["box_id"])
        self.assertEqual(edited["version_number"], 2)
        self.assertEqual([slide["title"] for slide in self.detail(edited)["preview"]["slides"]],
                         ["Dinner deck", "Main dishes", "Desserts"])
        linked = self.request("/api/state")[1]["message_artifacts"]
        for events in (created, updated):
            self.assertEqual(linked[events[-1]["message"]["id"]][0]["id"], original["id"])


if __name__ == "__main__":
    unittest.main()
