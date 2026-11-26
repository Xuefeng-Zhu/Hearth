import tempfile
import unittest
from unittest.mock import patch

from hearth import approvals, skills
from hearth.agent import TOOL_DEFINITIONS, tool_call
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import read_config
from hearth.server import Application
from hearth.storage import HearthError, ROOT, Storage


def playbook(name="Pack for camp", body="1. Make a packing list.", tools=()):
    return skills.format_skill({"name": name, "description": "Prepare a camp packing list.",
                               "when_to_use": "When packing for camp.", "tools": list(tools), "content": body})


class Disconnected:
    def discover(self):
        return {}, set()


class SkillsTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = Storage(directory.name)
        config = read_config(ROOT / "config/connectors.json")
        config["brain"] = {"provider": "mock", "model": ""}
        self.app = Application(self.storage, LocalCheckpoints(self.storage), config, gateway=Disconnected())
        self.agent = self.app.agent
        self.library = self.agent.skills

    def create(self, markdown=None):
        return self.library.mutate("create", {"markdown": markdown or playbook()})

    def test_builtin_seed_and_duplicate(self):
        self.assertEqual({row["name"] for row in self.library.list()},
                         {"Plan a dinner party", "Weekly family brief", "Research and compare", "Draft an email"})
        self.assertEqual(len(list((self.storage.live / "skills").glob("*.md"))), 4)
        builtin = self.library.detail("plan-dinner-party")
        for operation, args in (("delete", {}), ("save", {"markdown": playbook()})):
            with self.assertRaisesRegex(HearthError, "Duplicate a built-in"):
                self.library.mutate(operation, {"id": builtin["id"], "revision": builtin["revision"], **args})
        copied, action = self.library.mutate("duplicate", {"id": builtin["id"]})
        self.assertEqual(copied["name"], "Plan a dinner party (copy)")
        self.assertFalse(copied["builtin"])
        self.assertEqual(copied["tools"], builtin["tools"])
        self.assertIn("duplicated", action["title"])

    def test_validation_and_case_insensitive_unique_names(self):
        for markdown in ("# Missing front matter", playbook(tools=["made_up"]), playbook(""),
                         playbook().replace('"When packing for camp."', "&value [*value]")):
            with self.subTest(markdown=markdown), self.assertRaises(HearthError):
                self.create(markdown)
        self.create()
        with self.assertRaisesRegex(HearthError, "already exists"):
            self.create(playbook("pack FOR Camp"))
        with self.assertRaisesRegex(HearthError, "does not exist"):
            self.library.detail("../../memory/USER")

    def test_revisions_and_item_level_undo_survive_restart(self):
        original, creation = self.create()
        identity = original["id"]
        revised, edit = self.library.mutate("save", {"id": identity, "revision": original["revision"],
                                                     "markdown": playbook(body="1. Add a rain jacket.")})
        self.assertEqual([item["number"] for item in revised["versions"]], [2, 1])
        self.assertEqual(self.library.detail(identity, original["revision"])["content"], original["content"])
        with self.assertRaisesRegex(HearthError, "changed"):
            self.library.mutate("delete", {"id": identity, "revision": original["revision"]})
        with self.assertRaisesRegex(HearthError, "newer"):
            self.library.undo(creation["id"])
        _, deletion = self.library.mutate("delete", {"id": identity, "revision": revised["revision"]})
        self.assertEqual(len(self.library.list()), 4)
        self.assertFalse((self.library.root / f"{identity}.md").exists())
        self.storage.write("topics/fixture.md", "Independent workspace change")
        rows = self.app.timeline_info()["entries"]
        self.assertTrue(next(row for row in rows if row["action_id"] == deletion["id"])["undoable"])
        self.assertFalse(next(row for row in rows if row["action_id"] == edit["id"])["undoable"])
        self.assertTrue(self.app.undo_action(deletion["id"])["undone"])
        library = skills.Skills(Storage(self.storage.root), TOOL_DEFINITIONS)
        self.assertEqual(library.detail(identity)["content"], revised["content"])
        library.undo(edit["id"])
        self.assertEqual(library.detail(identity)["content"], original["content"])
        library.undo(creation["id"])
        self.assertEqual(len(library.list()), 4)
        self.assertEqual(self.storage.read("topics/fixture.md"), "Independent workspace change")

    def test_failed_save_keeps_last_markdown_and_timeline(self):
        original, _ = self.create()
        identity = original["id"]
        current = self.library.root / f"{identity}.md"
        with patch.object(self.storage, "save", side_effect=OSError("fixture")):
            with self.assertRaises(OSError):
                self.library.mutate("save", {"id": identity, "revision": original["revision"],
                                             "markdown": playbook(body="Not committed.")})
        self.assertEqual(current.read_text(), original["markdown"])
        self.assertEqual(self.library.detail(identity)["revision"], original["revision"])
        self.assertEqual(len(self.storage.load()["actions"]), 1)

    def test_chat_writes_wait_for_approval_and_stale_edits_fail(self):
        proposal = self.agent.execute("skill_create", {"name": "Pack for camp", "description": "Plan camping.",
                                                       "content": playbook()})["action"]
        self.assertEqual((proposal["categories"], proposal["status"]), (["skills"], "pending"))
        self.assertEqual(len(self.library.list()), 4)
        complete = approvals.decide(self.agent, proposal["id"], "approve")
        identity = complete["result"]["skill_id"]
        self.assertEqual(self.library.detail(identity)["description"], "Plan camping.")
        fields = {"name": "Pack for camp", "find": "Make a packing list.", "replace": "Make a checklist."}
        first = self.agent.execute("skill_edit", fields)["action"]
        second = self.agent.execute("skill_edit", {**fields, "replace": "Pack boots."})["action"]
        self.assertEqual(approvals.decide(self.agent, first["id"], "approve")["status"], "complete")
        self.assertEqual(approvals.decide(self.agent, second["id"], "approve")["status"], "failed")
        self.assertEqual(self.library.detail(identity)["content"], "1. Make a checklist.")
        self.assertEqual(approvals.settings(self.storage, {"skills": "allow"})["destructive"], "ask")
        result = self.agent.execute("skill_edit", {**fields, "find": "Make a checklist."})["action"]
        self.assertEqual(result["status"], "complete")

    def test_model_loads_custom_skill_before_using_its_tools(self):
        custom, _ = self.create(playbook(tools=["list_reminders"]))
        self.agent.models = [{"provider": "test-brain", "model": "test"}]
        events = []

        def complete(model, messages, tools, emit):
            names = {tool["function"]["name"] for tool in tools}
            results = [item["content"] for item in messages if item["role"] == "tool"]
            if not results:
                self.assertIn('"name": "Pack for camp", "description": "Prepare a camp packing list."', messages[0]["content"])
                self.assertNotIn("Make a packing list.", messages[0]["content"])
                return tool_call("skill_load", {"name": "pack FOR camp"})
            self.assertEqual(names, {"list_reminders"})
            self.assertIn("Make a packing list.", results[0])
            if len(results) == 1:
                return tool_call("send_email", {})
            self.assertIn("unavailable", results[1])
            return {"role": "assistant", "content": "Bring a flashlight."}

        with patch.object(self.agent, "model_completion", side_effect=complete):
            self.agent.chat("Help me prepare for a weekend at camp.", lambda *event: events.append(event))
        chip, = [data for name, data in events if name == "skill_loaded"]
        self.assertEqual(chip, {"id": custom["id"], "name": custom["name"]})
        done, = [data for name, data in events if name == "done"]
        self.assertEqual(done["message"]["skill"], chip)
        self.assertEqual(self.library.detail(custom["id"])["use_count"], 1)
        self.assertEqual(approvals.records(self.storage), [])

    def test_dinner_skill_can_create_implicit_workbook(self):
        events = []
        self.agent.chat("Please plan a dinner party for four.", lambda *event: events.append(event))
        chip = next(data for name, data in events if name == "skill_loaded")
        self.assertEqual(chip["id"], "plan-dinner-party")
        done = next(data["message"] for name, data in events if name == "done")
        self.assertEqual(done["skill"], chip)
        self.assertEqual(done["artifacts"][0]["format"], "xlsx")
        self.assertEqual(self.library.detail(chip["id"])["use_count"], 1)

    def test_scheduling_the_family_brief_does_not_run_it(self):
        events = []
        self.agent.chat("Every Sunday at 8am give me a weekly family brief.", lambda *event: events.append(event))
        self.assertNotIn("skill_loaded", [name for name, _ in events])
        proposal, = approvals.records(self.storage, pending=True)
        self.assertEqual(proposal["tool"], "create_recurring_task")
        self.assertEqual(self.library.detail("weekly-family-brief")["use_count"], 0)
        self.agent.chat("Show my weekly family brief with recurring tasks.", lambda *event: events.append(event))
        self.assertIn("skill_loaded", [name for name, _ in events])

    def test_draft_only_hides_send_and_followup_forces_approval(self):
        self.agent.models = [{"provider": "test-brain", "model": "test"}]
        approvals.settings(self.storage, {"send": "allow"})

        def complete(model, messages, tools, emit):
            names = {tool["function"]["name"] for tool in tools}
            current = next(message["content"] for message in reversed(messages) if message["role"] == "user")
            if current.startswith("Draft"):
                self.assertNotIn("send_email", names)
                return {"role": "assistant", "content": "Subject: Dinner\n\nWill you join us?"}
            self.assertIn("send_email", names)
            if messages[-1]["role"] == "tool":
                return {"role": "assistant", "content": "Review the draft on the approval card."}
            return tool_call("send_email", {"to": ["@".join(("guest", "example.invalid"))],
                                            "subject": "Dinner", "text": "Will you join us?"})

        with patch.object(self.agent, "model_completion", side_effect=complete):
            self.agent.chat("Draft an email about dinner to guest@example.invalid.", lambda *_: None)
            self.assertEqual(approvals.records(self.storage), [])
            self.agent.chat("Send it.", lambda *_: None)
        proposal, = approvals.records(self.storage, pending=True)
        self.assertEqual(proposal["tool"], "send_email")
        self.assertEqual(self.storage.load()["outbox"], [])

    def test_research_uses_exa_with_existing_search_filters(self):
        self.agent.search_settings = {**self.agent.search_settings, "provider": "tavily", "max_results": 2}
        self.agent.models = [{"provider": "test-brain", "model": "test"}]

        def complete(model, messages, tools, emit):
            if messages[-1]["role"] == "tool":
                return {"role": "assistant", "content": "Comparison complete."}
            return tool_call("web_search", {"query": "camp lanterns"})

        self.agent.config["gateway"]["exa"] = {"provider": "exa", "connection_id": "fixture"}
        with patch.object(self.agent, "model_completion", side_effect=complete), \
                patch.object(self.agent, "run_search", return_value={"results": []}) as run:
            self.agent.chat("Research and compare camp lanterns.", lambda *_: None)
        run.assert_called_once_with("camp lanterns", {**self.agent.search_settings, "provider": "exa"})


if __name__ == "__main__":
    unittest.main()
