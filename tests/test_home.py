import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from hearth import home, panels
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import read_config
from hearth.server import Application
from hearth.storage import HearthError, ROOT, Storage, iso

STAMP = datetime(2026, 11, 25, 14, tzinfo=timezone.utc)


def spec(kind="stat", value=42, **changes):
    return {"title": "A panel", "kind": kind, "source": {"type": "static", "value": value},
            "refresh_minutes": 15, **changes}


class HomeTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = Storage(Path(directory.name) / "data")
        self.app = self.open_app()

    def open_app(self):
        config = read_config(ROOT / "config/connectors.json")
        config["brain"] = {"provider": "mock", "model": ""}
        return Application(self.storage, LocalCheckpoints(self.storage), config)

    def execute(self, name, **arguments):
        with self.storage.lock():
            return self.app.agent.execute(name, arguments)

    def test_tool_validation_and_atomic_batch(self):
        for bad in [
            spec(title=""), spec("unknown"), spec(refresh_minutes=14), spec(refresh_minutes=1441),
            spec(refresh_minutes=True), spec(refresh_minutes=15.5), spec("countdown", "tomorrow"),
            spec("countdown", "2026-11-26T12:30:00"), spec("stat", float("inf")), spec("stat", True),
            spec("checklist", [{"text": "A", "checked": "false"}]), spec("list", ["\ud800"]),
            spec(source={"type": "brain"}), spec(source={"type": "connector", "provider": "closed", "path": "/items"}),
            spec("web-summary", source={"type": "url", "url": "http://127.0.0.1/debug"}),
            spec("web-summary", source={"type": "url", "url": "https://example.com/?api_key=secret"}),
            spec("note", source={"type": "url", "url": "https://example.com"}),
        ]:
            with self.subTest(bad=bad), self.assertRaises(HearthError):
                self.execute("create_panel", panels=[spec(), bad])
        self.assertEqual(self.storage.load().get("panels"), None)
        self.assertEqual(self.execute("create_panel", **spec(refresh_minutes=1440))["action"]["status"], "complete")

    def test_batch_approval_and_replay(self):
        specs = [spec(title=f"Panel {index}") for index in range(4)]
        result = self.execute("create_panel", panels=specs)["action"]
        self.assertEqual(result["status"], "pending")
        self.assertFalse(self.storage.load().get("panels"))
        self.assertEqual(self.app.agent.approve(result["id"])["status"], "complete")
        self.assertEqual(self.app.agent.approve(result["id"])["panel_titles"], [item["title"] for item in specs])
        self.assertEqual(len(self.storage.load()["panels"]), 4)

    def test_run_due_preserves_value_and_respects_failed_attempt_interval(self):
        row = self.execute("create_panel", **spec(source={"type": "brain", "query": "Count notes"}))["panels"][0]
        identity = row["id"]
        after = STAMP + timedelta(minutes=15)
        with patch("hearth.home.weather_value", return_value=(home.DEFAULT_PLACE, {"temperature": 48, "code": 3})):
            with patch("hearth.panels.read_source", return_value=12) as read:
                self.assertEqual(self.app.home.run_due(STAMP), 2)
                self.assertEqual(self.app.home.run_due(after - timedelta(seconds=1)), 0)
                read.assert_called_once()
            with patch("hearth.panels.read_source", side_effect=HearthError("Provider unavailable.")) as read:
                self.assertEqual(self.app.home.run_due(after), 1)
                self.assertEqual(self.app.home.run_due(after + timedelta(seconds=1)), 0)
                read.assert_called_once()
            restarted = self.open_app()
            saved = self.storage.load()["panels"][identity]
            self.assertEqual((saved["value"], saved["updated_at"], saved["attempted_at"], saved["error"]),
                             (12, iso(STAMP), iso(after), "Provider unavailable."))
            with patch("hearth.panels.read_source", return_value=20):
                current, refreshed = restarted.home.panels.refresh(identity, clock=after + timedelta(seconds=5))
            self.assertTrue(refreshed)
            self.assertEqual((current["value"], current["error"]), (20, None))

    def test_tick_refreshes_panels_and_weather(self):
        result = self.execute("create_panel", **spec(source={"type": "brain", "query": "Count notes"}))
        with patch("hearth.home.weather_value", return_value=(home.DEFAULT_PLACE, {"temperature": 48, "code": 3})), \
                patch("hearth.panels.read_source", return_value=5):
            data = self.app.scheduler_tick()
        self.assertEqual(data["panels_refreshed"], 2)
        self.assertEqual(self.app.home.snapshot()["panels"][result["panels"][0]["id"]]["value"], 5)

    def test_refresh_from_old_revision_cannot_overwrite_edit(self):
        row = self.execute("create_panel", **spec(source={"type": "brain", "query": "Count notes"}))["panels"][0]
        identity = row["id"]
        entered, finish = threading.Event(), threading.Event()
        result = []

        def read(*_):
            entered.set()
            finish.wait(3)
            return 10

        with patch("hearth.panels.read_source", side_effect=read):
            thread = threading.Thread(target=lambda: result.append(self.app.home.panels.refresh(identity)))
            thread.start()
            try:
                self.assertTrue(entered.wait(3))
                self.assertFalse(self.app.home.panels.refresh(identity)[1])
                self.execute("update_panel", id=identity, source={"type": "static", "value": 9})
            finally:
                finish.set()
                thread.join(3)
        self.assertFalse(result[0][1])
        self.assertEqual(self.storage.load()["panels"][identity]["value"], 9)

    def test_layout_checklist_and_side_chat_persist(self):
        with patch("hearth.agent.time.sleep"):
            self.app.agent.chat(panels.MOCK_DEMO, lambda *_: None)
            self.app.agent.chat(panels.MOCK_DEMO, lambda *_: None)
        state = self.storage.load()
        saved = list(state["panels"].values())
        self.assertEqual([row["title"] for row in saved], ["Thanksgiving countdown", "Shopping list"])
        row = saved[1]
        identity = row["id"]
        self.app.home.toggle({"id": identity, "index": 1, "checked": True, "revision": row["revision"]})
        with self.assertRaisesRegex(HearthError, "changed"):
            self.app.home.toggle({"id": identity, "index": 1, "checked": False, "revision": row["revision"]})
        self.app.home.adjust({"id": identity, "operation": "move", "target": "today", "position": "before"})
        self.app.home.adjust({"id": identity, "operation": "hide"})
        renamed = self.execute("update_panel", id=identity, title="Thanksgiving shopping")
        self.assertEqual(renamed["action"]["panel_titles"], ["Thanksgiving shopping"])
        self.app = self.open_app()
        snapshot = self.app.home.snapshot()
        self.assertEqual(snapshot["layout"]["order"][0], identity)
        self.assertIn(identity, snapshot["layout"]["hidden"])
        self.assertTrue(snapshot["panels"][identity]["value"][1]["checked"])
        self.app.home.adjust({"id": identity, "operation": "restore"})
        thread = self.app.home.panel_chat(identity)
        self.assertEqual(thread["title"], "About Thanksgiving shopping")
        with patch("hearth.agent.time.sleep"):
            self.app.agent.chat("What should I know about this panel?", lambda *_: None, thread["id"])
        with self.storage.lock():
            self.assertIn("Cranberries", self.app.threads.messages(thread["id"])[-1]["content"])
        self.execute("delete_panel", id=identity)
        self.assertNotIn(identity, self.app.home.snapshot()["layout"]["order"])

    def test_connector_get_and_public_url_source(self):
        connected = {"github": {"provider": "github", "connection_id": "example"}}
        connector = spec(source={"type": "connector", "provider": "github", "path": "/repos/owner/name",
                                 "pointer": "/items/0/week~1end"})
        with patch.object(self.app.agent, "gateway_connections", connected):
            row = self.execute("create_panel", **connector)["panels"][0]
            with patch("hearth.panels.gateway_read", return_value={"status": 200, "data": {"items": [{"week/end": 8}]}}) as read:
                self.assertEqual(self.app.home.panels.refresh(row["id"])[0]["value"], 8)
                read.assert_called_once_with(self.app.gateway, connected["github"], "repos/owner/name")
            with self.assertRaises(HearthError):
                self.execute("create_panel", **spec(source={"type": "connector", "provider": "github",
                                                           "path": "https://example.com/data"}))
        failed, _ = self.app.home.panels.refresh(row["id"])
        self.assertEqual(failed["value"], 8)
        self.assertIn("disconnected", failed["error"])
        source = self.execute("create_panel", **spec("web-summary", source={"type": "url", "url": "https://example.com"}))["panels"][0]
        with patch("hearth.panels.public_page", return_value="Open on Friday. Booking is available. Bring identification."):
            result, _ = self.app.home.panels.refresh(source["id"])
        self.assertIn("Booking is available", result["value"])

    def test_public_page_checks_resolved_ip_before_connecting(self):
        addresses = [(2, 1, 6, "", ("127.0.0.1", 443))]
        with patch("hearth.panels.socket.getaddrinfo", return_value=addresses), patch("hearth.panels.HTTPSConnection") as connect:
            with self.assertRaisesRegex(HearthError, "public address"):
                panels.public_page("https://example.com")
            connect.assert_not_called()

    def test_weather_failure_retains_forecast_and_retries_sooner(self):
        value = {"temperature": 48, "code": 3}
        with patch("hearth.home.weather_value", return_value=(home.DEFAULT_PLACE, value)):
            self.assertTrue(self.app.home.refresh_weather(STAMP))
        failed_at = STAMP + timedelta(minutes=30)
        with patch("hearth.home.weather_value", side_effect=OSError):
            self.assertTrue(self.app.home.refresh_weather(failed_at, due=True))
        saved = self.app.home.snapshot()["builtin"]["weather"]
        self.assertEqual((saved["value"], saved["updated_at"]), (value, iso(STAMP)))
        self.assertIsNotNone(saved["error"])
        with patch("hearth.home.weather_value", return_value=(home.DEFAULT_PLACE, value)) as request:
            self.assertFalse(self.app.home.refresh_weather(failed_at + timedelta(minutes=4), due=True))
            request.assert_not_called()
            self.assertTrue(self.app.home.refresh_weather(failed_at + timedelta(minutes=5), due=True))
        self.assertIsNone(self.app.home.settings()["error"])

    def test_weather_location_persists_and_uses_pacific_clock(self):
        with patch.object(self.app.home, "kick"):
            self.app.home.save_settings({"location": "Seattle, WA"})
        matches = {"results": [{"name": "Seattle", "admin1": "Washington", "country": "United States",
                                "latitude": 47.6, "longitude": -122.3}]}
        forecast = {"current": {"temperature_2m": 51.1, "weather_code": 2}}
        with patch("hearth.home.open_meteo", side_effect=[matches, forecast]) as meteo:
            self.assertTrue(self.app.home.refresh_weather(STAMP))
            self.assertEqual(meteo.call_args_list[0].args[2]["name"], "Seattle, WA")
            self.assertEqual(meteo.call_args_list[1].args[2]["timezone"], "America/Los_Angeles")
        snapshot = self.open_app().home.snapshot(STAMP)
        self.assertEqual(snapshot["builtin"]["weather"]["value"], {"temperature": 51, "code": 2})
        self.assertEqual(snapshot["builtin"]["weather"]["location"], "Seattle, WA")
        self.assertEqual(snapshot["clock_zone"], "America/Los_Angeles")
