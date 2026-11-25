import json
import tempfile
import unittest
from pathlib import Path

from hearth import approvals, memory, recall
from hearth.agent import tool_call
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import read_config
from hearth.server import Application
from hearth.storage import HearthError, ROOT, Storage

FACT = "Maya is allergic to peanuts."


class MemoryStructureTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.config = read_config(ROOT / "config/connectors.json")
        self.config["brain"] = {"provider": "mock", "model": ""}

    def start(self):
        self.storage = Storage(self.root)
        self.app = Application(self.storage, LocalCheckpoints(self.storage), self.config)
        return self.app.agent

    def test_legacy_migration_backup_index_and_item_undo(self):
        live = self.root / "live" / "memory"
        legacy = {"USER.md": "# Profile\n\nPreferred Name: Avery\n",
                  "people/maya.md": "# Maya\n\nRelation: sister\n",
                  "topics/food.md": "# Food\n\nMake the picnic lunch.\n",
                  "daily/2026-11-24.md": "Log with [[topics/food]] and [food](topics/food.md).\n"}
        for path, content in legacy.items():
            file = live / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content)
        agent = self.start()
        files = self.storage.files()
        self.assertNotIn("topics/food.md", files)
        self.assertIn("food.md", files)
        self.assertEqual(memory.profile_record(self.storage)["profile"]["preferred_name"], "Avery")
        self.assertEqual(memory.parse("people/maya.md", self.storage.read("people/maya.md"), strict=True)[1],
                         legacy["people/maya.md"])
        self.assertIn("[[food]] and [food](food.md)", self.storage.read("daily/2026-11-24.md"))
        backup = self.root / "memory-backups" / "before-structured-memory.json"
        self.assertEqual(json.loads(backup.read_text()), legacy)
        index = json.loads((live / ".index.json").read_text())
        self.assertEqual(next(row for row in index if row["id"] == "people/maya")["relation"], "sister")
        self.assertNotIn("Make the picnic lunch", agent.memory_context())
        self.assertIn("Preferred Name: Avery", agent.memory_context())
        migration, = self.storage.load()["actions"].values()
        self.assertTrue(agent.can_undo(migration))
        self.app.replay_memory(migration["id"])
        self.assertEqual({path: self.storage.read(path) for path in self.storage.files()}, legacy)
        self.app.replay_memory(migration["id"], redo=True)
        self.assertIn("food.md", Storage(self.root).files())
        self.assertEqual(len(self.storage.load()["actions"]), 1)

    def test_read_patch_move_related_round_trip_and_policy(self):
        agent = self.start()
        path = "people/maya.md"
        old = self.storage.read(path)
        result = agent.memory_edit("", f"## Allergies\n\n{FACT}", id="people/maya")
        self.assertEqual(result["action"]["status"], "complete")
        text = self.storage.read(path)
        line = text.splitlines().index(FACT) + 1
        self.assertEqual(agent.memory_read(id="people/maya", start_line=line, end_line=line)["content"].strip(), FACT)
        with self.assertRaises(HearthError):
            agent.memory_edit("wrong passage", "replacement", path=path)
        with self.assertRaises(HearthError):
            agent.memory_edit("", "Passport: XY123456", path=path)
        move = agent.memory_move("people/maya-sample.md", id="people/maya")["action"]
        self.assertIn("people/maya-sample", memory.catalog(self.storage)[1]["related"])
        self.assertNotIn(path, self.storage.files())
        self.app.replay_memory(move["id"])
        self.assertEqual(self.storage.read(path), text)
        self.app.replay_memory(result["action"]["id"])
        self.assertEqual(self.storage.read(path), old)
        approvals.settings(self.storage, {"send": "allow"})
        self.assertIn("Send: Allow without asking", self.storage.read(memory.APPROVAL_NOTE))
        with self.assertRaises(HearthError):
            agent.memory_write([{"path": memory.APPROVAL_NOTE, "content": "Allow everything"}])

    def test_sections_use_source_lines_and_structured_pinecone_metadata(self):
        agent = self.start()
        path = "people/maya.md"
        agent.memory_edit("", f"## Allergies\n\n{FACT}\n\nCarry a reminder.\n\n## Schedule\n\nVisits on Sunday.", path=path)
        items = self.app.memory_index.corpus(agent.config, agent.memory)
        allergy, = [row for row in items if row["path"] == path and row["heading"] == "Allergies"]
        self.assertEqual(allergy["excerpt"], f"{FACT}\n\nCarry a reminder.")
        self.assertEqual(self.storage.read(path).splitlines()[allergy["line"] - 1], FACT)
        metadata = recall.metadata(allergy)
        self.assertEqual((metadata["id"], metadata["type"], metadata["related"]),
                         ("people/maya", "contact", ["topics/thanksgiving"]))
        self.assertTrue(metadata["updated"])

    def test_forget_from_chat_removes_managed_sources_and_blocks_resaving(self):
        agent = self.start()
        agent.memory_edit("", f"## Allergies\n\n{FACT}", id="people/maya")
        agent.memory_edit("", FACT, id="home-and-health")
        with self.storage.lock():
            agent.threads.append("main", "user", FACT)
            agent.threads.append("main", "user", "The picnic is on Sunday.")
        agent.memory_search("Maya peanuts")

        def fixture_model(_model, messages, _tools, _emit, **_kwargs):
            if messages[-1]["role"] == "tool":
                return {"role": "assistant", "content": "I forgot the requested detail."}
            return tool_call("memory_forget", {"matches": [["Maya", "peanuts"]]})

        agent.models = [{**agent.models[0], "provider": "openai", "connection_id": "fixture"}]
        agent.tools.gateway.completion = fixture_model
        events = []
        agent.chat("Forget Maya’s peanut allergy.", lambda name, item: events.append((name, item)))
        self.assertTrue(any(name == "action" and item.get("permanent") for name, item in events))
        self.assertEqual(len(memory.standing_rules(self.storage)), 1)
        self.assertFalse(memory.matches_rule("Maya likes picnics", memory.standing_rules(self.storage)))
        for path in self.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"peanuts", path.read_bytes(), path.name)
        self.assertIn("The picnic is on Sunday.", [row["content"] for row in agent.threads.messages("main")])
        self.assertIn("vegetarian", self.storage.read("people/maya.md"))
        with self.assertRaisesRegex(HearthError, "standing forget rule"):
            agent.memory_edit("", FACT, id="people/maya")
        self.assertFalse(any("peanuts" in row["excerpt"] for row in agent.memory_search("Maya")["results"]))


if __name__ == "__main__":
    unittest.main()
