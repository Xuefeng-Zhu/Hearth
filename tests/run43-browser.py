"""Exercise the Memory review approval flow in WebKit with fictional data."""

import argparse
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import read_config
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage
from test_memory_review import FACT, FRIDAY, MONDAY, FakeGateway, fixture

CONTRAST = "function " + (ROOT / "tests/contrast-pairs.mjs").read_text().split("export function ", 1)[1]


class FixtureServer(HTTPServer):
    handle_error = ThreadingHTTPServer.handle_error


def check(page, selector):
    failures = page.evaluate("""selector => {
      const scope = document.querySelector(selector);
      const visible = el => el.getClientRects().length && !el.closest('[hidden]');
      const controls = [...scope.querySelectorAll('button, input, select')]
        .filter(el => visible(el) && !el.disabled)
        .map(el => el.type === 'checkbox' ? el.labels[0] : el);
      return {
        overflow: [document.documentElement, scope, ...scope.querySelectorAll('article, .memory-review-list')]
          .filter(el => visible(el) && el.scrollWidth > el.clientWidth + 1)
          .map(el => el.id || el.className),
        small: controls.filter(el => {
          const rect = el.getBoundingClientRect();
          return Math.min(rect.width, rect.height) < 43.5;
        }).map(el => el.textContent.trim() || el.id),
      };
    }""", selector)
    assert not any(failures.values()), failures
    scoped = CONTRAST.replace("const scope = modal || document.body;", f'const scope = document.querySelector("{selector}");')
    pairs = page.evaluate(f"({scoped})", {"dark": True, "allControls": True})
    failures = [pair for pair in pairs if pair["ratio"] + 0.005 < pair["threshold"]]
    assert pairs and not failures, failures
    print(selector, len(pairs), "AA contrast samples")


def go(page, view):
    page.locator("#open-menu").click()
    page.locator(f'#workspace-drawer [data-view="{view}"]').click()
    expect(page.locator(f"#{view}-view")).to_be_visible()


def exercise(browser, output, width, height):
    with TemporaryDirectory() as path:
        storage = Storage(path)
        fixture(storage)
        with storage.lock():
            state = storage.load()
            state["proactivity_settings"] = {"quiet_start": "00:00", "quiet_end": "00:00"}
            storage.save(state)
        config = read_config(ROOT / "config/connectors.json")
        config["brain"] = {"provider": "mock", "model": ""}
        app = Application(storage, LocalCheckpoints(storage), config, gateway=FakeGateway())
        with FixtureServer(("127.0.0.1", 0), app) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            context = browser.new_context(viewport={"width": width, "height": height}, is_mobile=True,
                                          has_touch=True, color_scheme="dark")
            try:
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                suffix = f"{width}x{height}-dark.png"
                response = page.goto(f"http://127.0.0.1:{server.server_port}/#settings/memory")
                assert response.status == 200, (response.status, response.text())
                run = page.get_by_role("button", name="Run now")
                expect(run).to_be_enabled()
                expect(page.locator("#memory-review-time")).to_have_value("03:00")
                check(page, "#memory-review-settings")
                page.screenshot(path=output / f"settings-{suffix}")

                enabled = page.get_by_label("Run nightly")
                enabled.uncheck()
                page.locator("#memory-review-time").fill("04:15")
                page.get_by_role("button", name="Save schedule").click()
                expect(page.locator("#memory-review-settings-status")).to_have_text("Review schedule saved.")
                run.click()
                expect(page.locator("#memory-review-settings-status")).to_contain_text("4 new proposals", timeout=10_000)
                go(page, "home")
                card = page.get_by_role("article", name="Memory review")
                expect(card).to_be_visible()
                check(page, ".feed-card")
                page.screenshot(path=output / f"feed-{suffix}")
                card.get_by_role("button", name="Review proposals").click()
                expect(page.get_by_role("heading", name="Memory review", exact=True)).to_be_focused()
                expect(page.get_by_text(FACT, exact=False).first).to_be_visible()
                check(page, ".memory-review")
                page.screenshot(path=output / f"review-{suffix}")

                contradiction = page.get_by_role("article", name="Contradiction")
                expect(contradiction.get_by_text(MONDAY)).to_be_visible()
                expect(contradiction.get_by_text(FRIDAY)).to_be_visible()
                expect(contradiction.get_by_text("people/rowan.md", exact=False)).to_be_visible()
                expect(contradiction.get_by_text("projects/club.md", exact=False)).to_be_visible()
                contradiction.scroll_into_view_if_needed()
                page.screenshot(path=output / f"contradiction-{suffix}")

                stale = page.get_by_role("article", name="Mark stale")
                stale.get_by_role("button", name="Reject").click()
                expect(stale.get_by_text("Rejected")).to_be_visible()
                page.get_by_role("button", name="Accept all").click()
                expect(page.get_by_role("article", name="Add to profile").get_by_text("Accepted")).to_be_visible()
                expect(contradiction.get_by_role("button", name="Accept")).to_be_enabled()
                contradiction.get_by_role("button", name="Accept").click()
                expect(contradiction.get_by_text("Acknowledged")).to_be_visible()
                go(page, "timeline")
                item = page.locator(".timeline-entry").filter(has_text="Memory review changes accepted").first
                expect(item).to_be_visible()
                item.get_by_role("button", name="Undo", exact=True).click()
                item.get_by_role("button", name="Undo change", exact=True).click()
                expect(item.get_by_role("button", name="Redo", exact=True)).to_be_visible()
                assert FACT not in storage.read("USER.md")
                assert not errors, errors
                print(f"{width}×{height} settings, run, Feed, review decisions and Timeline Undo")
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
