import io
import json
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from hearth import browserbase, router
from hearth.agent import tool_call
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import ConnectorError, Gateway, read_config
from hearth.server import Application
from hearth.storage import HearthError, ROOT, Storage

PAGE = "https://fly.io/hacksgiving/"
SESSION = "test-session"
SIGNED_URL = "wss://connect.browserbase.com/?sessionId=test-session&signature=fixture-only"


class BrowserGateway(Gateway):
    def __init__(self, *, connected=True):
        self.calls = []
        self.connected = connected
        self.session = {"id": SESSION, "connectUrl": SIGNED_URL}

    def request(self, path, body, headers, timeout, *, method=None):
        self.calls.append((path, body))
        if not self.connected:
            raise ConnectorError("upstream details", 404)
        data = {
            "browserbase/" + browserbase.TEST_PATH: [],
            "browserbase/v1/fetch": {"statusCode": 200, "content": "# Hacksgiving"},
            "browserbase/v1/search": {"results": [{"url": PAGE, "title": "Hacksgiving", "excerpts": ["Community event"]}]},
            "browserbase/v1/sessions": self.session,
            f"browserbase/v1/sessions/{SESSION}": {"status": "REQUEST_RELEASE"},
        }[path]
        return io.BytesIO(json.dumps(data).encode())


class BrowsingTest(unittest.TestCase):
    def test_router_reads_specific_pages_and_routes_live_or_write_requests(self):
        samples = {
            f"Open and summarize {PAGE}": "browse_fetch",
            "Check fly.io/hacksgiving/ and take a screenshot": "browse_session",
            f"Scroll down on {PAGE}": "session_plan",
            "Check the website’s live availability": "find_page",
            "Search with Browserbase for Fly Hacksgiving": "browse_search",
            f"Open {PAGE} and submit the form": "approval",
            f"Sign in at {PAGE}": "approval",
            f"Buy tickets at {PAGE}": "approval",
            f"Post the update at {PAGE}": "approval",
            "Search for Seattle weather": None,
            "Read topics/thanksgiving.md": None,
            "Send an email to reader@example.com": None,
        }
        for prompt, tool in samples.items():
            with self.subTest(prompt=prompt):
                intent = router.browse_intent(prompt)
                self.assertEqual(intent and intent[0], tool)
                if tool:
                    self.assertEqual(router.classify(prompt), "tool")

    def test_fetch_search_and_test_use_credential_free_gateway_paths(self):
        gateway = BrowserGateway()
        browser = browserbase.Browserbase(gateway)
        browser.test()
        self.assertEqual(browser.fetch(PAGE)["markdown"], "# Hacksgiving")
        self.assertEqual(browser.search("Hacksgiving")["results"][0]["snippet"], "Community event")
        self.assertEqual(gateway.calls, [
            ("browserbase/" + browserbase.TEST_PATH, None),
            ("browserbase/v1/fetch", {"url": PAGE, "format": "markdown", "allowRedirects": True}),
            ("browserbase/v1/search", {"query": "Hacksgiving", "numResults": 5, "excerpts": True}),
        ])

    def test_releases_session_on_page_error(self):
        gateway = BrowserGateway()
        browser = browserbase.Browserbase(gateway)
        events = []
        with patch.object(browser, "drive", AsyncMock(side_effect=HearthError("Navigation failed."))):
            result, image = browser.session(PAGE, [], lambda name, data: events.append((name, data)))
        self.assertEqual(result, {"error": "Navigation failed.", "session_id": SESSION})
        self.assertIsNone(image)
        self.assertEqual(gateway.calls, [
            ("browserbase/v1/sessions", {"timeout": 90}),
            (f"browserbase/v1/sessions/{SESSION}", {"status": "REQUEST_RELEASE"}),
        ])
        self.assertEqual([name for name, _ in events], ["browse_active", "browse_finished"])
        self.assertEqual(events[0][1]["id"], events[1][1]["id"])
        self.assertNotIn(SIGNED_URL, str(events))

    def test_cdp_failure_releases_before_fetching(self):
        gateway = BrowserGateway()
        browser = browserbase.Browserbase(gateway)
        with patch.object(browser, "drive", AsyncMock(side_effect=browserbase.CdpUnavailable())):
            result, image = browser.session(PAGE, [], lambda *_: None)
        self.assertEqual(result["markdown"], "# Hacksgiving")
        self.assertIn("Used Fetch", result["fallback"])
        self.assertEqual(result["session_id"], SESSION)
        self.assertIsNone(image)
        self.assertEqual([path for path, _ in gateway.calls], [
            "browserbase/v1/sessions", f"browserbase/v1/sessions/{SESSION}", "browserbase/v1/fetch",
        ])
        self.assertIsNone(browserbase.service_url("wss://connect.browserbase.com/?apiKey=secret", "wss", cdp=True))

    def make_app(self, root, gateway, *, mock=False, allowed=True):
        storage = Storage(root)
        config = read_config(ROOT / "config/connectors.json")
        config["browsing"] = {"allowed": allowed}
        config["brain"] = {"provider": "mock" if mock else "auto", "model": ""}
        app = Application(storage, LocalCheckpoints(storage), config, gateway=gateway)
        if not mock:
            app.connections.selected["huggingface"] = "fake-model"
            app.reload_agent()
        return app

    @staticmethod
    def collect(queue):
        events = []
        while (event := queue.get(timeout=8)) is not None:
            events.append(event)
        return events

    def test_missing_connection_has_clear_instructions_in_reply_and_card(self):
        with tempfile.TemporaryDirectory() as root:
            gateway = BrowserGateway(connected=False)
            app = self.make_app(root, gateway)
            app.connections.test("browserbase")
            report = app.connections.report()["providers"]["browserbase"]
            self.assertEqual(report["test_detail"], browserbase.NOT_CONNECTED)
            self.assertEqual(report["status"], "not_set_up")
            self.assertTrue(report["can_test"])
            events = self.collect(app.enqueue("main", f"Open {PAGE}"))
            self.assertEqual(dict(events)["done"]["message"]["content"], browserbase.NOT_CONNECTED)
            self.assertEqual(gateway.calls[-1][0], "browserbase/v1/fetch")
            browse = next(row for row in app.timeline_info()["entries"] if row["kind"] == "browse")
            self.assertEqual(browse["data"]["url"], PAGE)
            self.assertIn("duration_ms", browse["data"])
            self.assertIsNone(browse["data"]["session_id"])

    def test_mock_screenshot_is_in_saved_reply_and_toggle_stops_browsing(self):
        with tempfile.TemporaryDirectory() as root:
            gateway = BrowserGateway()
            app = self.make_app(root, gateway, mock=True)
            prompt = f"Open {PAGE} and take a screenshot"
            with patch("hearth.browserbase.time.sleep"):
                events = self.collect(app.enqueue("main", prompt))
            self.assertTrue(dict(events)["browse_active"]["mock"])
            message = dict(events)["done"]["message"]
            attachment = message["browse_images"][0]
            self.assertEqual(browserbase.screenshot_path(app.storage, attachment["name"]).read_bytes(),
                             browserbase.demo_image())
            self.assertEqual(app.info()["messages"][-1]["browse_images"], [attachment])
            self.assertEqual(gateway.calls, [])
            app.connections.save_preferences("browsing", {"allowed": False})
            app.reload_agent()
            events = self.collect(app.enqueue("main", prompt))
            self.assertEqual(dict(events)["done"]["message"]["content"], browserbase.DISABLED)
            self.assertNotIn("browse_active", dict(events))

    def test_browser_action_executes_once_only_after_approval(self):
        class ActionGateway(BrowserGateway):
            def completion(self, config, messages, tools, emit):
                if not any(message["role"] == "tool" for message in messages):
                    return tool_call("browse_session", {"url": PAGE,
                                     "steps": [{"action": "click", "target": "#submit"}]})
                return {"role": "assistant", "content": "The form is ready to review."}

        with tempfile.TemporaryDirectory() as root:
            gateway = ActionGateway()
            app = self.make_app(root, gateway)
            events = self.collect(app.enqueue("main", f"Submit the form at {PAGE}"))
            action = dict(events)["action"]
            self.assertEqual(action["status"], "pending")
            self.assertEqual(gateway.calls, [])
            with patch.object(app.agent.browser, "drive", AsyncMock(return_value=(
                {"url": PAGE, "text": "Form received"}, browserbase.demo_image(),
            ))) as drive:
                approved = self.collect(app.enqueue("main", "", approval=action["id"]))
                self.assertTrue(drive.call_args.kwargs["approved"])
            self.assertIn("browse_images", dict(approved)["done"]["message"])
            self.assertEqual(app.storage.load()["actions"][action["id"]]["status"], "complete")
            calls = gateway.calls.copy()
            repeat = self.collect(app.enqueue("main", "", approval=action["id"]))
            self.assertIn("no longer awaiting approval", dict(repeat)["error"]["message"])
            self.assertEqual(gateway.calls, calls)
