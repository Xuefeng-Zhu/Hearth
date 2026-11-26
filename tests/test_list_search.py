import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from urllib.parse import urlencode

from hearth import scheduler
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import read_config
from hearth.reminder_config import DEFAULTS
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage, iso


def seed_list_search(app):
    morning = datetime(2030, 6, 14, 16, 30, tzinfo=timezone.utc)
    with app.storage.lock():
        state = app.storage.load()
        scheduler.add_job(state, "Reserve the café table", morning, at=iso(morning + timedelta(days=1)),
                          channel="both", note="Ask about the courtyard and bring the printed reservation.")
        scheduler.add_job(state, "Pick up garden supplies", morning, at=iso(morning + timedelta(days=2)),
                          note="Get potting soil, labels, and twine.")
        snoozed = scheduler.add_job(state, "Call the café about the menu", morning, at=iso(morning + timedelta(hours=1)))
        snoozed["snoozed_at"] = iso(morning)
        delivered = scheduler.occurrence({"id": "delivered-job", "message": "Print the weekend itinerary",
                                          "channel": "app", "next_at": iso(morning)}, morning)
        state["reminders"].append(delivered)
        state["outbox"].append({"id": "fixture-outbox", "subject": "Hearth reminder: print the weekend itinerary",
                                "created_at": iso(morning), "kind": "reminder", "reason": "Demo"})
        app.storage.save(state)

    selection = {**DEFAULTS, "acknowledge": False}
    mailbox = {"address": "hearth-fixture@example.test", "key": "list-search-fixture"}
    emails = [
        ("garden", "Júlia Chen <julia@example.test>", "Community garden workshop",
         "We have reserved the café patio for Saturday. Bring a small plant to swap.",
         "The Saturday workshop is confirmed.", ["workshop", "community"]),
        ("booking", "Remy O’Neil <remy@example.test>", "Café reservation confirmed",
         "Your table for four is booked for Saturday at 11:30 a.m. Please arrive ten minutes early.",
         "Your table is confirmed.", ["booking"]),
        ("receipt", "Workshop desk <desk@example.test>", "Receipt for ceramic planters",
         "Thanks for stopping by. The total was $42.00. Fixture markup <img src=x>.",
         "Payment cleared.", ["purchase"]),
        ("forward", "Home Organizer <home@example.test>", "Dinner copy",
         "Forwarded message\nFrom: Léa Green <lea@example.test>\nSubject: Thursday potluck\n\nBring a salad.",
         "Potluck details", []),
    ]
    for index, (identity, sender, subject, body, preview, labels) in enumerate(emails):
        message = {"from": sender, "subject": subject, "text": body, "preview": preview, "labels": labels,
                   "created_at": iso(morning - timedelta(minutes=index))}
        assert app.inbox.process(None, mailbox, identity, identity, message, selection, morning) == 1
    with app.storage.lock():
        state = app.storage.load()
        state["inbox"]["garden"]["proposal"]["summary"] = "Bring a small plant to the workshop."
        state["inbox"]["booking"]["status"] = "dismissed"
        app.storage.save(state)

    skill, _ = app.agent.skills.mutate("create", {"markdown": (
        '---\nname: "Weekend planning"\ndescription: "Build a low-key weekend itinerary."\n'
        'when_to_use: "When the family calendar gets crowded."\ntools: []\ntags: ["Récurring weekend", "family"]\n'
        '---\n\n1. Call the café to check its opening hours.\n2. Gather the picnic blankets.\n'
    )})
    return skill["id"]


class ListSearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(folder.cleanup)
        storage = Storage(folder.name)
        config = read_config(ROOT / "config/connectors.json")
        config["brain"] = {"provider": "mock", "model": ""}
        cls.app = Application(storage, LocalCheckpoints(storage), config)
        cls.skill = seed_list_search(cls.app)
        cls.server = HTTPServer(("127.0.0.1", 0), cls.app)
        cls.addClassCleanup(cls.server.server_close)
        thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(cls.server.shutdown)

    def get(self, resource, **query):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request("GET", f"/api/{resource}?{urlencode(query, doseq=True)}")
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_optional_query_validates_each_resource(self):
        for resource in ("reminders", "inbox", "skills"):
            with self.subTest(resource=resource):
                self.assertEqual(self.get(resource)[0], 200)
                for query in ("", "  ", "x" * 201, ["a", "b"], ["", "a"], "\0"):
                    self.assertEqual(self.get(resource, q=query)[0], 400)
                for query in ("a", "日" * 200, " ☕ "):
                    self.assertEqual(self.get(resource, q=query)[0], 200)

    def test_reminders_searches_across_delivery_groups_and_local_due_text(self):
        _, result = self.get("reminders", q="CAFE")
        self.assertEqual([row["message"] for row in result["jobs"]],
                         ["Reserve the café table", "Call the café about the menu"])
        self.assertEqual(result["jobs"][0]["search_matches"]["title"][1], {"text": "café", "match": True})
        _, result = self.get("reminders", q="courtYard")
        self.assertIn("note", result["jobs"][0]["search_matches"])
        _, result = self.get("reminders", q="email")
        self.assertEqual(len(result["jobs"]), 1)
        self.assertIn("email", result["jobs"][0]["search_matches"])
        self.assertEqual(len(result["outbox"]), 1)
        _, result = self.get("reminders", q="JUN 15, 2030, 9:30 am")
        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(result["jobs"][0]["search_matches"]["due"],
                         [{"text": "Jun 15, 2030, 9:30 AM", "match": True}])
        _, result = self.get("reminders", q="itinerary")
        self.assertEqual((len(result["delivered"]), len(result["outbox"])), (1, 1))

    def test_inbox_searches_stored_mail_metadata_and_text_across_statuses(self):
        for query, ids in (("julia", ["garden"]), ("julia@example.test", ["garden"]), ("lea green", ["forward"]),
                           ("dinner copy", ["forward"]), ("CAFE", ["garden", "booking"]), ("community", ["garden"]),
                           ("purchase", ["receipt"]), ("arrive ten", ["booking"]), ("payment cleared", ["receipt"]),
                           ("receipt or order", ["receipt"]), ("<img src=x>", ["receipt"]), ("CAT_", [])):
            with self.subTest(query=query):
                _, result = self.get("inbox", q=query)
                self.assertEqual([row["id"] for row in result["cards"]], ids)
        _, result = self.get("inbox", q="cafe patio")
        row = result["cards"][0]
        self.assertEqual(row["search_matches"]["excerpt"][1], {"text": "café patio", "match": True})
        self.assertNotIn("mailbox", row)
        self.assertIn("approvals", result)

    def test_skills_searches_current_playbooks_and_hides_private_details_from_summaries(self):
        for query in ("weekend planning", "itinerary", "calendar gets", "recurring weekend", "cafe", "picnic blankets"):
            with self.subTest(query=query):
                _, result = self.get("skills", q=query)
                self.assertEqual([row["id"] for row in result["skills"]], [self.skill])
                row = result["skills"][0]
                self.assertIn("search_matches", row)
                self.assertNotIn("markdown", row)
                self.assertNotIn("content", row)
        _, result = self.get("skills", q="cafe")
        self.assertEqual(result["skills"][0]["search_matches"]["excerpt"][1], {"text": "café", "match": True})
        custom = self.app.agent.skills.detail(self.skill)
        self.assertEqual(custom["tags"], ["Récurring weekend", "family"])
        self.assertGreater(len(self.get("skills", q="dinner party")[1]["skills"]), 0)
