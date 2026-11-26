import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from hearth import approvals, goals, memory, memory_purge, reminders, scheduler, tasks
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import ConnectorError, read_config
from hearth.server import Application
from hearth.storage import HearthError, ROOT, Storage, iso

NOW = datetime(2030, 4, 3, 18, tzinfo=timezone.utc)
TOPICS = ["Seed labels", "Trail snacks", "Market stall", "Garden map", "Lanterns", "Orchard trip"]


def idea(kind, source, topic, **fields):
    return {"kind": kind, "source": source, "topic": topic, "title": topic,
            "detail": "Make the next step easier.", **fields}


class FakeBrain:
    def __init__(self):
        self.results = []
        self.requests = []

    def discover(self):
        return {}, set()

    def request(self, *args, **kwargs):
        raise ConnectorError("Fixture has no other connections.", 404, missing_connection=True)

    def completion(self, config, messages, tools, progress, **limits):
        assert not tools
        assert "untrusted reference data" in messages[0]["content"]
        self.requests.append(json.loads(messages[1]["content"]))
        return {"content": json.dumps({"items": self.results})}


class IdeasGoalsTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = Storage(directory.name)
        config = read_config(ROOT / "config/connectors.json")
        config["brain"] = {"provider": "mock", "model": ""}
        self.brain = FakeBrain()
        self.app = Application(self.storage, LocalCheckpoints(self.storage), config, gateway=self.brain)
        with self.storage.lock():
            state = self.storage.load()
            state["proactivity_settings"] = {"quiet_start": "00:00", "quiet_end": "00:00"}
            self.storage.save(state)
            self.storage.write("topics/greenhouse.md", "# Greenhouse\n\nPlan the seedling exchange.")
        self.source = "memory:topics/greenhouse.md"

    def model(self):
        self.app.agent.models = [{"provider": "test-brain", "model": "fixture"}]

    def create_goal(self, title="Open the seed library", **fields):
        return goals.mutate(self.storage, "goal_create", {"title": title, **fields}, clock=NOW)

    def test_create_and_delete_approval_and_timeline_undo(self):
        proposed = self.app.agent.execute("goal_create", {"title": "Ship the seed library", "target_date": "2030-04-10"})["action"]
        self.assertEqual(proposed["status"], "pending")
        self.assertEqual(goals.list_goals(self.storage.load()), [])
        approved = approvals.decide(self.app.agent, proposed["id"], "approve")
        row = goals.list_goals(self.storage.load())[0]
        self.assertEqual(approved["status"], "complete")
        self.assertIn(row["id"], self.app.agent.memory_context())
        deleting = self.app.agent.execute("goal_update", {"id": row["id"], "delete": True})["action"]
        self.assertEqual(deleting["status"], "pending")
        self.assertEqual(len(goals.list_goals(self.storage.load())), 1)
        deleted = approvals.decide(self.app.agent, deleting["id"], "approve")
        self.assertEqual(goals.list_goals(self.storage.load()), [])
        entry = next(item for item in self.app.timeline_info()["entries"] if item.get("action_id") == deleted["effect_action"])
        self.assertTrue(entry["undoable"])
        restored, code = self.app.undo_action(deleted["effect_action"])
        self.assertEqual(code, 200)
        self.assertTrue(restored["undone"])
        self.assertEqual(goals.list_goals(self.storage.load())[0]["target_date"], "2030-04-10")

    def test_stale_delete_approval_and_revision_scoped_undo(self):
        first = self.create_goal()
        goal = first["goal"]
        args = {"id": goal["id"], "revision": goal["revision"]}
        proposed = self.app.agent.execute("goal_update", {**args, "delete": True})["action"]
        updated = self.app.agent.execute("goal_checkin", {**args, "progress": 45, "note": "Labels printed"})
        self.assertEqual(approvals.decide(self.app.agent, proposed["id"], "approve")["status"], "failed")
        self.assertEqual(updated["goal"]["progress"]["percent"], 45)
        with self.assertRaises(HearthError):
            self.app.undo_action(first["action"]["id"])
        self.app.undo_action(updated["action"]["id"])
        self.assertEqual(goals.list_goals(self.storage.load())[0]["progress"]["percent"], 0)
        self.app.undo_action(first["action"]["id"])
        self.assertEqual(goals.list_goals(self.storage.load()), [])

    def test_link_progress_and_snoozed_reminder_completion(self):
        task = tasks.mutate(self.storage, "create", {"name": "Stock the cabinet", "instruction": "Review stock",
                           "schedule": {"type": "daily", "time": "13:00"}}, clock=NOW)
        with self.storage.lock():
            state = self.storage.load()
            reminder = scheduler.add_job(state, "Check inventory", clock=NOW, at=iso(NOW + timedelta(minutes=1)))
            self.storage.save(state)
        links = [{"kind": "task", "id": task["id"]}, {"kind": "reminder", "id": reminder["id"]}]
        row = self.create_goal(links=links)["goal"]
        self.assertEqual(row["progress"]["percent"], 0)
        scheduler.run_due(self.storage, NOW + timedelta(minutes=1))
        self.assertEqual(goals.list_goals(self.storage.load())[0]["progress"]["percent"], 0)
        with self.storage.lock():
            state = self.storage.load()
            reminders.change_occurrence(state, state["reminders"][0], "snooze-10", NOW + timedelta(minutes=1))
            self.storage.save(state)
        scheduler.run_due(self.storage, NOW + timedelta(minutes=11))
        with self.storage.lock():
            state = self.storage.load()
            reminders.change_occurrence(state, state["reminders"][1], "done", NOW + timedelta(minutes=11))
            state["task_runs"] = {"run-fixture": {"task_id": task["id"], "status": "complete"}}
            self.storage.save(state)
        self.assertEqual(goals.list_goals(self.storage.load())[0]["progress"]["percent"], 100)
        with self.assertRaises(HearthError):
            goals.mutate(self.storage, "goal_checkin", {"id": row["id"], "progress": 25}, clock=NOW)

    def test_checkin_reminder_keeps_local_time_and_returns_after_undo(self):
        now = datetime(2030, 3, 9, 17, tzinfo=timezone.utc)
        result = goals.mutate(self.storage, "goal_create", {"title": "Spring training",
                              "checkin": {"cadence": "daily", "time": "09:30"}}, clock=now)
        row = result["goal"]
        self.assertEqual(row["next_checkin"], "2030-03-09T17:30:00+00:00")
        self.assertEqual(scheduler.run_due(self.storage, now + timedelta(minutes=30)), 1)
        self.assertEqual(goals.list_goals(self.storage.load())[0]["next_checkin"], "2030-03-10T16:30:00+00:00")
        done = goals.mutate(self.storage, "goal_checkin", {"id": row["id"], "progress": 100}, clock=now)
        self.assertIsNone(done["goal"]["next_checkin"])
        goals.undo(self.storage, done["action"]["id"], clock=now)
        self.assertIsNotNone(goals.list_goals(self.storage.load())[0]["next_checkin"])

    def test_idea_cap_dedupe_feedback_and_draft(self):
        self.model()
        self.brain.results = [idea("slides", "memory:missing.md", "Unknown"),
                              idea("slides", self.source, "Seed labels"),
                              idea("chat", self.source, "Seed-labels"),
                              *[idea("chat", self.source, topic) for topic in TOPICS[1:]]]
        self.assertEqual(self.app.ideas.tick(NOW), "complete")
        cards = self.app.feed.list(clock=NOW)["ideas"]
        self.assertEqual(len(cards), 5)
        self.assertEqual(sum(row["kind"] == "slides" for row in cards), 1)
        slide = next(row for row in cards if row["kind"] == "slides")
        result = self.app.ideas.respond({"id": slide["id"], "operation": "open"}, NOW)
        self.assertIn("Create a slide deck", result["draft"])
        self.assertIn("seedling exchange", result["draft"])
        self.assertEqual(self.app.threads.messages(result["thread"]["id"]), [])
        self.app.ideas.respond({"id": cards[0]["id"], "operation": "not-interested"}, NOW)
        self.app.ideas.respond({"id": cards[1]["id"], "operation": "dismiss"}, NOW)
        self.app.ideas.tick(NOW + timedelta(days=8), force=True)
        refreshed = self.app.feed.list(clock=NOW + timedelta(days=8))["ideas"]
        self.assertNotIn(cards[0]["title"], [row["title"] for row in refreshed])
        self.assertIn(cards[1]["title"], [row["title"] for row in refreshed])

    def test_long_chat_fires_early_and_next_step_matches_goal_revision(self):
        self.model()
        self.assertEqual(self.app.ideas.tick(NOW), "complete")
        row = self.create_goal()["goal"]
        with self.storage.lock():
            for _ in range(4):
                message = self.app.threads.append("main", "user", "Reviewing plans for the toy observatory.", at=iso(NOW))
                self.app.threads.append("main", "assistant", "Here is a draft.", at=iso(NOW))
        self.brain.results = [idea("chat", f"chat:main/{message['id']}", "Observatory plan"),
                              {"kind": "goal", "id": row["id"], "text": "Label ten seed envelopes."}]
        later = NOW + timedelta(minutes=3)
        self.assertEqual(self.app.ideas.tick(later, thread="main"), "complete")
        self.assertEqual(self.app.ideas.tick(later, thread="main"), "not-due")
        self.assertEqual(goals.list_goals(self.storage.load())[0]["next_step"], "Label ten seed envelopes.")
        updated = goals.mutate(self.storage, "goal_checkin", {"id": row["id"], "progress": 20}, clock=later)
        self.assertIsNone(updated["goal"]["next_step"])

    def test_watcher_requires_approval_and_notifies_only_on_change(self):
        self.model()
        with self.storage.lock():
            source = self.app.threads.append("main", "user", "Comparing planters at https://example.org/planters", at=iso(NOW))
        self.brain.results = [idea("watcher", f"chat:main/{source['id']}", "Planter prices", mode="price")]
        self.app.ideas.tick(NOW)
        idea_id = self.app.feed.list(clock=NOW)["ideas"][0]["id"]
        approval = self.app.ideas.respond({"id": idea_id, "operation": "open"}, NOW)["action"]
        self.assertEqual(approval["status"], "pending")
        self.assertEqual(self.storage.load().get("recurring_tasks", {}), {})
        payload = self.brain.requests[0]
        watch_source = next(row for row in payload["available_sources"] if row["watchable_page"])
        self.assertNotIn("example.org", watch_source["text"])
        approved = approvals.decide(self.app.agent, approval["id"], "approve", clock=NOW)
        self.assertEqual(approved["status"], "complete")
        self.assertIn(approved["result"]["task_id"], self.storage.load()["recurring_tasks"])
        with patch("hearth.panels.public_page", side_effect=["USD 40", "USD 40", "USD 35"]):
            for offset in range(1, 4):
                when = NOW + timedelta(days=offset)
                self.assertEqual(self.app.task_runner.tick(when), 1)
                notifications = self.storage.load().get("task_notifications", {})
                self.assertEqual(len(notifications), int(offset == 3))
        self.assertIn("USD 35", next(iter(notifications.values()))["text"])

    def test_scheduled_reminder_and_automation_ideas_wait_for_review(self):
        self.model()
        with self.storage.lock():
            state = self.storage.load()
            job = scheduler.add_job(state, "Open the garden gates", at=iso(NOW + timedelta(days=2)), clock=NOW)
            self.storage.save(state)
        at = iso(NOW + timedelta(days=1))
        self.brain.results = [idea("reminder", self.source, "Bring seed packets", at=at),
                              idea("automation", f"reminder:{job['id']}", "Close the shed", delay_minutes=120)]
        self.app.ideas.tick(NOW)
        for card in self.app.feed.list(clock=NOW)["ideas"]:
            action = self.app.ideas.respond({"id": card["id"], "operation": "open"}, NOW)["action"]
            self.assertEqual(action["status"], "pending")
            self.assertEqual(len(self.storage.load()["jobs"]), 1)
            self.assertFalse(self.storage.load().get("event_automations"))
        rows = {row["tool"]: row for row in approvals.records(self.storage, pending=True, clock=NOW)}
        for tool in ["schedule", "create_event_automation"]:
            self.assertEqual(approvals.decide(self.app.agent, rows[tool]["id"], "approve", clock=NOW)["status"], "complete")
        self.assertEqual(len(self.storage.load()["jobs"]), 2)
        self.assertEqual(len(self.storage.load()["event_automations"]), 1)

    def test_forget_removes_goal_history_and_invalidates_open_ideas(self):
        row = self.create_goal("Novel Glass Orchard", checkin={"cadence": "daily", "time": "09:00"})["goal"]
        self.model()
        self.brain.results = [idea("reminder", self.source, "Bring seed packets", at=iso(NOW + timedelta(days=1)))]
        self.app.ideas.tick(NOW)
        card = self.app.feed.list(clock=NOW)["ideas"][0]
        approval = self.app.ideas.respond({"id": card["id"], "operation": "open"}, NOW)["action"]
        rules = [memory.forget_rule([["novel glass orchard"]])]
        with self.storage.lock():
            memory_purge.apply(self.storage, rules)
        state = self.storage.load()
        self.assertFalse(goals.list_goals(state))
        self.assertFalse(any(job.get("goal_id") == row["id"] for job in state["jobs"]))
        self.assertFalse(state.get("goal_undo"))
        self.assertEqual(state["actions"][approval["id"]]["status"], "expired")
        self.assertNotIn("Novel Glass Orchard", json.dumps(state))
