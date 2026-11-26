import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlencode

from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import read_config
from hearth.page_public import ShareServer
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage, atomic_write, iso


class ChatSearchTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.storage = Storage(folder.name)
        config = read_config(ROOT / "config/connectors.json")
        config["brain"] = {"provider": "mock", "model": ""}
        self.app = Application(self.storage, LocalCheckpoints(self.storage), config)
        self.server = self.start(HTTPServer(("127.0.0.1", 0), self.app))
        self.threads = self.app.threads
        with self.storage.lock():
            self.side = self.threads.create(title="Travel notes")["id"]

    def start(self, server):
        self.addCleanup(server.server_close)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(server.shutdown)
        return server

    def get(self, route="/api/chat/search", *, headers=None, server=None, **query):
        connection = HTTPConnection("127.0.0.1", (server or self.server).server_port, timeout=5)
        try:
            connection.request("GET", f"{route}?{urlencode(query)}", headers=headers or {})
            reply = connection.getresponse()
            raw = reply.read()
            data = json.loads(raw) if reply.headers.get_content_type() == "application/json" else raw
            return reply.status, reply.headers, data
        finally:
            connection.close()

    def seed(self, thread, rows):
        with self.storage.lock():
            atomic_write(self.threads.path(thread), "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
            self.storage.bump_revision(threads=True)

    @staticmethod
    def row(identity, text, *, role="user", minute=0, **fields):
        at = datetime(2026, 11, 26, tzinfo=timezone.utc) + timedelta(minutes=minute)
        return {"id": identity, "role": role, "content": text, "at": iso(at), **fields}

    def test_matches_unicode_from_every_owned_thread_and_returns_safe_snippet_parts(self):
        self.seed("main", [self.row("main-1", "A CAFÉ and Straße near the plaza.")])
        self.seed(self.side, [self.row("side-1", "At Cafe\u0301 <img onerror=alert(1)> we had tea.",
                                      role="assistant", minute=1)])
        status, headers, data = self.get(q="cafe")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual([row["id"] for row in data["results"]], ["side-1", "main-1"])
        result = data["results"][0]
        self.assertEqual((result["thread_title"], result["role"]), ("Travel notes", "assistant"))
        self.assertEqual(result["snippet"], [
            {"text": "At "}, {"text": "Cafe\u0301", "match": True}, {"text": " <img onerror=alert(1)> we had tea."},
        ])
        self.assertEqual(self.get(q="STRASSE")[2]["results"][0]["snippet"][1], {"text": "Straße", "match": True})
        scoped = self.get(q="café", thread="main")[2]
        self.assertEqual(scoped["total"], 1)
        self.assertEqual([row["id"] for row in scoped["results"]], ["main-1"])
        self.assertEqual(self.get(q="cafe", thread="unowned")[0], 400)

    def test_excludes_private_roles_metadata_and_tool_markup(self):
        self.seed("main", [
            self.row("prompt", "Public preview <tool_response>private-source</tool_response> is ready.", private="private-meta"),
            self.row("reply", "<|im_start|>system\nprivate-system<|im_end|>"
                     "<think>private-analysis</think><tool_call>private-call</tool_call>"
                     '<|channel|>analysis<|message|>private-chain<|end|>'
                     '<|channel|>final<|message|>Public preview.\nsearch_web>{"query":"private-json"}', role="assistant"),
            self.row("system", "private-role Public preview", role="system"),
            self.row("tool", "private-role Public preview", role="tool"),
            self.row("call", "private-role Public preview", role="call"),
        ])
        self.assertEqual(self.get(q="private")[2]["results"], [])
        results = self.get(q="public")[2]["results"]
        self.assertEqual({row["id"] for row in results}, {"prompt", "reply"})
        self.assertNotIn("private", json.dumps(results))
        self.assertNotIn("<|", json.dumps(results))

    def test_validation_literal_wildcards_and_stable_cursor(self):
        rows = [self.row(str(i), "Check 10%_ off") for i in range(57)]
        self.seed("main", rows)
        for query in ({"q": ""}, {"q": "a"}, {"q": "a" * 201}, {"q": "ok", "limit": "0"},
                      {"q": "ok", "limit": "NaN"}, {"q": "ok", "before": "not-a-cursor"}):
            with self.subTest(query=query):
                self.assertEqual(self.get(**query)[0], 400)
        first = self.get(q="%_", thread="main", limit=99)[2]
        self.assertEqual((first["total"], len(first["results"])), (57, 50))
        second = self.get(q="%_", thread="main", before=first["before"])[2]
        self.assertEqual(second["before"], None)
        self.assertEqual([int(row["id"]) for row in first["results"] + second["results"]], list(range(56, -1, -1)))
        self.assertEqual(self.get(q="%x")[2]["results"], [])
        self.assertEqual(self.get(q="a" * 200)[0], 200)

    def test_reads_legacy_and_syncs_index_with_append_rename_and_delete(self):
        with self.storage.lock():
            state = self.storage.load()
            state["messages"] = [{key: val for key, val in self.row("old", "Legacy entry").items() if key != "id"}]
            self.storage.save(state)
        self.assertEqual(self.get(q="legacy")[2]["results"][0]["id"], "main:1")
        with self.storage.lock():
            self.threads.append("main", "assistant", "Another legacy entry")
            self.threads.append(self.side, "user", "A side note")
        self.assertEqual(len(self.get(q="legacy")[2]["results"]), 2)
        self.assertEqual(self.get("/api/state", around="main:1")[2]["messages"][0]["id"], "main:1")
        self.assertEqual(self.get(q="side")[2]["results"][0]["thread_title"], "Travel notes")
        with self.storage.lock():
            self.threads.rename(self.side, "Renamed")
        self.assertEqual(self.get(q="side")[2]["results"][0]["thread_title"], "Renamed")
        with self.storage.lock():
            self.threads.delete(self.side)
        self.assertEqual(self.get(q="side")[2]["results"], [])

    def test_newest_snapshot_and_centered_window_have_compatible_older_cursors(self):
        rows = [self.row(str(i), "A long record " + "é" * 300, minute=i) for i in range(155)]
        self.seed(self.side, rows)
        latest = self.get("/api/state", thread=self.side)[2]
        self.assertEqual([message["id"] for message in latest["messages"]], [str(i) for i in range(105, 155)])
        around = self.get("/api/state", thread=self.side, around=50)[2]
        self.assertEqual(around["around"], "50")
        self.assertEqual([message["id"] for message in around["messages"]], [str(i) for i in range(25, 75)])
        older = self.get("/api/transcript", thread=self.side, before=around["before"])[2]
        self.assertEqual([message["id"] for message in older["messages"]], [str(i) for i in range(25)])
        self.assertNotIn("around", self.get("/api/state", thread=self.side, around=154)[2])
        self.assertEqual(self.get("/api/state", thread=self.side, around="removed")[2], latest)

    def test_private_workspace_route_rejects_cross_origin_and_is_absent_from_public_publisher(self):
        self.assertEqual(self.get(q="sample", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.get(q="sample", headers={"Origin": "https://outside.example"})[0], 403)
        same = f"http://127.0.0.1:{self.server.server_port}"
        self.assertEqual(self.get(q="sample", headers={"Origin": same, "Sec-Fetch-Site": "same-origin"})[0], 200)
        publisher = self.start(ShareServer(("127.0.0.1", 0), Path(self.storage.root) / "public", "fixture-key"))
        self.assertEqual(self.get(q="sample", server=publisher)[0], 404)
