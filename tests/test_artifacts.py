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

from hearth import box
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import Gateway, read_config
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage, iso


class MockBox:
    """Simulate the gateway at the HTTP boundary, including multipart uploads."""

    def __init__(self):
        self.requests = []
        self.next_id = 100
        self.folders = {"0": {"id": "0", "name": "All Files", "type": "folder", "parent": None}}
        self.files = {}
        self.reject_upload = None

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
        assert url.path.startswith("/v1/gateway/box/qa_Box/2.0/")
        parts = url.path.split("/")[6:]
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
        if method == "POST" and len(parts) == 2:
            assert item["trashed"]
            item["trashed"] = False
            return self.response(self.metadata(item))
        if item["trashed"]:
            self.fail(request, 404)
        if method == "DELETE" and len(parts) == 2:
            assert request.get_header("If-match") == self.metadata(item)["etag"]
            item["trashed"] = True
            return BytesIO()
        if len(parts) == 2:
            return self.response(self.metadata(item))
        if parts[2] == "versions":
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

    def create(self, **fields):
        status, item = self.endpoint("/create", {"title": "Dinner plan", "kind": "plan", "content": "# Dinner", **fields})
        self.assertEqual(status, 201, item)
        return item

    def detail(self, item):
        status, detail = self.endpoint("/detail?id=" + item["id"])
        self.assertEqual(status, 200, detail)
        return detail

    def undo(self, operation):
        rows = self.request("/api/timeline")[1]["entries"]
        action = next(item for item in reversed(rows) if item["title"].startswith("Artifact " + operation))
        return self.endpoint("/undo", {"id": action["action_id"]})

    def test_bootstrap_upload_new_version_list_and_undo(self):
        self.assertEqual(len(self.provider.folders), 1)
        item = self.create(title="../Dinner\r\nplan", content="# Dinner\n\npassword: demo-secret")
        self.assertEqual(item["sync"], "synced")
        self.assertEqual(item["box_url"], "https://app.box.com/file/" + item["box_id"])
        self.assertNotIn("/", item["filename"])
        self.assertNotIn("\n", item["filename"])
        folders = json.loads(self.app.connections.path.read_text())["box_folders"]
        self.assertEqual(set(folders["kinds"]), set(box.FOLDERS))
        self.assertEqual(self.app.connections.load()["box_folders"], folders)
        self.assertEqual(len(self.provider.folders), 7)
        detail = self.detail(item)
        self.assertIn("[redacted]", detail["content"])
        self.assertNotIn("demo-secret", detail["content"])
        status, edited = self.endpoint("/update", {"id": item["id"], "revision": detail["revision"], "content": "# Edited"})
        self.assertEqual(status, 200, edited)
        self.assertEqual(edited["box_id"], item["box_id"])
        self.assertEqual(edited["version_number"], "2")
        self.assertEqual([row["number"] for row in self.detail(item)["versions"]], ["2", "1"])
        listed = self.endpoint()[1]["artifacts"]
        self.assertEqual([row["id"] for row in listed], [item["id"]])
        self.assertEqual(self.endpoint("/update", {"id": item["id"], "revision": detail["revision"], "content": "stale"})[0], 400)
        self.assertEqual(self.undo("updated")[0], 200)
        self.assertIn("# Dinner", self.detail(item)["content"])
        self.assertEqual(self.detail(item)["versions"][0]["number"], "3")
        self.assertEqual(len(self.provider.folders), 7)

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
        self.assertEqual(self.endpoint("/delete", {"id": detail["id"], "revision": detail["revision"]})[0], 200)
        self.assertTrue(external["trashed"])
        self.assertEqual(len(self.endpoint()[1]["artifacts"]), 2)
        self.assertEqual(self.undo("deleted")[0], 200)
        self.assertFalse(external["trashed"])
        self.assertEqual(len(self.endpoint()[1]["artifacts"]), 3)

    def test_upload_fallback_error_mapping_and_retry(self):
        self.provider.reject_upload = 403, {"error": "endpoint is not supported by the Box connector"}
        item = self.create()
        self.assertEqual(item["sync"], "local")
        self.assertEqual(item["sync_message"], box.UNAVAILABLE)
        self.assertEqual(self.detail(item)["content"], "# Dinner")
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

    def test_box_version_fallback_preserves_pending_local_content(self):
        item = self.create()
        detail = self.detail(item)
        self.provider.reject_upload = 403, {"error": "endpoint is not supported by the Box connector"}
        code, update = self.endpoint("/update", {"id": item["id"], "revision": detail["revision"], "content": "Local edit"})
        self.assertEqual(code, 200, update)
        self.assertEqual(update["sync"], "local")
        self.assertEqual(self.detail(item)["content"], "Local edit")
        self.assertEqual(self.detail(item)["versions"][0]["number"], "1")
        self.provider.reject_upload = None
        self.assertEqual(self.endpoint("/retry", {"id": item["id"]})[1]["version_number"], "2")
        self.assertEqual(self.detail(item)["content"], "Local edit")

    def test_local_settings_bounds_json_redaction_and_csrf(self):
        self.assertEqual(self.endpoint("/settings", {"auto_save": False, "format": "json", "folder_name": "Kitchen"})[0], 200)
        self.assertEqual(self.endpoint("/settings")[1]["settings"]["folder_name"], "Kitchen")
        self.assertEqual(self.endpoint("/create", {"title": "No", "content": "{}"}, Origin="https://elsewhere.invalid")[0], 403)
        self.assertEqual(self.endpoint("/create", {"title": "No", "content": "{}"}, **{"Sec-Fetch-Site": "same-site"})[0], 403)
        self.assertEqual(self.endpoint("/settings", {"folder_name": "../nested"})[0], 400)
        self.assertEqual(self.endpoint("/create", {"title": "Big", "content": "é" * box.MAX_BYTES, "format": "md"})[0], 400)
        self.assertEqual(self.endpoint("/create", {"title": "Bad JSON", "content": "not-json"})[0], 400)
        item = self.create(content='{"access_token":"private","menu":["Pie"]}')
        detail = self.detail(item)
        self.assertEqual(detail["sync"], "local")
        self.assertEqual(json.loads(detail["content"]), {"access_token": "[redacted]", "menu": ["Pie"]})
        self.assertEqual(len(self.provider.files), 0)
        self.assertEqual(self.endpoint("/delete", {"id": item["id"], "revision": detail["revision"]})[0], 200)
        self.assertEqual(self.undo("deleted")[0], 200)
        self.assertEqual(self.undo("created")[0], 200)
        self.assertEqual(self.endpoint()[1]["artifacts"], [])

    def test_chat_tool_and_save_message_link_to_reply(self):
        _, events = self.request("/api/chat", {"message": "Make Thanksgiving demo artifacts"})
        done = events[-1]["message"]
        self.assertEqual(len(done["artifacts"]), 3)
        self.assertEqual({item["format"] for item in done["artifacts"]}, {"md", "csv"})
        self.assertTrue(any(event.get("title") == "Saving to Box" for event in events))
        body = {"thread_id": "main", "message_id": done["id"]}
        status, first = self.endpoint("/save-message", body)
        self.assertEqual(status, 201)
        self.assertEqual(self.endpoint("/save-message", body)[1]["id"], first["id"])
        self.assertEqual(len(self.request("/api/state")[1]["message_artifacts"][done["id"]]), 4)
        self.assertEqual(self.detail(first)["thread_id"], "main")


if __name__ == "__main__":
    unittest.main()
