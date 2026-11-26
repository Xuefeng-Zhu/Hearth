import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from hearth import memory, memory_purge, memory_review, recall, router
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import ConnectorError, read_config
from hearth.server import Application
from hearth.storage import HearthError, ROOT, Storage, atomic_write, iso

NOW = datetime(2030, 4, 3, 10, tzinfo=timezone.utc)
FACT = "I prefer sketching with charcoal."
STALE = "The workshop deadline was 2024-03-12."
MONDAY = "Rowan's practice day: Monday."
FRIDAY = "Rowan's practice day: Friday."


def fixture(storage):
    for path in storage.files():
        if path not in memory.PINNED:
            storage.memory_path(path).unlink()
    storage.write(memory.PROFILE_NOTE, memory.canonical(memory.PROFILE_NOTE, "# My profile\n\nI like spring.\n"))
    for path, body in {
        "people/rowan.md": f"# Rowan\n\n{MONDAY}\n",
        "projects/club.md": f"# The club\n\n{FRIDAY}\n\n{STALE}\n",
        "topics/sketching.md": f"# Sketching\n\n- {FACT}\n",
        "daily/2030-03-20.md": f"# Daily\n\n- {FACT}\n",
        "daily/2030-03-21.md": f"# Daily\n\n- {FACT}\n",
    }.items():
        storage.write(path, memory.canonical(path, body))


class FakeGateway:
    def __init__(self):
        self.requests = []
        self.vectors = {}
        self.reply = '{"items":[]}'
        self.block = None

    def discover(self):
        return {}, set()

    def request(self, *args, **options):
        raise ConnectorError("The fixture connector is disconnected.", 404)

    def completion(self, model, messages, tools, emit, **options):
        self.requests.append((model["model"], json.loads(messages[-1]["content"]), tools, options))
        if self.block:
            self.block()
        return {"content": self.reply}

    def json(self, entry, path, body=None, **options):
        url = urlsplit(path)
        query = parse_qs(url.query)
        assert url.path == "indexes/fixture/vectors/fetch"
        assert query["namespace"] == ["fixture-namespace"]
        return {"vectors": {identity: {"metadata": self.vectors[identity]}
                            for identity in query["ids"] if identity in self.vectors}}


class MemoryReviewTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.storage = Storage(temp.name)
        fixture(self.storage)
        config = read_config(ROOT / "config/connectors.json")
        config["brain"] = {"provider": "mock", "model": ""}
        self.gateway = FakeGateway()
        self.app = Application(self.storage, LocalCheckpoints(self.storage), config, gateway=self.gateway)
        self.review = self.app.memory_review

    def notes(self):
        return {path: self.storage.read(path) for path in self.storage.files()}

    def mock_digest(self):
        result = self.review.tick(NOW, force=True)
        self.assertEqual((result["status"], result["mode"], result["count"]), ("complete", "mock", 4))
        digest, = self.review.get()["digests"]
        return digest, {item["kind"]: item for item in digest["items"]}

    def make_live(self):
        self.app.agent.models = [{"provider": "huggingface", "model": router.KIMI},
                                 {"provider": "huggingface", "model": router.FLASH}]

    def decide(self, digest, operation, item=None):
        return self.review.decide({"digest": digest["id"], "operation": operation,
                                   **({"item": item["id"]} if item else {})})

    def test_nightly_dst_and_settings(self):
        self.assertEqual(self.review.tick(NOW)["status"], "not-due")
        next_at = NOW + timedelta(days=1)
        self.assertEqual(self.review.get()["next_run"], iso(next_at))
        self.assertEqual(self.review.tick(next_at)["status"], "complete")
        self.assertEqual(self.review.tick(next_at)["status"], "not-due")
        self.assertEqual(self.review.get()["next_run"], iso(next_at + timedelta(days=1)))
        self.review.configure({"enabled": False, "time": "16:20"}, NOW)
        self.assertIsNone(self.review.get()["next_run"])
        self.assertEqual(self.review.tick(next_at + timedelta(days=3))["status"], "not-due")
        self.assertEqual(self.review.tick(NOW, force=True)["status"], "complete")
        with self.assertRaises(HearthError):
            self.review.configure({"enabled": True, "time": "25:01"})
        spring = datetime(2030, 3, 10, 9, tzinfo=timezone.utc)
        self.assertEqual(memory_review.next_run({"enabled": True, "time": "02:30"}, spring),
                         "2030-03-11T09:30:00+00:00")
        fall = datetime(2030, 11, 3, 7, tzinfo=timezone.utc)
        self.assertEqual(memory_review.next_run({"enabled": True, "time": "01:30"}, fall),
                         "2030-11-03T08:30:00+00:00")

    def test_review_is_read_only_until_approved_and_undo_reconciles(self):
        original = self.notes()
        digest, items = self.mock_digest()
        self.assertEqual(self.notes(), original)
        self.assertFalse(self.app.checkpoints.list())
        self.assertFalse(self.app.feed.list(clock=NOW)["cards"])
        cards = self.app.feed.list(clock=NOW + timedelta(hours=4))["cards"]
        self.assertEqual([(card["kind"], card["id"]) for card in cards], [("memory-review", digest["id"])])
        self.assertEqual([row["text"] for row in items["contradiction"]["sources"]], [MONDAY, FRIDAY])
        with patch.object(self.app.memory_index, "on_change") as sync:
            result = self.decide(digest, "accept-all")
            sync.assert_called_once_with()
        dispositions = {row["kind"]: row["status"] for row in result["digests"][0]["items"]}
        self.assertEqual(dispositions, {"promote": "accepted", "merge": "accepted", "stale": "accepted",
                                       "contradiction": "pending"})
        self.assertIn(FACT, self.storage.read(memory.PROFILE_NOTE))
        self.assertEqual(sum(FACT in text for path, text in self.notes().items() if path != memory.PROFILE_NOTE), 2)
        self.assertIn(STALE + " _(marked stale)_", self.storage.read("projects/club.md"))
        action, = self.storage.load()["actions"].values()
        self.assertTrue(action["memory_change"])
        self.assertEqual(action["checkpoint"]["id"], self.app.checkpoints.list()[0]["id"])
        self.assertEqual(self.decide(digest, "accept", items["contradiction"])["digests"][0]["items"][-1]["status"],
                         "acknowledged")
        self.assertIn(MONDAY, self.storage.read("people/rowan.md"))
        self.assertIn(FRIDAY, self.storage.read("projects/club.md"))
        with patch.object(self.app.memory_sync, "request") as sync:
            self.app.replay_memory(action["id"])
            sync.assert_called_once_with()
            self.assertEqual(self.notes(), original)
            self.app.replay_memory(action["id"], redo=True)
        self.assertFalse(self.app.feed.list(clock=NOW + timedelta(hours=6))["cards"])

    def test_reject_and_failed_accept_are_atomic(self):
        digest, items = self.mock_digest()
        changed = self.storage.read("projects/club.md").replace(STALE, "The workshop deadline changed.")
        self.storage.write("projects/club.md", changed)
        before = self.notes()
        with self.assertRaisesRegex(HearthError, "source changed"):
            self.decide(digest, "accept-all")
        self.assertEqual(self.notes(), before)
        self.assertFalse(self.app.checkpoints.list())
        self.decide(digest, "reject", items["stale"])
        with patch.object(self.storage, "save", side_effect=OSError):
            with self.assertRaises(OSError):
                self.decide(digest, "accept-all")
        self.assertEqual(self.notes(), before)
        self.assertEqual(self.review.get()["digests"][0]["items"][0]["status"], "rejected")
        self.decide(digest, "accept-all")
        self.assertIn(FACT, self.storage.read(memory.PROFILE_NOTE))

    def test_forgetting_keeps_unrelated_review_proposals_pending(self):
        digest, items = self.mock_digest()
        state = self.storage.load()
        rules = [memory.forget_rule([[STALE]])]
        memory_purge.scrub_state(state, rules)
        remaining, = state["memory_review"]["digests"]
        self.assertEqual(remaining, {**digest, "items": [item for item in digest["items"] if item != items["stale"]]})
        self.assertTrue(all(item["status"] == "pending" for item in remaining["items"]))
        self.assertNotIn(STALE, json.dumps(remaining, ensure_ascii=False))

    def test_validation_caps_proposals_and_logs_failure(self):
        self.make_live()
        self.gateway.reply = '{"items":[{"kind":"merge","sources":["1","missing"]}]}'
        original = self.notes()
        result = self.review.tick(NOW, force=True)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.notes(), original)
        self.assertFalse(self.review.get()["digests"])
        diagnostic = self.storage.load()["activity"][-1]
        self.assertTrue(diagnostic["diagnostic"])
        self.assertEqual(diagnostic["title"], "Memory review failed")
        model, _, tools, options = self.gateway.requests[-1]
        self.assertEqual(model, router.FLASH)
        self.assertFalse(tools)
        self.assertEqual(options["json_schema"], memory_review.SCHEMA)
        with self.assertRaises(memory_review.InvalidReview):
            memory_review.validate('{"items":[],"items":[]}', {})
        with self.assertRaises(memory_review.InvalidReview):
            memory_review.validate(json.dumps({"items": [{}] * 21}), {})
        with self.assertRaises(memory_review.InvalidReview):
            memory_review.validate('{"items":[{"kind":"promote","sources":["1","2"]}]}', {"1": {}, "2": {}})
        with patch.object(self.gateway, "completion", side_effect=ConnectorError("Unavailable", 503)):
            self.assertEqual(self.review.tick(NOW, force=True)["status"], "failed")
        self.assertEqual(self.notes(), original)

    def test_mirrored_pinecone_records_are_checked_and_cannot_inflate_occurrences(self):
        self.make_live()
        config = self.app.agent.config
        entry = config["pinecone"]
        entry.update(connection_id="fixture", index="fixture", namespace="fixture-namespace")
        corpus = self.app.memory_index.corpus(config, self.app.agent.memory)
        mirrored = [row for row in corpus if FACT in row["excerpt"]]
        for row in mirrored:
            self.gateway.vectors[row["id"]] = recall.metadata(row)
        bad = mirrored[0]["id"]
        self.gateway.vectors[bad]["text"] = "Old, replaced text."
        sync_path = self.storage.root / "pinecone-sync" / (
            recall.digest(json.dumps(self.app.memory_index.target(config)))[:24] + ".json")
        atomic_write(sync_path, json.dumps({"records": {
            row["id"]: recall.digest(json.dumps(recall.metadata(row), sort_keys=True)) for row in mirrored}}))
        result = self.review.tick(NOW, force=True)
        self.assertEqual(result["indexed"], 2)
        sources = self.gateway.requests[-1][1]["sources"]
        refs = [ref for ref, row in sources.items() if FACT in row["text"]]
        self.assertEqual(len(refs), 3)
        self.assertEqual(sum(sources[ref].get("indexed", False) for ref in refs), 2)
        other = next(ref for ref, row in sources.items() if STALE == row["text"])
        self.gateway.reply = json.dumps({"items": [
            {"kind": "promote", "sources": [*refs[:2], other]},
            {"kind": "merge", "sources": [refs[0], other]},
        ]})
        self.assertEqual(self.review.tick(NOW, force=True)["count"], 0)
        self.assertNotIn(FACT, self.storage.read(memory.PROFILE_NOTE))

    def test_permanent_forget_scrubs_matching_review_items_from_live_state_and_checkpoints(self):
        digest, items = self.mock_digest()
        self.decide(digest, "accept", items["promote"])
        self.app.purge_memory([["sketching with charcoal"]], None)
        remaining, = self.review.get()["digests"]
        self.assertEqual(remaining, {**digest, "items": [items["stale"], items["contradiction"]]})
        self.assertNotIn("sketching with charcoal", self.storage.state.read_text())
        for state in self.app.checkpoints.root.glob("*/live/state.json"):
            self.assertNotIn("sketching with charcoal", state.read_text())
        self.assertEqual(self.decide(digest, "accept", items["merge"])["digests"], [remaining])
        self.review.tick(NOW, force=True)
        self.assertNotIn("sketching with charcoal", json.dumps(self.review.get()))

    def test_concurrent_run_and_source_change(self):
        self.make_live()
        started, release = threading.Event(), threading.Event()

        def block():
            started.set()
            release.wait(5)

        self.gateway.block = block
        self.assertEqual(self.review.kick(force=True)["status"], "running")
        try:
            self.assertTrue(started.wait(5))
            self.assertEqual(self.review.kick(force=True)["status"], "busy")
            self.app.purge_memory([["Rowan", "practice day"]], None)
        finally:
            release.set()
        with self.review.worker:
            self.assertEqual(self.review.get()["last"]["status"], "interrupted")
        self.assertFalse(self.review.get()["digests"])


if __name__ == "__main__":
    unittest.main()
