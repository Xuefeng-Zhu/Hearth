import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from unittest.mock import Mock, patch

from hearth import artifacts, box, office
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import ConnectorError, Gateway
from hearth.storage import HearthError, Storage


class ArtifactIOTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.operation = threading.RLock()
        connections = Mock(config={"artifacts": dict(box.DEFAULTS)}, selected={"box": "fixture"})
        self.service = artifacts.Artifacts(Storage(scratch.name), connections, self.operation)
        self.client = Mock()
        self.service.client = Mock(return_value=self.client)
        self.client.folders.side_effect = lambda parent, names: dict.fromkeys(names, "10")
        self.client.upload.return_value = {"id": "11", "etag": "1"}
        self.client.file.return_value = {"id": "11", "etag": "1"}

    @staticmethod
    def document(text):
        return {"title": "Dinner", "sections": [{"paragraphs": [text]}]}

    def test_listing_serves_cached_rows_while_one_background_walk_runs(self):
        started, release = threading.Event(), threading.Event()
        self.service.walk = Mock()

        def walk(client, *args):
            if self.service.walk.call_count == 1:
                started.set()
                self.assertTrue(release.wait(5))
                return {"box-11": self.service.box_row({"id": "11", "name": "Dinner.txt"}, "note", "fixture")}
            raise ConnectorError("fixture detail", 429)

        self.service.walk.side_effect = walk
        with ThreadPoolExecutor() as pool:
            first = pool.submit(self.service.list)
            try:
                self.assertTrue(started.wait(5))
                self.assertEqual(first.result(timeout=1)["box_status"], "refreshing")
                self.assertEqual(self.service.list()["artifacts"], [])
                self.assertTrue(self.service.lock.acquire(timeout=1))
                self.service.lock.release()
                self.assertEqual(self.service.walk.call_count, 1)
                refresh = self.service.refresh
            finally:
                release.set()
            refresh.result(timeout=5)
        fresh = self.service.list()
        self.assertEqual(fresh["box_status"], "fresh")
        self.assertEqual(fresh["artifacts"][0]["id"], "box-11")
        self.assertIsNotNone(fresh["box_refreshed_at"])
        self.assertEqual(self.service.walk.call_count, 1)

        refreshing = self.service.list(force=True)
        self.assertEqual(refreshing["box_status"], "refreshing")
        self.assertEqual(refreshing["artifacts"], fresh["artifacts"])
        self.service.refresh.result(timeout=5)
        stale = self.service.list()
        self.assertEqual(stale["box_status"], "stale")
        self.assertEqual(stale["box_refreshed_at"], fresh["box_refreshed_at"])
        self.assertEqual(stale["artifacts"][0]["id"], "box-11")
        self.assertIn("limiting requests", stale["box_error"])

    def test_folder_change_discards_an_in_flight_listing(self):
        started, release = threading.Event(), threading.Event()

        def walk(client, scope):
            if scope[1] == box.DEFAULTS["folder_name"]:
                started.set()
                self.assertTrue(release.wait(5))
                return {"box-11": self.service.box_row({"id": "11", "name": "Old.txt"}, "note", "fixture")}
            return {"box-12": self.service.box_row({"id": "12", "name": "New.txt"}, "note", "fixture")}

        self.service.walk = Mock(side_effect=walk)
        with ThreadPoolExecutor() as pool:
            first = pool.submit(self.service.list)
            try:
                self.assertTrue(started.wait(5))
                first.result(timeout=1)
                old_refresh = self.service.refresh
                self.service.connections.config["artifacts"]["folder_name"] = "New"
                self.assertEqual(self.service.list()["artifacts"], [])
                self.service.refresh.result(timeout=5)
            finally:
                release.set()
            old_refresh.result(timeout=5)
        self.assertEqual([row["id"] for row in self.service.list()["artifacts"]], ["box-12"])

    def test_create_releases_shared_locks_during_upload(self):
        started, release = threading.Event(), threading.Event()

        def upload(row, content, folder):
            started.set()
            self.assertTrue(release.wait(5))
            self.assertTrue(content.read(2))
            return {"id": "11", "etag": "1"}

        self.client.upload.side_effect = upload
        with ThreadPoolExecutor() as pool:
            save = pool.submit(self.service.create, "docx", self.document("Original"))
            try:
                self.assertTrue(started.wait(5))
                self.assertTrue(self.operation.acquire(timeout=1))
                self.operation.release()
                self.assertTrue(self.service.lock.acquire(timeout=1))
                self.service.lock.release()
                row = self.service.list()["artifacts"][0]
                self.service.bind([row["id"]], "main", "reply")
            finally:
                release.set()
            saved = save.result(timeout=5)
        self.assertEqual(saved["sync"], "synced")
        self.assertTrue(self.service.has_reply_file("main", "reply"))

    def test_concurrent_edit_revalidates_revision_after_generation(self):
        item = self.service.create("docx", self.document("Original"))
        started, release = threading.Event(), threading.Event()
        generate = office.generate

        def generate_slowly(fmt, value):
            if "Slow edit" in str(value):
                started.set()
                self.assertTrue(release.wait(5))
            return generate(fmt, value)

        with patch.object(office, "generate", side_effect=generate_slowly), ThreadPoolExecutor() as pool:
            slow = pool.submit(self.service.update, "docx", item["id"], item["revision"], self.document("Slow edit"))
            try:
                self.assertTrue(started.wait(5))
                fast = pool.submit(self.service.update, "docx", item["id"], item["revision"], self.document("Fast edit"))
                winner = fast.result(timeout=2)
            finally:
                release.set()
            with self.assertRaisesRegex(HearthError, "changed"):
                slow.result(timeout=5)
        self.assertEqual(self.service.find(item["id"])["revision"], winner["revision"])
        self.assertEqual(self.client.upload.call_count, 2)

    def test_retry_cannot_commit_across_restore_of_same_revision(self):
        self.service.connections.config["artifacts"]["auto_save"] = False
        item = self.service.create("docx", self.document("Original"))
        checkpoints = LocalCheckpoints(self.service.storage)
        checkpoint = checkpoints.create("Before retry")
        started, release = threading.Event(), threading.Event()

        def upload(row, content, folder):
            started.set()
            self.assertTrue(release.wait(5))
            return {"id": "11", "etag": "1"}

        self.client.upload.side_effect = upload
        with ThreadPoolExecutor() as pool:
            retry = pool.submit(self.service.mutate, "retry", {"id": item["id"]})
            try:
                self.assertTrue(started.wait(5))
                with self.assertRaisesRegex(HearthError, "changed"):
                    self.service.mutate("delete", {"id": item["id"], "revision": item["revision"]})
                self.assertTrue(self.operation.acquire(timeout=1))
                try:
                    self.service.reset()
                    with self.service.storage.lock():
                        checkpoints.restore(checkpoint["id"])
                finally:
                    self.operation.release()
            finally:
                release.set()
            with self.assertRaisesRegex(HearthError, "workspace changed"):
                retry.result(timeout=5)
        restored = self.service.find(item["id"])
        self.assertEqual((restored["revision"], restored["sync"]), (item["revision"], "local"))
        self.assertNotIn("box_id", restored)


class BoxTransferTest(unittest.TestCase):
    def test_multipart_streams_seekable_file_and_preserves_headers(self):
        gateway = Gateway()
        gateway.opener = Mock()
        payload_size = 50 * 1024 * 1024

        def check_request(request, timeout):
            self.assertEqual(request.get_header("If-match"), "7")
            self.assertIn("multipart/form-data; boundary=", request.get_header("Content-type"))
            chunks = iter(request.data)
            prefix = next(chunks)
            self.assertIn(b'name="attributes"', prefix)
            self.assertIn(b'filename="example.txt"', prefix)
            transferred = len(prefix)
            for chunk in chunks:
                self.assertIsInstance(chunk, bytes)
                self.assertLessEqual(len(chunk), 128 * 1024)
                transferred += len(chunk)
            self.assertEqual(transferred, int(request.get_header("Content-length")))
            self.assertLess(transferred - payload_size, 1024)
            self.assertGreater(transferred, payload_size)
            return BytesIO(b'{"entries":[{"id":"11"}]}')

        gateway.opener.open.side_effect = check_request
        client = box.Box(gateway, {"provider": "box", "connection_id": "fixture"})
        with tempfile.TemporaryFile() as source:
            source.truncate(payload_size)
            self.assertEqual(client.upload({"box_id": "11", "etag": "7", "filename": "example.txt",
                                            "format": "txt"}, source)["id"], "11")

    def test_large_download_spools_in_bounded_chunks_and_enforces_limit(self):
        class Response(BytesIO):
            def read(self, size=-1):
                if not 0 < size <= 128 * 1024:
                    raise AssertionError("Expected a bounded read")
                return super().read(size)

        gateway = Mock()
        raw = b"sample" * (256 * 1024)
        response = Response(raw)
        gateway.open.return_value = response
        client = box.Box(gateway, {})
        with client.download_file("11", limit=len(raw)) as download:
            self.assertEqual(download.read(), raw)
            self.assertTrue(download.seekable())
        self.assertTrue(response.closed)
        self.assertTrue(download.closed)

        gateway.open.return_value = Response(raw)
        with self.assertRaisesRegex(HearthError, "too large"):
            client.download_file("11", limit=len(raw) - 1)


if __name__ == "__main__":
    unittest.main()
