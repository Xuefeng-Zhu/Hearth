"""Exercise For you and Proactivity settings in Chromium with synthetic data."""

import argparse
import json
import runpy
import threading
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright

from hearth import approvals
from hearth.agent import tool_call
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import read_config
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage
from test_proactivity import offer

PREVIOUS = runpy.run_path(str(Path(__file__).with_name("run30-browser.py")))
CONTRAST = PREVIOUS["CONTRAST"]
choose = PREVIOUS["choose"]
FixtureGateway = PREVIOUS["FixtureGateway"]

BIRTHDAY = "Find a birthday gift"
DINNER = "Build the holiday shopping list"
BOOKING = "Prepare for the weekend train"


def fixture_completion(model, messages, tools, emit, **limits):
    if not tools:
        candidates = [
            {**offer("holiday-shopping", kind="events", source="memory:topics/thanksgiving.md",
                     label="Make an Excel shopping list", prompt="Make an Excel grocery list for the holiday dinner."),
             "title": DINNER, "why": "Grocery shopping is easier with the menu in one place.", "urgency": "soon"},
            {**offer("weekend-train", kind="travel", label="Draft a travel checklist",
                     prompt="Write a checklist for the weekend train."),
             "title": BOOKING, "why": "There’s time to collect the essentials before departure."},
            {**offer("birthday-plan", label="Prepare a gift message",
                     prompt="Send an email about birthday gift ideas, with approval."),
             "why": "A birthday is coming up, with time to plan something thoughtful."},
        ]
        return {"content": "```json\n" + json.dumps({"suggestions": candidates}, ensure_ascii=False) + "\n```"}
    if messages[-1]["role"] == "tool":
        return {"content": "The draft is ready for your approval."}
    return tool_call("send_email", {"to": ["sample@example.invalid"], "subject": "Birthday gift ideas",
                                   "text": "A book or a loose-leaf tea sampler could make a thoughtful gift."})


def verify(page, origin, width, theme, output, app):
    mobile = width == 390
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda event: errors.append(event.text) if event.type in {"error", "warning"} else None)
    response = page.goto(origin, wait_until="domcontentloaded")
    assert response.status == 200 and page.title() == "Hearth" and page.url == origin + "/"

    def capture(name, root):
        ratios = root.evaluate(CONTRAST)
        assert ratios and not [row for row in ratios if row["ratio"] + 0.005 < row["min"]], ratios
        assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
        page.screenshot(path=output / f"{name}-{width}-{theme}.png", animations="disabled")
        return min(row["ratio"] for row in ratios)

    section = page.get_by_role("region", name="For you")
    expect(section.get_by_role("heading", name="For you")).to_be_visible()
    expect(section.get_by_role("article")).to_have_count(3)
    home_contrast = capture("for-you", section)
    dinner = section.get_by_role("article", name=DINNER)
    dinner.get_by_role("button", name="Snooze").click()
    expect(dinner.get_by_role("button", name="1 day")).to_be_focused()
    page.keyboard.press("Escape")
    expect(dinner.get_by_role("button", name="Snooze")).to_be_focused()
    dinner.get_by_role("button", name="Snooze").click()
    expect(dinner.get_by_role("button", name="1 week")).to_be_visible()
    dinner.get_by_role("button", name="1 day").click()
    expect(section.get_by_role("status")).to_have_text("Snoozed for one day.")
    expect(dinner).to_have_count(0)

    travel = section.get_by_role("article", name=BOOKING)
    travel.get_by_role("button", name="Not interested in this kind").click()
    expect(travel).to_have_count(0)
    expect(section.get_by_role("status")).to_have_text("Muted travel & bookings.")

    page.reload(wait_until="domcontentloaded")
    expect(section.get_by_role("article")).to_have_count(1)
    section.get_by_role("article", name=BIRTHDAY).get_by_role("button", name="Do it").click()
    expect(page.get_by_role("heading", name="Chat", level=1)).to_be_visible()
    approval = page.locator(".automation-approval").filter(has_text="Send this email")
    expect(approval.get_by_text("Needs approval")).to_be_visible()
    expect(approval.get_by_role("button", name="Approve", exact=True)).to_be_enabled()
    assert not app.storage.load()["outbox"]

    choose(page, "Timeline", mobile)
    entries = page.locator('#timeline-view [data-kind="proactivity"] .timeline-title')
    expect(entries.filter(has_text="Suggestion shown")).to_have_count(3)
    expect(entries.filter(has_text="Suggestion acted on")).to_be_visible()

    choose(page, "Settings", mobile)
    page.get_by_role("button", name="Proactivity", exact=True).click()
    form = page.locator("#proactivity-settings-form")
    expect(form.get_by_label("Check every (minutes)")).to_have_value("120")
    expect(form.get_by_label("Email a daily digest")).not_to_be_checked()
    expect(form.get_by_text("Muted categories", exact=False)).to_contain_text("Travel & bookings")
    settings_contrast = capture("settings", form)
    form.get_by_label("Check every (minutes)").fill("90")
    form.get_by_label("Show suggestions on Home").uncheck()
    form.get_by_role("button", name="Save settings").click()
    expect(form.get_by_role("status")).to_have_text("Proactivity settings saved.")
    choose(page, "Home", mobile)
    expect(section).to_be_hidden()
    assert not errors, errors
    print(f"{width} {theme} passed. Minimum sampled text contrast {min(home_contrast, settings_contrast):.2f}:1.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--chromium")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.chromium)
        for width, height in ((390, 844), (1440, 1000)):
            for theme in ("light", "dark"):
                with TemporaryDirectory() as directory:
                    storage = Storage(directory)
                    config = read_config(ROOT / "config/connectors.json")
                    config["brain"] = {"provider": "mock", "model": ""}
                    app = Application(storage, LocalCheckpoints(storage), config, gateway=FixtureGateway())
                    app.agent.models = [{"provider": "test-brain", "model": "fixture"}]
                    approvals.settings(storage, {"send": "allow"})
                    with (
                        patch.object(app.gateway, "completion", side_effect=fixture_completion, create=True),
                        patch.object(app.agent, "side_summary", return_value="A birthday email draft awaits approval."),
                        patch.object(app.proactivity, "kick"),
                    ):
                        app.proactivity.save_settings({"quiet_start": "00:00", "quiet_end": "00:00"})
                        assert len(app.proactivity.tick(datetime.now(timezone.utc))["suggestions"]) == 3
                        with HTTPServer(("127.0.0.1", 0), app) as server:
                            worker = threading.Thread(target=server.serve_forever, daemon=True)
                            worker.start()
                            context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=theme,
                                                          is_mobile=width == 390, has_touch=width == 390)
                            try:
                                verify(context.new_page(), f"http://127.0.0.1:{server.server_port}", width, theme, args.output, app)
                            finally:
                                context.close()
                                server.shutdown()
                                worker.join()
        browser.close()


if __name__ == "__main__":
    main()
