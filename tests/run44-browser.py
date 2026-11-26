"""Exercise event automation surfaces in WebKit with fictional data."""

import argparse
import threading
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

from hearth import scheduler
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import read_config
from hearth.server import Application
from hearth.storage import ROOT, Storage
from test_event_automations import FEED, REMINDER

tools = import_module("run43-browser")


def exercise(browser, output, width, height):
    with TemporaryDirectory() as directory:
        storage = Storage(directory)
        config = read_config(ROOT / "config/connectors.json")
        config["brain"] = {"provider": "mock", "model": ""}
        app = Application(storage, LocalCheckpoints(storage), config)
        with tools.FixtureServer(("127.0.0.1", 0), app) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            context = browser.new_context(viewport={"width": width, "height": height}, is_mobile=True,
                                          has_touch=True, color_scheme="dark")
            try:
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                base = f"http://127.0.0.1:{server.server_port}"
                suffix = f"{width}x{height}-dark.png"
                response = page.goto(f"{base}/#settings/automations")
                assert response.status == 200, (response.status, response.text())
                page.get_by_role("button", name="New automation").click()
                dialog = page.get_by_role("dialog", name="New automation")
                expect(dialog).to_be_visible()
                dialog.get_by_label("Name", exact=True).fill("Greenhouse alarm")
                dialog.get_by_label("When", exact=True).select_option("reminder")
                dialog.get_by_label("Action type").select_option("reminder")
                dialog.get_by_label("Reminder text").fill(REMINDER["message"])
                dialog.get_by_role("button", name="Add action").click()
                dialog.get_by_label("Action type").last.select_option("feed_card")
                dialog.get_by_label("Card title").fill(FEED["title"])
                dialog.get_by_label("Topic").fill(FEED["topic"])
                tools.check(page, "#automation-dialog")
                page.screenshot(path=output / f"editor-{suffix}")
                dialog.get_by_role("button", name="Save automation").click()
                expect(dialog).to_have_count(0)

                card = page.locator(".event-automation-card").filter(has_text="Greenhouse alarm")
                expect(card.get_by_text("No runs yet", exact=True)).to_be_visible()
                card.get_by_role("button", name="Pause Greenhouse alarm").click()
                expect(card.get_by_text("Paused", exact=True)).to_be_visible()
                card.get_by_role("button", name="Enable Greenhouse alarm").click()
                expect(card.get_by_text("Enabled", exact=True)).to_be_visible()
                card.get_by_role("button", name="Edit", exact=True).click()
                editor = page.get_by_role("dialog", name="Edit automation")
                expect(editor.get_by_label("Reminder text")).to_have_value(REMINDER["message"])
                editor.get_by_label("Name", exact=True).fill("Greenhouse follow-up")
                editor.get_by_role("button", name="Save automation").click()
                card = page.locator(".event-automation-card").filter(has_text="Greenhouse follow-up")
                expect(card).to_be_visible()

                now = datetime.now(timezone.utc)
                with storage.lock():
                    state = storage.load()
                    scheduler.add_job(state, "Water the greenhouse", now, cron="* * * * *")
                    storage.save(state)
                with storage.lock():
                    clock = datetime.fromisoformat(storage.load()["jobs"][0]["next_at"])
                scheduler.run_due(storage, clock)
                app.event_runner.tick(clock)
                expect(card.get_by_text("Completed", exact=True).first).to_be_visible(timeout=10_000)
                card.locator(".event-run-history summary").click()
                expect(card.get_by_text("Feed card added.", exact=False)).to_be_visible()
                tools.check(page, "#settings-automations")
                card.scroll_into_view_if_needed()
                page.screenshot(path=output / f"settings-history-{suffix}")

                tools.go(page, "timeline")
                item = page.locator(".timeline-entry").filter(has_text="Greenhouse follow-up")
                expect(item).to_have_count(1)
                item.get_by_role("button", name="Undo", exact=True).click()
                expect(item.get_by_text("Remove this run’s Feed cards", exact=False)).to_be_visible()
                page.screenshot(path=output / f"timeline-undo-{suffix}")
                item.get_by_role("button", name="Undo change", exact=True).click()
                expect(item.get_by_text("Undone", exact=True)).to_be_visible()

                page.goto(f"{base}/#settings/automations")
                card.get_by_role("button", name="Delete", exact=True).click()
                approval = page.locator("#event-automation-approval")
                expect(approval.get_by_text("Needs approval")).to_be_visible()
                approval.get_by_role("button", name="Approve").click()
                expect(card).to_have_count(0)
                approval.get_by_role("button", name="Undo").click()
                expect(card).to_be_visible()

                tools.go(page, "chat")
                page.locator("#message").fill("When Mira@example.invalid emails me, summarize it and remind me tomorrow")
                page.locator("#send").click()
                proposal = page.locator('[data-surface="chat"]').filter(has_text="Create automation")
                expect(proposal.get_by_role("button", name="Confirm")).to_be_visible()
                assert len(storage.load()["event_automations"]) == 1
                tools.check(page, "#chat-view .automation-approval")
                expect(page.locator("#send")).to_be_enabled()
                proposal.evaluate('element => element.scrollIntoView({block: "center"})')
                page.screenshot(path=output / f"chat-approval-{suffix}")
                proposal.get_by_role("button", name="Confirm").click()
                expect(proposal.get_by_text("Created Email follow-up.")).to_be_visible()
                assert len(storage.load()["event_automations"]) == 2
                assert not errors, errors
                print(f"{width}×{height} settings, editing, run history, Timeline Undo, deletion and chat confirmation")
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
