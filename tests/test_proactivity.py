import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from hearth import approvals, memory, proactivity, scheduler, tasks
from hearth.agent import CHAT_ORIGIN
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import read_config
from hearth.proactive_context import Context
from hearth.server import Application
from hearth.storage import ROOT, HearthError, Storage, iso

NOW = datetime(2030, 1, 7, 17, tzinfo=timezone.utc)
PERSON = "memory:people/maya.md"


class Disconnected:
    def discover(self):
        return {}, set()

    def completion(self, *args, **kwargs):
        raise AssertionError("Unexpected brain request")


def offer(key="birthday-2030", *, kind="gifts", source=PERSON, action_type="chat", **action):
    return {
        "title": "Find a birthday gift", "why": "There’s an occasion coming up soon.", "kind": kind,
        "urgency": "upcoming", "expiry_hours": 240, "dedupe_key": key, "sources": [source],
        "action": {"type": action_type, "label": "Compare three options",
                   "prompt": "Suggest three thoughtful gift ideas.", **action},
    }


class ProactivityTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = Storage(directory.name)
        config = read_config(ROOT / "config/connectors.json")
        config["brain"] = {"provider": "mock", "model": ""}
        self.app = Application(self.storage, LocalCheckpoints(self.storage), config, gateway=Disconnected())
        self.engine = self.app.proactivity
        self.agent = self.app.agent
        self.agent.models = [{"provider": "test-brain", "model": "fixture"}]

    def change_settings(self, **settings):
        with patch.object(self.engine, "kick"):
            self.engine.save_settings(settings)

    def run_pass(self, now, *offers, force=False):
        completion = {"content": "```json\n" + json.dumps({"suggestions": offers}, ensure_ascii=False) + "\n```"}
        with patch.object(self.agent.tools.gateway, "completion", return_value=completion) as brain:
            result = self.engine.tick(now, force=force)
            self.assertEqual(brain.call_count, result["status"] == "complete" and "provider" in result)
        return result

    def test_pacific_quiet_hours_frequency_and_trigger_coalescing(self):
        quiet = NOW.replace(hour=14, minute=59)
        self.assertEqual(self.run_pass(quiet, offer(), force=True)["status"], "quiet")
        awake = quiet + timedelta(minutes=1)
        self.assertEqual(self.run_pass(awake)["status"], "complete")
        self.assertEqual(self.run_pass(awake + timedelta(minutes=119))["status"], "not-due")
        self.assertEqual(self.run_pass(awake + timedelta(minutes=120))["status"], "complete")
        self.storage.write("topics/thanksgiving.md", "# Updated plans")
        self.assertEqual(self.run_pass(awake + timedelta(minutes=121))["status"], "not-due")
        self.assertEqual(self.run_pass(awake + timedelta(minutes=130))["status"], "complete")
        with self.storage.lock():
            state = self.storage.load()
            state["inbox"] = {"new": {"id": "new", "received_at": iso(awake), "status": "review",
                                     "title": "Train booking", "body": "Check-in is at 3 PM.",
                                     "proposal": {"kind": "event"}}}
            self.storage.save(state)
        later = awake + timedelta(minutes=140)
        row, = self.run_pass(later, offer("rail-2030", kind="travel", source="inbox:new"))["suggestions"]
        self.assertEqual(row["kind"], "travel")
        self.assertEqual(self.storage.load()["jobs"], [])
        self.assertEqual(self.app.threads.messages("main"), [])
        self.change_settings(enabled=False)
        self.assertEqual(self.run_pass(later, force=True)["status"], "off")
        self.assertEqual(self.engine.list(later), [])

    def test_dedup_limits_snoozes_and_timeline(self):
        self.change_settings(max_per_day=5)
        options = [offer(f"choice-{kind}", kind=kind) for kind in ("gifts", "events", "research", "shopping", "planning")]
        first = self.run_pass(NOW, *options)["suggestions"]
        self.assertEqual(len(first), 3)
        self.engine.update("snooze", {"id": first[0]["id"], "days": 1}, NOW)
        self.engine.update("dismiss", {"id": first[1]["id"]}, NOW)
        self.assertEqual(len(self.engine.list(NOW)), 1)
        second = self.run_pass(NOW + timedelta(hours=2), options[0], *options[3:])["suggestions"]
        self.assertEqual(len(second), 1)  # Two slots left and the first returned candidate is a duplicate.
        third = self.run_pass(NOW + timedelta(hours=4), options[4])["suggestions"]
        self.assertEqual(len(third), 1)
        self.assertEqual(self.run_pass(NOW + timedelta(hours=6))["status"], "daily-limit")
        sunrise = NOW + timedelta(days=1)
        self.assertEqual(self.run_pass(sunrise)["suggestions"][0]["id"], first[0]["id"])
        self.engine.update("snooze", {"id": first[0]["id"], "days": 7}, sunrise)
        self.assertNotIn(first[0]["id"], [row["id"] for row in self.engine.list(sunrise)])
        self.assertEqual(self.run_pass(sunrise + timedelta(days=7))["suggestions"][0]["id"], first[0]["id"])
        self.assertEqual(len([row for row in self.storage.load()["activity"] if row["title"] == "Suggestion shown"]), 7)

    def test_preference_and_sources_recheck_for_visibility_and_action(self):
        options = [offer("plan-first"), offer("review-first", kind="research")]
        gift, research = self.run_pass(NOW, *options)["suggestions"]
        self.engine.update("block", {"id": gift["id"]}, NOW)
        self.assertIn("- [x] gifts", self.storage.read(memory.PROACTIVITY_NOTE))
        self.assertEqual(self.engine.get_settings()["blocked"], ["gifts"])
        result = self.run_pass(NOW + timedelta(hours=2), offer("plan-second", source="memory:people/daniel.md"))
        self.assertEqual(result["suggestions"], [])
        self.storage.write("people/maya.md", "# Updated details")
        self.assertEqual(self.engine.list(NOW), [])
        with self.assertRaisesRegex(HearthError, "no longer available"):
            self.engine.update("do", {"id": research["id"]}, NOW)

    def test_forget_filters_sources_and_invalidates_cached_cards(self):
        phrase = "An uncommon constellation appears in this note."
        self.storage.write("people/maya.md", "# A detail\n\n" + phrase)
        with self.storage.lock():
            self.app.threads.append("main", "user", phrase)
        self.assertTrue(self.run_pass(NOW, offer())["suggestions"])
        self.app.forget_memory({"path": "people/maya.md"})
        state = self.storage.load()
        self.assertEqual(self.engine.cards(state, NOW), [])
        records = Context(self.app, state).collect(datetime.now(timezone.utc))
        self.assertFalse(any("constellation" in row["text"] for row in records))
        self.assertNotIn("constellation", json.dumps(state.get("proactivity", {})))

    def test_read_only_exa_and_private_why(self):
        self.storage.write("people/maya.md", "# Picnic\n\nThe yellow banner is kept beside the striped picnic basket.")
        self.agent.config["gateway"] = {"exa": {"provider": "exa", "connection_id": "fixture"}}
        lookup = {"content": '{"public_search":"weather in Portland tomorrow"}'}
        unsafe = {**offer(), "why": "The yellow banner is kept beside the striped picnic basket."}
        safe = offer("park-weather", kind="weather")
        answer = {"content": json.dumps({"suggestions": [unsafe, safe]})}
        with patch.object(self.agent.tools.gateway, "completion", side_effect=[lookup, answer]) as brain, patch(
            "hearth.proactivity.search.search",
            return_value={"results": [{"title": "Local forecast", "snippet": "Dry conditions."}]},
        ) as search:
            result = self.engine.tick(NOW)
        self.assertEqual([row["kind"] for row in result["suggestions"]], ["weather"])
        self.assertTrue(all(call.args[2] == [] for call in brain.call_args_list))
        self.assertEqual(search.call_args.args[2]["provider"], "exa")
        self.assertIn("Dry conditions", brain.call_args.args[1][-1]["content"])

    def test_do_it_is_idempotent_and_forces_approval(self):
        approvals.settings(self.storage, {"send": "allow"})
        card, = self.run_pass(NOW, offer(action_type="workers"))["suggestions"]
        thread, prompt = self.engine.update("do", {"id": card["id"]}, NOW)
        self.assertIn("Use parallel workers", prompt)
        self.assertEqual(self.engine.update("do", {"id": card["id"]}, NOW), (thread, None))
        token = CHAT_ORIGIN.set({"source": proactivity.SOURCE, "thread_id": thread["id"], "thread_title": thread["title"]})
        try:
            side_effect = self.agent.execute("send_email", {
                "to": ["sample@example.invalid"], "subject": "Example", "text": "An example."})
        finally:
            CHAT_ORIGIN.reset(token)
        self.assertEqual(side_effect["action"]["status"], "pending")
        self.assertEqual(self.storage.load()["outbox"], [])
        entries = [row for row in self.storage.load()["activity"] if row["kind"] == proactivity.SOURCE]
        self.assertEqual([row["title"] for row in entries], ["Suggestion shown", "Suggestion acted on"])
        self.assertEqual(entries[-1]["thread_id"], thread["id"])

    def test_reminder_handoff_defaults_to_app_and_explicit_email_asks(self):
        self.app.reminders.save({"recipient": "owner@example.invalid", "channel": "email"})
        approvals.settings(self.storage, {"send": "allow"})
        token = CHAT_ORIGIN.set({"source": proactivity.SOURCE, "thread_id": "main", "thread_title": "Main"})
        try:
            reminder = {"message": "Check the schedule", "at": iso(NOW)}
            app_only = self.agent.execute("schedule", reminder)["action"]
            pending = self.agent.execute("schedule", {**reminder, "channel": "email"})["action"]
        finally:
            CHAT_ORIGIN.reset(token)
        self.assertEqual(app_only["job"]["channel"], "app")
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(len(self.storage.load()["jobs"]), 1)
        self.assertEqual(self.agent.approve(pending["id"])["status"], "complete")
        self.assertEqual([row["channel"] for row in self.storage.load()["jobs"]], ["app", "email"])

    def test_brief_seed_migrates_duplicate_and_is_read_only(self):
        with self.storage.lock():
            state = self.storage.load()
            tasks.seed(state, NOW)
            row = state["recurring_tasks"][tasks.BRIEF_ID]
            row["instruction"] = tasks.OLD_BRIEF
            state["recurring_tasks"]["duplicate"] = {**row, "id": "duplicate", "enabled": True, "next_run": iso(NOW)}
            scheduler.add_job(state, "Pick up the groceries", NOW, at=iso(NOW + timedelta(hours=1)))
            state["weather"] = {"location": "Example City", "place": {"name": "Example City"},
                                "value": {"temperature": 54, "code": 0}, "updated_at": iso(NOW), "attempted_at": iso(NOW)}
            self.storage.save(state)
        self.run_pass(NOW, offer())
        with self.storage.lock():
            state = self.storage.load()
            state["actions"]["approval"] = {"status": "pending", "kind": "page_share", "title": "Share the sample Page?"}
            self.storage.save(state)
        with patch.object(self.agent.tools.gateway, "completion") as brain:
            self.assertEqual(self.app.task_runner.tick(NOW), 1)
            brain.assert_not_called()
        state = self.storage.load()
        self.assertEqual(list(state["recurring_tasks"]), [tasks.BRIEF_ID])
        run, = state["task_runs"].values()
        for phrase in ("Pick up the groceries", "Find a birthday gift", "Example City · 54°F, clear", "Share the sample Page?"):
            self.assertIn(phrase, run["output"])
        self.assertEqual(state["outbox"], [])

    def test_email_digest_is_opt_in_private_and_once_a_day(self):
        self.app.reminders.save({"recipient": "owner@example.invalid"})
        self.run_pass(NOW, offer())
        self.assertEqual(self.storage.load().get("task_notifications", {}), {})
        self.change_settings(email_digest=True, max_per_day=5)
        self.run_pass(NOW + timedelta(hours=2), offer("plan-event", kind="events"))
        with patch.object(self.app.reminders, "client") as client, patch.object(self.app.reminders, "mailbox"):
            client.return_value.send.return_value = {"message_id": "test-receipt"}
            self.app.task_runner.tick(NOW + timedelta(hours=2))
            self.run_pass(NOW + timedelta(hours=4), offer("research-plan", kind="research"))
            self.app.task_runner.tick(NOW + timedelta(hours=4))
            client.return_value.send.assert_called_once()
            message = client.return_value.send.call_args.args[1]
        self.assertEqual(message["to"], ["owner@example.invalid"])
        self.assertEqual(message["labels"], ["hearth-proactivity"])
        self.assertIn("Find a birthday gift", message["text"])
        self.assertNotIn("Suggest three thoughtful gift ideas.", message["text"])


if __name__ == "__main__":
    unittest.main()
