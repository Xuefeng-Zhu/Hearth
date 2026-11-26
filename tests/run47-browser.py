"""Check Ideas and Goals in mobile WebKit with fictional sources and a fake brain."""

import argparse
import re
import threading
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

from hearth import goals, scheduler
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import read_config
from hearth.server import Application
from hearth.storage import ROOT, Storage, iso
from test_ideas_goals import FakeBrain, idea

qa = import_module("run43-browser")


def capture(page, path, errors):
    start = len(errors)
    page.screenshot(caret="initial", path=path)
    # Playwright WebKit inserts an empty stylesheet to sync animations before each screenshot.
    errors[start:] = [error for error in errors[start:]
                      if not error.startswith("error: Refused to apply a stylesheet because its hash")]


def exercise(browser, output, width, height):
    now = datetime.now(timezone.utc)
    with TemporaryDirectory() as directory:
        storage = Storage(directory)
        config = read_config(ROOT / "config/connectors.json")
        config["brain"] = {"provider": "mock", "model": ""}
        brain = FakeBrain()
        app = Application(storage, LocalCheckpoints(storage), config, gateway=brain)
        app.agent.models = [{"provider": "test-brain", "model": "fixture"}]
        with storage.lock():
            state = storage.load()
            state["proactivity_settings"] = {"quiet_start": "00:00", "quiet_end": "00:00"}
            scheduler.add_job(state, "Print seed labels", clock=now, at=iso(now + timedelta(days=2)))
            storage.save(state)
            source = app.threads.append("main", "user", "We are planning a seed swap and a toy observatory.")
        goal = goals.mutate(storage, "goal_create", {"title": "Open the seed library",
                            "target_date": (now + timedelta(days=12)).date().isoformat(),
                            "checkin": {"cadence": "weekly", "day": 1, "time": "09:30"}}, clock=now)["goal"]
        goals.mutate(storage, "goal_checkin", {"id": goal["id"], "progress": 35, "note": "Seed drawers assembled."}, clock=now)
        source_id = f"chat:main/{source['id']}"
        brain.results = [
            idea("slides", source_id, "Toy observatory slides"),
            idea("chat", source_id, "Seed-swap plan"),
            idea("reminder", source_id, "Pack seed trays", detail="Get the trays ready before the seed swap.", at=iso(now + timedelta(days=1))),
            {"kind": "goal", "id": goal["id"], "text": "Label ten seed envelopes."},
        ]
        assert app.ideas.tick(now) == "complete"
        app.agent.models = [{"provider": "mock", "model": "hearth-demo"}]
        with qa.FixtureServer(("127.0.0.1", 0), app) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            context = browser.new_context(viewport={"width": width, "height": height}, is_mobile=True,
                                          has_touch=True, color_scheme="dark")
            try:
                page = context.new_page()
                errors = []
                http_errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("console", lambda message: errors.append(f"{message.type}: {message.text}") if message.type in ("error", "warning") else None)
                page.on("response", lambda response: http_errors.append(
                    f"{response.status} {response.request.method} {response.url}") if response.status >= 400 else None)
                base = f"http://127.0.0.1:{server.server_port}"
                response = page.goto(base)
                assert (response.status == 200 and page.url.startswith(base + "/") and "Hearth" in page.title()), (response.status, page.url, page.title())
                suffix = f"{width}x{height}-dark.png"

                qa.go(page, "home")
                feed = page.get_by_role("region", name="Ideas")
                reminders_idea = feed.get_by_role("article", name="Pack seed trays")
                expect(reminders_idea).to_be_visible()
                reminders_idea.scroll_into_view_if_needed()
                qa.check(page, ".idea-strip")
                capture(page, output / f"ideas-{suffix}", errors)
                reminders_idea.get_by_role("button", name="Review reminder").click()
                approval = feed.locator(".automation-approval")
                expect(approval.get_by_text("Needs approval")).to_be_visible()
                assert len(storage.load()["jobs"]) == 2
                approval.evaluate('element => element.scrollIntoView({block: "center"})')
                qa.check(page, ".idea-approval")
                capture(page, output / f"idea-approval-{suffix}", errors)
                approval.get_by_role("button", name="Approve", exact=True).click()
                expect(approval.get_by_text("Reminder scheduled", exact=True)).to_be_visible()
                assert len(storage.load()["jobs"]) == 3
                feed.get_by_role("article", name="Seed-swap plan").get_by_role("button", name="Not interested").click()
                expect(feed.get_by_role("article", name="Seed-swap plan")).to_have_count(0)
                feed.get_by_role("button", name="Draft in Chat").click()
                expect(page.locator("#message")).to_have_value(re.compile("Create a slide deck"))
                assert "toy observatory" in page.locator("#message").input_value().lower()

                qa.go(page, "home")
                panel = page.locator("[data-panel=goals]")
                entry = panel.locator(".goal-row").filter(has_text="Open the seed library")
                expect(entry.get_by_text("35%")).to_be_visible()
                expect(entry.get_by_text("Label ten seed envelopes.")).to_be_visible()
                panel.evaluate('element => element.scrollIntoView({block: "center"})')
                qa.check(page, ".home-card-goals")
                capture(page, output / f"goals-{suffix}", errors)
                entry.get_by_role("button", name="Check in").click()
                dialog = page.get_by_role("dialog", name="Check in · Open the seed library")
                dialog.get_by_label("Progress (%)").fill("55")
                dialog.get_by_label("Check-in note").fill("More labels printed.")
                qa.check(page, "#goal-dialog")
                dialog.get_by_role("button", name="Save check-in").click()
                expect(entry.get_by_text("55%")).to_be_visible()

                panel.get_by_role("button", name="New goal").click()
                dialog = page.get_by_role("dialog", name="New goal")
                dialog.get_by_label("Title", exact=True).fill("Host the seed swap")
                dialog.get_by_label("Target date").fill((now + timedelta(days=8)).date().isoformat())
                dialog.get_by_label("Check-in reminder").select_option("weekly")
                dialog.get_by_label("Day of week").select_option("5")
                dialog.get_by_text("Linked reminders and tasks", exact=True).click()
                dialog.get_by_label("Print seed labels · reminder").check()
                qa.check(page, "#goal-dialog")
                capture(page, output / f"goal-editor-{suffix}", errors)
                dialog.get_by_role("button", name="Create goal").click()
                goal_approval = panel.locator(".goal-approval")
                expect(goal_approval.get_by_text("Needs approval")).to_be_visible()
                assert len(goals.list_goals(storage.load())) == 1
                goal_approval.get_by_role("button", name="Approve").click()
                linked = panel.locator(".goal-row").filter(has_text="Host the seed swap")
                expect(linked.get_by_text("0 of 1 linked items complete")).to_be_visible()
                linked.get_by_role("button", name="Edit", exact=True).click()
                editor = page.get_by_role("dialog", name="Edit goal")
                editor.get_by_label("Title", exact=True).fill("Host the spring seed swap")
                editor.get_by_role("button", name="Save goal").click()
                linked = panel.locator(".goal-row").filter(has_text="Host the spring seed swap")
                expect(linked).to_be_visible()
                linked.get_by_role("button", name="Delete Host the spring seed swap").click()
                goal_approval.get_by_role("button", name="Approve").click()
                expect(linked).to_have_count(0)

                qa.go(page, "timeline")
                entry = page.locator(".timeline-entry").filter(has_text="Deleted goal · Host the spring seed swap")
                entry.get_by_role("button", name="Undo", exact=True).click()
                expect(entry.get_by_text("Undo this goal change?")).to_be_visible()
                entry.evaluate('element => element.scrollIntoView({block: "center"})')
                capture(page, output / f"timeline-undo-{suffix}", errors)
                entry.get_by_role("button", name="Undo change", exact=True).click()
                expect(entry.get_by_text("Undone", exact=True)).to_be_visible()

                qa.go(page, "home")
                expect(panel.get_by_role("heading", name="Host the spring seed swap", exact=True)).to_be_visible()
                page.get_by_role("button", name="Edit layout").click()
                controls = panel.locator(".home-order-tools")
                order = page.locator("#home-grid > article")
                before = order.evaluate_all("(panels) => panels.map(panel => panel.dataset.panel)")
                prior = before[before.index("goals") - 1]
                controls.get_by_role("button", name="Move Goals up").click()
                expect(page.locator(f'[data-panel=goals] + [data-panel="{prior}"]')).to_be_visible()
                controls.get_by_role("button", name="Remove Goals").click()
                expect(panel).to_have_count(0)
                page.get_by_role("listitem").filter(has_text="Goals").get_by_role("button", name="Restore").click()
                expect(panel).to_be_visible()
                qa.go(page, "chat")
                page.locator("#message").fill("Create a goal Assemble the toy telescope by " +
                                              (now + timedelta(days=10)).date().isoformat())
                page.locator("#send").click()
                chat_approval = page.locator('.automation-approval[data-surface="chat"]').filter(has_text="Assemble")
                expect(chat_approval.get_by_role("button", name="Approve")).to_be_visible()
                assert not errors and not http_errors, (errors, http_errors)
                print(f"{width}×{height} Feed, drafts, approvals, goals, layout, and Timeline Undo")
            finally:
                context.close()
                server.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.webkit.launch()
        for width, height in ((390, 844), (375, 667)):
            exercise(browser, args.output, width, height)
