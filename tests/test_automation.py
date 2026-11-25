import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from hearth import approvals, tasks
from hearth.agent import TOOL_DEFINITIONS
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import read_config
from hearth.server import Application
from hearth.storage import ROOT, Storage, iso

NOW = datetime(2030, 1, 7, 17, tzinfo=timezone.utc)


class Disconnected:
    def discover(self):
        return {}, set()


class AutomationTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = Storage(directory.name)
        config = read_config(ROOT / "config/connectors.json")
        config["brain"] = {"provider": "mock", "model": ""}
        self.app = Application(self.storage, LocalCheckpoints(self.storage), config, gateway=Disconnected())
        self.agent = self.app.agent
        self.app.reminders.save({"quiet_start": "00:00", "quiet_end": "00:00"})

    def draft(self):
        return self.agent.execute("send_email", {"to": ["guest@example.com"], "subject": "Dinner", "text": "At 7."})["action"]

    def task(self, **changes):
        return tasks.mutate(self.storage, "create", {"name": "Brief", "instruction": "List my reminders",
                            "schedule": {"type": "interval", "minutes": 10}, **changes}, clock=NOW)

    def test_policy_covers_every_tool_and_classifies_dynamic_effects(self):
        inputs = {"browse_session": {"steps": []}, "memory_write": {"notes": [{"content": "Updated"}]}}
        for name in TOOL_DEFINITIONS:
            with self.subTest(name=name):
                self.assertIsInstance(approvals.classify(name, inputs.get(name, {})), tuple)
        self.assertEqual(approvals.classify("web_search", {}), ())
        self.assertEqual(approvals.classify("send_email", {}), ("send",))
        self.assertEqual(approvals.classify("browse_session", {"steps": []}), ("spend",))
        self.assertEqual(approvals.classify("memory_write", {"notes": [{"content": ""}]}), ("destructive",))
        self.assertEqual(approvals.classify("delete_recurring_task", {}), ("destructive",))
        connector = lambda provider, method, path, body=None: approvals.classify(
            "gateway_request", {"provider": provider, "method": method, "path": path, "body": body})
        self.assertEqual(connector("box", "GET", "/2.0/files/1"), ())
        self.assertEqual(connector("box", "DELETE", "/2.0/files/1"), ("destructive",))
        self.assertIn("send", connector("box", "PUT", "/2.0/files/1", {"shared_link": {}}))
        self.assertIn("public", connector("slack", "POST", "/api/chat.postMessage"))
        self.assertEqual(connector("browserbase", "POST", "/v1/sessions"), ("spend",))
        self.assertEqual(approvals.policy(self.storage.load()), approvals.DEFAULTS)

    def test_approval_edit_and_concurrent_idempotency(self):
        row = self.draft()
        self.assertEqual(self.storage.load()["outbox"], [])
        approvals.decide(self.agent, row["id"], "edit", {"subject": "Updated", "text": "At 8."})
        started, release = threading.Event(), threading.Event()
        original = self.agent.execute_approved
        def wait(action):
            started.set()
            release.wait(5)
            return original(action)
        results = []
        thread = threading.Thread(target=lambda: results.append(approvals.decide(self.agent, row["id"], "approve")))
        with patch.object(self.agent, "execute_approved", side_effect=wait) as execution:
            thread.start()
            try:
                self.assertTrue(started.wait(5))
                self.assertEqual(approvals.decide(self.agent, row["id"], "approve")["status"], "changing")
            finally:
                release.set()
                thread.join(5)
            self.assertEqual(approvals.decide(self.agent, row["id"], "approve")["status"], "simulated")
            execution.assert_called_once()
        self.assertEqual(results[0]["status"], "simulated")
        self.assertEqual(self.storage.load()["outbox"], [{"id": row["id"], "to": ["guest@example.com"],
                                                         "subject": "Updated", "text": "At 8."}])
        self.assertEqual(len(self.app.threads.messages("main")), 1)

    def test_expiry_and_decline_never_execute(self):
        row = self.draft()
        expires = datetime.fromisoformat(row["expires_at"])
        with patch.object(self.agent, "execute_approved") as execution:
            self.assertEqual(approvals.decide(self.agent, row["id"], "approve", clock=expires)["status"], "expired")
            self.assertEqual(approvals.records(self.storage, pending=True, clock=expires), [])
            second = self.draft()
            approvals.decide(self.agent, second["id"], "decline")
            self.assertEqual(approvals.decide(self.agent, second["id"], "approve")["status"], "declined")
            execution.assert_not_called()
        activity = self.storage.load()["activity"]
        self.assertTrue(any(row["title"].startswith("Expired") for row in activity))
        self.assertTrue(any(row["title"].startswith("Declined") for row in activity))
        self.assertIn("declined", self.app.threads.messages("main")[-1]["content"])

    def test_local_schedule_preview_and_dst(self):
        fields = tasks.natural("Every weekday at 8am give me a brief of my reminders, weather and top AI news")
        self.assertEqual(fields["schedule"]["days"], [1, 2, 3, 4, 5])
        row = tasks.clean_fields(fields, NOW)
        self.assertEqual(row["timezone"], "America/Los_Angeles")
        self.assertEqual(tasks.preview(row, NOW), ["2030-01-08T08:00:00-08:00",
                                                   "2030-01-09T08:00:00-08:00", "2030-01-10T08:00:00-08:00"])
        zone = ZoneInfo("America/Los_Angeles")
        schedule = {"type": "cron", "cron": "30 2 * * *"}
        before_gap = datetime(2026, 3, 8, 9, tzinfo=timezone.utc)
        self.assertEqual(iso(tasks.next_run(schedule, zone, before_gap)), "2026-03-09T09:30:00+00:00")
        before_fold = datetime(2026, 11, 1, 8, tzinfo=timezone.utc)
        schedule["cron"] = "30 1 * * *"
        first = tasks.next_run(schedule, zone, before_fold)
        self.assertEqual(iso(first), "2026-11-01T08:30:00+00:00")
        self.assertEqual(iso(tasks.next_run(schedule, zone, first)), "2026-11-02T09:30:00+00:00")

    def test_chat_task_confirmation_and_disabled_sample(self):
        self.agent.chat("Every weekday at 8am give me a brief of my reminders, weather and top AI news", lambda *_: None)
        proposal, = approvals.records(self.storage, pending=True)
        self.assertEqual(proposal["tool"], "create_recurring_task")
        self.assertEqual(len(proposal["upcoming"]), 3)
        self.assertEqual([row["enabled"] for row in tasks.mutate(self.storage, "list", {})["tasks"]], [False])
        self.assertEqual(approvals.decide(self.agent, proposal["id"], "approve")["status"], "complete")
        self.assertEqual(len(tasks.mutate(self.storage, "list", {})["tasks"]), 2)

    def test_runner_uses_normal_brain_and_deduplicates_after_restart(self):
        row = self.task()
        due = NOW + timedelta(minutes=10)
        self.assertEqual(self.app.task_runner.tick(due), 1)
        self.assertEqual(tasks.Runner(self.app).tick(due), 0)
        stored = self.storage.load()
        run, = stored["task_runs"].values()
        self.assertEqual(run["status"], "complete")
        self.assertEqual(run["tools"][0]["tool"], "list_reminders")
        self.assertIn("reminders", run["output"])
        self.assertEqual(stored["recurring_tasks"][row["id"]]["next_run"], iso(NOW + timedelta(minutes=20)))
        self.assertEqual(len(self.app.threads.messages(run["thread_id"])), 2)
        self.assertEqual(len(tasks.inbox_rows(stored, due)), 1)

    def test_restart_recovers_a_completed_chat_with_an_unfinished_run_claim(self):
        self.task()
        due = NOW + timedelta(minutes=10)
        run = self.app.task_runner.due(due)
        output, _, reason, _ = self.app.task_runner.run(run)
        self.assertIsNone(reason)
        self.assertEqual(self.storage.load()["task_runs"][run["id"]]["status"], "running")
        self.assertEqual(tasks.Runner(self.app).tick(due + timedelta(seconds=1)), 0)
        self.assertEqual(self.storage.load()["task_runs"][run["id"]]["output"], output)
        self.assertEqual(len(self.app.threads.messages(run["thread_id"])), 2)

    def test_notification_visibility_observes_quiet_hours(self):
        self.app.reminders.save({"quiet_start": "22:00", "quiet_end": "07:00"})
        self.task()
        due = datetime(2030, 1, 8, 7, tzinfo=timezone.utc)
        self.assertEqual(self.app.task_runner.tick(due), 1)
        state = self.storage.load()
        self.assertEqual(tasks.inbox_rows(state, due), [])
        self.assertEqual(len(tasks.inbox_rows(state, datetime(2030, 1, 8, 15, tzinfo=timezone.utc))), 1)

    def test_retry_once_and_record_reason_without_duplicate_occurrence(self):
        self.task()
        due = NOW + timedelta(minutes=10)
        with patch.object(self.app.task_runner, "run", return_value=("", [], "Connector failed.", 25)) as run:
            self.assertEqual(self.app.task_runner.tick(due), 1)
            self.assertEqual(self.app.task_runner.tick(due), 0)
            self.assertEqual(self.app.task_runner.tick(due + timedelta(minutes=1)), 1)
            self.assertEqual(self.app.task_runner.tick(due + timedelta(minutes=1)), 0)
            self.assertEqual(run.call_count, 2)
        stored, = self.storage.load()["task_runs"].values()
        self.assertEqual((stored["status"], stored["reason"], stored["attempts"]), ("failed", "Connector failed.", 2))

    def test_task_mail_notifies_only_the_configured_recipient(self):
        self.app.reminders.save({"recipient": "owner@example.com"})
        self.task(instruction="Email friend@example.com | Brief | In the morning.", delivery="both")
        with patch.object(self.app.reminders, "client") as client, patch.object(self.app.reminders, "mailbox"):
            client.return_value.send.return_value = {"message_id": "fixture"}
            self.assertEqual(self.app.task_runner.tick(NOW + timedelta(minutes=10)), 1)
            calls = client.return_value.send.call_args_list
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(call.args[1]["to"] == ["owner@example.com"] for call in calls))
            self.assertTrue(any(call.args[1]["subject"] == "Hearth: Approval needed" for call in calls))
        approval, = approvals.records(self.storage, pending=True)
        self.assertEqual(approval["email"]["to"], ["friend@example.com"])

    def test_scheduled_send_always_asks_even_with_allow_policy(self):
        approvals.settings(self.storage, {"send": "allow"})
        self.task(instruction="Email friend@example.com | Brief | In the morning.")
        self.assertEqual(self.app.task_runner.tick(NOW + timedelta(minutes=10)), 1)
        approval, = approvals.records(self.storage, pending=True)
        self.assertEqual(approval["email"]["to"], ["friend@example.com"])
        stored = self.storage.load()
        self.assertEqual(stored["outbox"], [])
        self.assertEqual(next(iter(stored["task_runs"].values()))["status"], "approval_needed")
        self.assertIn(approval["id"], stored["task_notifications"])
        self.assertEqual(self.agent.approve(approval["id"])["status"], "simulated")
