import io
import json
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from hearth import pinecone, recall
from hearth.agent import CHAT_ORIGIN
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import GATEWAY, Gateway, read_config
from hearth.server import Application
from hearth.storage import ROOT, Storage

ALLERGY = "Maya develops hives after eating peanuts and tree nuts."
QUERY = "who can't eat nuts"
CHINESE_QUERY = "谁对坚果过敏"
HOST = "hearth-memory-demo.svc.example.pinecone.io"


class PineconeHTTP:
    """Exercise the real gateway client with a stateful Pinecone and Box fixture."""

    def __init__(self, *, integrated=True):
        self.allow_integrated = integrated
        self.allow_create = True
        self.allow_records = True
        self.allow_rerank = True
        self.allow_box = False
        self.index_list_error = None
        self.index = None
        self.records = {}
        self.requests = []
        self.query_delay = 0
        self.rerank_delay = 0
        self.upsert_failures = 0

    @staticmethod
    def response(value):
        return io.BytesIO(json.dumps(value).encode())

    @staticmethod
    def fail(request, status, error="upstream fixture"):
        raise HTTPError(request.full_url, status, error, {}, PineconeHTTP.response({"error": error}))

    def add_records(self, request, namespace, rows):
        if self.upsert_failures:
            self.upsert_failures -= 1
            self.fail(request, 503)
        self.records.setdefault(namespace, {}).update(rows)

    def open(self, request, *, timeout):
        url = urlsplit(request.full_url)
        parts = url.path.removeprefix("/v1/gateway/").split("/")
        method = request.get_method()
        mime = request.get_header("Content-type")
        if mime == "application/x-ndjson":
            body = [json.loads(line) for line in request.data.splitlines()]
        else:
            body = json.loads(request.data) if request.data else None
        if parts == ["list"]:
            providers = ["pinecone", "huggingface"] + (["box"] if self.allow_box else [])
            return self.response({"connections": [
                {"provider": name, "gateway_base_url": f"{GATEWAY}/{name}/test-{name}"} for name in providers
            ]})
        provider, _, *rest = parts
        path = "/".join(rest)
        self.requests.append((provider, method, path, body, request))
        if provider == "huggingface":
            if path == "v1/models":
                return self.response({"data": []})
            return self.response([[1, *([0] * 383)] for _ in body["inputs"]])
        if provider == "box":
            path = path.removeprefix("2.0/")
            if path == "folders/0/items":
                return self.response({"entries": [{"id": "9", "type": "folder", "name": "Hearth"}], "total_count": 1})
            if path == "folders/9/items":
                return self.response({"entries": [{"id": "32", "type": "file", "name": "Shopping list.csv",
                                       "size": 55, "etag": "1", "created_at": "2026-11-24T10:00:00Z",
                                       "file_version": {"id": "8"}}], "total_count": 1})
            if path == "files/32":
                return self.response({"id": "32", "type": "file", "name": "Shopping list.csv",
                                      "size": 55, "etag": "1", "file_version": {"id": "8"}})
            if path == "files/32/content":
                return io.BytesIO(b"Item,Qty\nCranberries,2\nPumpkin,1\n")
            self.fail(request, 404)
        if path in ("indexes", "indexes/create-for-model") and method == "POST":
            integrated = path.endswith("create-for-model")
            if (integrated and not self.allow_integrated) or not self.allow_create:
                self.fail(request, 403, "endpoint is not supported by the Pinecone connector")
            self.index = {"name": body["name"], "host": HOST, "metric": "cosine", "status": {"ready": True},
                          "dimension": 1024 if integrated else body["dimension"]}
            if integrated:
                self.index["embed"] = body["embed"]
            return self.response(self.index)
        if path == "indexes":
            if self.index_list_error:
                self.fail(request, self.index_list_error)
            return self.response({"indexes": [self.index] if self.index else []})
        if path == "indexes/hearth-memory":
            if not self.index:
                self.fail(request, 404)
            return self.response(self.index)
        if path == "rerank":
            time.sleep(self.rerank_delay)
            if not self.allow_rerank:
                self.fail(request, 403)
            return self.response({"data": [{"index": i, "score": 0.97 - i / 10}
                                           for i in reversed(range(len(body["documents"])))]})
        if path == "embed":
            return self.response({"data": [{"values": [1, *([0] * 1023)]} for _ in body["inputs"]]})
        if path.endswith("/describe_index_stats"):
            return self.response({"namespaces": {ns: {"vectorCount": len(rows)} for ns, rows in self.records.items()}})
        if path.endswith("/vectors/list"):
            namespace = parse_qs(url.query)["namespace"][0]
            return self.response({"vectors": [{"id": key} for key in self.records.get(namespace, {})]})
        if path.endswith("/vectors/delete"):
            rows = self.records[body["namespace"]]
            for key in body["ids"]:
                rows.pop(key, None)
            return self.response({})
        if path.endswith("/vectors/upsert"):
            self.add_records(request, body["namespace"], ((row["id"], row["metadata"]) for row in body["vectors"]))
            return self.response({"upsertedCount": len(body["vectors"])})
        if "/records/namespaces/" in path:
            if not self.allow_records:
                self.fail(request, 403, "endpoint is not supported by the Pinecone connector")
            namespace = rest[-2]
            if path.endswith("/upsert"):
                self.add_records(request, namespace, ((row["_id"], row) for row in body))
                return io.BytesIO()
            hits = self.search(namespace, body["query"]["inputs"]["text"], body["query"])
            return self.response({"result": {"hits": [{"_id": key, "_score": score} for key, score in hits]}})
        if path.endswith("/query"):
            hits = self.search(body["namespace"], QUERY, {"top_k": body["topK"], "filter": body.get("filter", {})})
            return self.response({"matches": [{"id": key, "score": score} for key, score in hits]})
        raise AssertionError(f"Unexpected fixture path {path}")

    def search(self, namespace, query, parameters):
        time.sleep(self.query_delay)
        rows = self.records.get(namespace, {})
        filters = parameters.get("filter", {})
        hits = []
        for key, row in rows.items():
            if any(("$eq" in rule and row[field] != rule["$eq"])
                   or ("$in" in rule and row[field] not in rule["$in"]) for field, rule in filters.items()):
                continue
            text = row["text"].casefold()
            if query in (QUERY, CHINESE_QUERY):
                score = 0.914 if "hives" in text else 0.62 if "allergies" in text else 0.1
            elif "shopping list" in query and row["kind"] == "artifact":
                score = 0.923
            else:
                score = 0.861 if query.casefold() in text else 0.1
            hits.append((key, score))
        return sorted(hits, key=lambda hit: -hit[1])[:parameters["top_k"]]


class PineconeMemoryTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.storage = Storage(scratch.name)
        self.path = "people/maya-allergy.md"
        self.storage.write(self.path, f"# Allergy note\n\n{ALLERGY}\n")
        self.config = read_config(ROOT / "config/connectors.json")
        self.config["brain"] = {"provider": "mock", "model": ""}
        self.checkpoints = LocalCheckpoints(self.storage)
        self.http = PineconeHTTP()
        self.gateway = Gateway()
        self.gateway.opener = self.http

    def start(self):
        self.app = Application(self.storage, self.checkpoints, self.config, gateway=self.gateway)
        self.addCleanup(self.app.memory_index.query_pool.shutdown)
        self.app.scan_connections(sync_memory=True)
        self.wait()
        return self.app

    def wait(self):
        deadline = time.monotonic() + 4
        while self.app.memory_sync.running and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(self.app.memory_sync.running)
        return self.app.memory_sync.job

    def requests(self, suffix):
        return [row for row in self.http.requests if row[2].endswith(suffix)]

    def test_integrated_bootstrap_and_real_query_filters(self):
        self.start()
        status = self.app.memory_info()["pinecone"]
        self.assertEqual((status["host"], status["namespace"], status["dimension"]), (HOST, "frank", 1024))
        sync = self.app.memory_sync.job
        self.assertEqual(status["record_count"], sync["upserted"])
        saved = json.loads(self.app.connections.path.read_text())["pinecone"]
        self.assertEqual((saved["host"], saved["namespace"]), (HOST, "frank"))
        create, = self.requests("create-for-model")
        self.assertEqual(create[3]["embed"]["field_map"], {"text": "text"})
        self.assertEqual((create[3]["cloud"], create[3]["region"]), ("aws", "us-east-1"))
        payload, = self.requests("/frank/upsert")
        self.assertEqual(payload[4].get_header("Content-type"), "application/x-ndjson")
        for _, _, _, _, request in self.http.requests:
            self.assertIsNone(request.get_header("Authorization"))
            self.assertIsNone(request.get_header("Api-key"))
            if "/pinecone/" in request.full_url:
                self.assertEqual(request.get_header("X-pinecone-api-version"), "2025-10")
        result = self.app.agent.memory_search(CHINESE_QUERY, kind="person", thread_id="main")
        hit, = result["results"]
        self.assertEqual((result["backend"], hit["path"], hit["score"]), ("pinecone", self.path, 0.914))
        search, = self.requests("/frank/search")
        self.assertEqual(search[3]["query"]["top_k"], 8)
        self.assertEqual(search[3]["query"]["filter"]["kind"], {"$eq": "person"})
        self.assertEqual(search[3]["query"]["filter"]["thread_id"], {"$eq": "main"})
        self.app.memory_sync.request("sync")
        self.assertEqual(self.wait()["upserted"], 0)
        self.assertEqual(len(self.requests("/frank/upsert")), 1)

    def test_dense_fallback_uses_multilingual_hugging_face_vectors(self):
        self.http.allow_integrated = False
        self.start()
        status = self.app.memory_info()["pinecone"]
        self.assertFalse(status["integrated"])
        self.assertEqual((status["embedding_model"], status["dimension"]), (pinecone.DENSE_MODEL, 384))
        self.assertEqual(self.requests("/vectors/upsert")[0][3]["namespace"], "frank")
        result = self.app.agent.memory_search(QUERY, kind="person")
        self.assertEqual(result["results"][0]["score"], 0.914)
        embedding = [row[3]["inputs"] for row in self.http.requests if row[0] == "huggingface"]
        self.assertTrue(embedding[0][0].startswith("passage: "))
        self.assertEqual(embedding[-1], [f"query: {QUERY}"])
        self.assertEqual(self.requests("/query")[0][3]["filter"]["kind"], {"$eq": "person"})

    def test_denied_records_routes_reuse_existing_index_with_hosted_embeddings(self):
        self.http.allow_records = False
        self.start()
        self.assertTrue(self.app.memory_info()["pinecone"]["vector_transport"])
        self.assertEqual(len(self.requests("/vectors/upsert")[0][3]["vectors"][0]["values"]), 1024)
        self.assertEqual(self.app.agent.memory_search(QUERY)["backend"], "pinecone")

    def test_live_style_creation_rejection_reports_local_fallback(self):
        self.http.allow_create = False
        self.start()
        self.assertEqual(self.app.memory_sync.job["status"], "failed")
        self.assertIn("HTTP 403", self.app.memory_sync.job["error"])
        hit = self.app.agent.memory_search("peanuts")["results"][0]
        self.assertEqual(hit["backend"], "local")
        self.assertEqual(hit["path"], self.path)
        self.assertIsNone(self.app.memory_info()["pinecone"]["record_count"])

    def test_home_and_connections_follow_pinecone_recovery_on_same_target(self):
        self.http.allow_create = False
        self.http.index_list_error = 403
        app = self.start()
        app.connections.test("pinecone")
        app.connection_state = app.connections.report()
        self.assertEqual(app.connection_info()["providers"]["pinecone"]["test_status"], "denied")
        failed = app.home.snapshot()["builtin"]
        self.assertEqual(failed["memory"]["pinecone"], "Unavailable")
        self.assertEqual(next(row for row in failed["connections"]["items"] if row["id"] == "pinecone")["status"],
                         "error")
        self.assertEqual(failed["activity"]["errors"], 1)

        self.http.allow_create = True
        create_attempts = len(self.requests("create-for-model"))
        app.scan_connections(sync_memory=True)
        self.assertEqual(len(self.requests("create-for-model")), create_attempts)
        self.assertFalse(app.memory_sync.running)
        app.memory_sync.request("sync")
        self.assertEqual(self.wait()["status"], "complete")
        current = app.home.snapshot()["builtin"]
        memory = current["memory"]
        self.assertEqual(memory["pinecone"], "Ready")
        self.assertEqual(memory["record_count"], len(self.http.records["frank"]))
        self.assertTrue(memory["last_sync"])
        connection = next(row for row in current["connections"]["items"] if row["id"] == "pinecone")
        self.assertEqual(connection["status"], "ok")
        self.assertEqual(current["activity"]["errors"], 0)
        entry = app.connection_info()["providers"]["pinecone"]
        self.assertEqual((entry["index_state"], entry["index_error"], entry["test_status"], entry["test_detail"]),
                         ("Ready", None, None, None))
        self.assertNotIn("pinecone", app.connections.check_times)
        self.assertNotIn("error", app.memory_info()["pinecone"])

        app.connections.test("pinecone")
        app.connection_state = app.connections.report()
        self.assertEqual(app.connection_info()["providers"]["pinecone"]["test_status"], "denied")

    def test_edits_deletes_undo_redo_and_box_text(self):
        self.http.allow_box = True
        self.http.upsert_failures = 1
        self.start()
        self.assertEqual(len(self.requests("/frank/upsert")), 2)
        remote = self.http.records["frank"]
        shopping, = [hit for hit in self.app.agent.memory_search("what was on my shopping list", kind="artifact")["results"]]
        self.assertEqual((shopping["artifact_id"], shopping["source"]), ("box-32", "Box"))
        original, = [row["_id"] for row in remote.values() if "hives" in row["text"]]
        key = "pcsk_" + "A" * 32
        action = self.app.agent.memory_write([{"path": self.path, "content": f"Seafood allergy. API key: {key}"}])["action"]
        self.assertEqual(self.wait()["deleted"], 1)
        replacement, = [row for row in remote.values() if "Seafood allergy" in row["text"]]
        self.assertNotIn(original, remote)
        self.assertEqual(replacement["kind"], "person")
        self.assertEqual(replacement["thread_id"], "main")
        self.assertEqual(replacement["source"], "Markdown")
        self.assertTrue(replacement["created_at"])
        self.assertIn("[redacted]", replacement["text"])
        self.assertNotIn(key, str(self.http.requests))
        self.app.replay_memory(action["id"])
        self.wait()
        self.assertIn(original, remote)
        self.assertNotIn(replacement["_id"], remote)
        self.app.replay_memory(action["id"], redo=True)
        self.wait()
        self.assertNotIn(original, remote)
        self.assertIn(replacement["_id"], remote)
        action = self.app.forget_memory({"path": self.path})
        self.wait()
        self.assertNotIn(replacement["_id"], remote)
        self.app.replay_memory(action["id"])
        self.wait()
        self.assertIn(replacement["_id"], remote)

    def test_saved_note_excerpts_keep_their_originating_thread(self):
        self.start()
        path = "topics/thread-origins.md"
        first = "I prefer the blue notebook."
        self.app.agent.memory_write([{"path": path, "content": first}])
        self.wait()
        with self.storage.lock():
            thread = self.app.threads.create()
        origin = CHAT_ORIGIN.set({"thread_id": thread["id"], "thread_title": thread["title"]})
        try:
            self.app.agent.memory_write([{"path": path, "content": first + "\n\nSecond note."}])
        finally:
            CHAT_ORIGIN.reset(origin)
        self.wait()
        rows = {row["text"]: row for row in self.http.records["frank"].values()}
        self.assertEqual((rows[first]["thread_id"], rows[first]["kind"]), ("main", "preference"))
        self.assertEqual(rows["Second note."]["thread_id"], thread["id"])

    def test_rerank_optional_and_deadlines_use_local_or_unreranked_hits(self):
        self.start()
        result = self.app.agent.memory_search(QUERY)
        self.assertTrue(result["reranked"])
        self.assertEqual((result["results"][0]["score"], result["results"][0]["similarity"]), (0.97, 0.914))
        self.http.allow_rerank = False
        result = self.app.agent.memory_search(QUERY)
        self.assertFalse(result["reranked"])
        self.assertEqual(result["results"][0]["score"], 0.914)
        self.app.agent.memory_search(QUERY)
        self.assertEqual(len(self.requests("rerank")), 2)
        self.app.memory_index.remote[1].rerank_unavailable = False
        self.http.rerank_delay = .5
        result = self.app.agent.memory_search(QUERY, budget=.16)
        self.assertEqual(result["backend"], "pinecone")
        self.assertFalse(result["reranked"])
        self.http.query_delay = .5
        result = self.app.agent.memory_search("peanuts", budget=.15)
        self.assertEqual(result["backend"], "local")
        self.assertLess(result["latency_ms"], 250)
        self.assertEqual(result["results"][0]["path"], self.path)

    def test_chat_cites_pinecone_and_signals_ember(self):
        self.start()
        events = []
        self.app.agent.chat(QUERY, lambda name, data: events.append((name, data)))
        self.assertIn("remembered", [name for name, _ in events])
        done = events[-1][1]["message"]
        self.assertEqual(done["remembered"][0]["backend"], "pinecone")
        self.assertIsInstance(done["remembered"][0]["score"], float)
        entries = self.storage.load()["activity"]
        self.assertEqual(entries[-1]["provider"], "pinecone")
        self.assertIn("Pinecone", entries[-1]["title"])
