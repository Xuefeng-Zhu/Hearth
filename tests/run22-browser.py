"""Chromium checks and screenshots for the Home dashboard."""

import argparse
import json
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright

from hearth import home, panels, scheduler, timeline
from hearth.agent import DEMO_FILES
from hearth.browserbase import TEST_PATH
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import ConnectorError, read_config
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage, iso
from hearth.threads import MAIN_ORIGIN

ORDER = ["Today", "Inbox to review", "Weather & clock", "Recent files", "Memory", "Activity", "Connections health"]
DEMO = ["Thanksgiving countdown", "Shopping list"]
CONTRAST = """() => {
  const toRGB = (value) => (value.match(/[\\d.]+/g) || []).map(Number);
  const background = (element) => {
    for (let node = element; node; node = node.parentElement) {
      const color = toRGB(getComputedStyle(node).backgroundColor);
      if (color.length === 3 || color[3] === 1) return color;
    }
    return [255, 255, 255];
  };
  const luminance = (colors) => colors.slice(0, 3).reduce((sum, value, index) => {
    const s = value / 255;
    return sum + [0.2126, 0.7152, 0.0722][index] * (s <= .04045 ? s / 12.92 : ((s + .055) / 1.055)**2.4);
  }, 0);
  return [...document.querySelectorAll('#home-view *')].flatMap((element) => {
    const text = [...element.childNodes].find((item) => item.nodeType === 3 && item.textContent.trim());
    if (!text || !element.checkVisibility() || element.closest(':disabled')) return [];
    const style = getComputedStyle(element);
    const a = luminance(toRGB(style.color)), b = luminance(background(element));
    return [{ text: text.textContent, ratio: (Math.max(a,b)+.05) / (Math.min(a,b)+.05) }];
  });
}"""


class FixtureGateway:
    def discover(self):
        connections = {"vocalbridge": ["demo-voice"], "tavily": ["demo-tavily"], "apify": ["demo-apify"]}
        return connections, set(connections)

    def json(self, config, path, **kwargs):
        if (config["provider"], path) == ("vocalbridge", "api/v1/agent/versions"):
            return {"name": "Hearth demo"}
        raise ConnectorError("The connector is unavailable.", 503)

    def open(self, config, path, *, timeout):
        assert (config["provider"], path) == ("apify", "v2/users/me")
        raise ConnectorError("Test denied.", 403)

    def request(self, path, body, headers, timeout):
        assert path == f"browserbase/{TEST_PATH}"
        raise ConnectorError("No Browserbase connection.", 404, missing_connection=True)


def seed(app):
    now = datetime.now(timezone.utc)
    with app.storage.lock():
        state = app.storage.load()
        for hours, message in [(1, "Confirm Thanksgiving headcount"), (4, "Pick up groceries"), (6, "Check the oven schedule")]:
            scheduler.add_job(state, message, now, at=iso(now + timedelta(hours=hours)))
        state["inbox"] = {str(i): {"status": "review", "subject": title, "received_at": iso(now - timedelta(minutes=i))}
                          for i, title in enumerate(["Dinner RSVP from Maya", "Grocery pickup confirmation",
                                                     "Library book club reminder", "Weekend ferry reservation"])}
        app.storage.save(state)
    for kind, title in [("memory", "Saved Thanksgiving plans"), ("inbox", "Email ready for review"),
                        ("reminder", "Set a grocery reminder")]:
        timeline.record(app.storage, kind, title, MAIN_ORIGIN, data={})
    for fmt in ("pdf", "xlsx"):
        data = dict(DEMO_FILES[fmt][1])
        app.artifacts.create(fmt, data, kind=data.pop("kind"), origin=MAIN_ORIGIN)
    app.home.refresh_weather(now - timedelta(minutes=5))


def mock_weather(row):
    if row["location"] != home.DEFAULT_LOCATION:
        return {"name": row["location"], "latitude": 47.6, "longitude": -122.3}, {"temperature": 52, "code": 2}
    return home.DEFAULT_PLACE, {"temperature": 49, "code": 3}


def go(page, name, mobile):
    if mobile:
        page.get_by_role("button", name="Open menu").click()
        scope = page.locator("#workspace-drawer")
    else:
        scope = page.locator(".sidebar")
    scope.get_by_role("button", name=name, exact=True).click()


def capture(page, directory, label, mobile):
    if not directory:
        return
    view = page.locator("#home-view")
    view.evaluate("element => element.scrollTop = 0")
    page.screenshot(path=directory / f"run22-home-{label}.png", animations="disabled")
    if mobile:
        viewport = page.viewport_size
        height = view.evaluate("element => Math.ceil(element.getBoundingClientRect().top + element.scrollHeight) + 1")
        page.set_viewport_size({"width": viewport["width"], "height": height})
        view.evaluate("element => element.scrollTop = 0")
        page.screenshot(path=directory / f"run22-all-panels-{label}.png", animations="disabled", full_page=True)
        page.set_viewport_size(viewport)


def test_dashboard(page, base, mobile, label, shots, app):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    # Keep connector health fixtures steady without hitting an external gateway during the browser run.
    page.route("**/api/connections/rescan", lambda route: route.fulfill(json=app.connection_info()))
    page.goto(base)
    expect(page).to_have_title("Hearth")
    expect(page.locator("#view-title")).to_have_text("Home")
    try:
        expect(page.locator("#home-grid h2")).to_have_text(ORDER)
    except AssertionError as error:
        raise AssertionError((errors, page.locator("#home-feedback").text_content(),
                              page.evaluate("fetch('/api/home').then(r => r.status, e => String(e))"))) from error
    expect(page.get_by_text("Confirm Thanksgiving headcount")).to_be_visible()
    expect(page.get_by_text("4", exact=True).first).to_be_visible()
    expect(page.get_by_text("4", exact=True).first.locator("..")).to_contain_text("items to review")
    expect(page.locator('[data-panel="inbox"] .home-rows li')).to_have_count(3)
    expect(page.get_by_text("49°F")).to_be_visible()
    statuses = page.locator('[data-panel="connections"] .home-status')
    expect(page.locator('[data-panel="connections"]')).not_to_contain_text("Apify")
    expect(statuses.filter(has_text="OK")).to_have_count(1)
    expect(statuses.filter(has_text="Error")).to_have_count(1)
    expect(statuses.filter(has_text="Not connected")).to_have_count(2)
    assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
    assert page.locator("#home-grid").evaluate("element => getComputedStyle(element).gridTemplateColumns.split(' ').length") == (1 if mobile else 3)
    if mobile:
        page.get_by_role("button", name="Open menu").click()
        nav = page.locator("#workspace-drawer")
    else:
        nav = page.locator(".sidebar")
    expect(nav.locator("nav button").first).to_have_text("Home")
    if mobile:
        nav.get_by_role("button", name="Close menu").click()
    page.get_by_role("button", name="Try sample panels in Chat").click()
    expect(page.locator("#message")).to_have_value(panels.MOCK_DEMO)
    page.get_by_role("button", name="Send message").click()
    expect(page.get_by_role("button", name="Open Home", exact=True)).to_be_visible()
    page.get_by_role("button", name="Open Home", exact=True).click()
    expect(page.locator("#home-grid h2")).to_have_text(ORDER + DEMO)
    assert page.locator("#home-view").evaluate("element => element.scrollTop") == 0
    expect(page.locator('[data-panel="weather"] [data-updated]')).to_have_text(re.compile(r"Updated [5-9] min ago"))
    expect(page.locator(".home-card-countdown .home-stat")).to_have_text(re.compile(r"^(Today|\d+ days?)$"))
    contrast = page.evaluate(CONTRAST)
    assert contrast and min(row["ratio"] for row in contrast) >= 4.5, sorted(contrast, key=lambda row: row["ratio"])[:5]
    capture(page, shots, label, mobile)

    page.locator('[data-panel="files"]').get_by_role("button", name=re.compile("PDF")).click()
    expect(page.locator("#artifact-drawer[open]")).to_be_visible()
    expect(page.locator(".artifact-pdf")).to_be_visible()
    page.get_by_role("button", name="Close artifact").click()
    expect(page.locator('[data-panel="files"]').get_by_role("button", name=re.compile("PDF"))).to_be_focused()

    shopping = page.get_by_role("article", name="Shopping list")
    check = shopping.get_by_role("checkbox", name="Cranberries")
    check.check()
    expect(check).to_be_checked()
    shopping.get_by_role("button", name="Refresh Shopping list").click()
    expect(shopping.locator("[data-updated]")).to_have_text("Updated just now")
    page.reload()
    expect(page.get_by_role("article", name="Shopping list").get_by_role("checkbox", name="Cranberries")).to_be_checked()

    if mobile:
        page.get_by_role("button", name="Edit layout").click()
        page.get_by_role("button", name="Move Today down").click()
        if shots:
            page.screenshot(path=shots / f"run22-reorder-{label}.png", animations="disabled")
    else:
        page.locator('[data-panel="today"] .home-grip').drag_to(page.locator('[data-panel="inbox"] h2'))
        page.get_by_role("button", name="Edit layout").click()
    expect(page.locator("#home-grid h2").first).to_have_text("Inbox to review")
    page.get_by_role("button", name="Remove Today from Home").click()
    expect(page.locator('[data-panel="today"]')).to_have_count(0)
    expect(page.locator("#home-removed")).to_contain_text("Today")
    page.get_by_role("button", name="Restore", exact=True).click()
    expect(page.locator("#home-grid h2").nth(1)).to_have_text("Today")
    page.get_by_role("button", name="Done", exact=True).click()
    page.reload()
    expect(page.locator("#home-grid h2").first).to_have_text("Inbox to review")

    page.locator('[data-panel="weather"]').get_by_role("button", name="Weather settings").click()
    expect(page.get_by_label("Weather location")).to_have_value("Redmond, WA")
    page.get_by_label("Weather location").fill("Seattle, WA")
    page.get_by_role("button", name="Save location").click()
    expect(page.locator("#weather-settings-status")).to_contain_text("Location saved")
    go(page, "Home", mobile)
    expect(page.locator(".home-location")).to_have_text("Seattle, WA")
    page.locator('[data-panel="weather"]').get_by_role("button", name="Refresh Weather & clock").click()
    expect(page.get_by_text("52°F")).to_be_visible()

    page.get_by_role("article", name="Shopping list").get_by_role("button", name="Ask about this").click()
    expect(page.locator("#thread-title")).to_have_text("About Shopping list")
    expect(page.locator("#message")).to_have_value("What should I know about this panel?")
    page.get_by_role("button", name="Send message").click()
    expect(page.locator(".message.assistant").last).to_contain_text("Cranberries")

    definitions = [{"title": f"Extra {index}", "kind": "stat", "source": {"type": "static", "value": index}} for index in range(4)]
    page.locator("#message").fill("/panel create " + json.dumps({"panels": definitions}))
    page.get_by_role("button", name="Send message").click()
    approval = page.get_by_role("button", name="Approve and create panels")
    expect(approval).to_be_visible()
    assert len(app.storage.load()["panels"]) == 2
    approval.click()
    expect(page.get_by_text("Panels added to Home.", exact=True)).to_be_visible()
    assert len(app.storage.load()["panels"]) == 6

    with app.storage.lock():
        state = app.storage.load()
        row = panels.create(state, [panels.definition({
            "title": "Weather bulletin", "kind": "note", "source": {"type": "brain", "query": "Recent updates"},
        }, {})])[0]
        row.update(value="Original bulletin", updated_at=iso(), error="The source failed.")
        app.storage.save(state)
    go(page, "Home", mobile)
    stale = page.get_by_role("article", name="Weather bulletin")
    expect(stale).to_contain_text("Original bulletin")
    expect(stale).to_contain_text("Showing last value. The source failed.")
    with patch("hearth.panels.read_source", return_value="Fresh bulletin"):
        stale.get_by_role("button", name="Refresh Weather bulletin").click()
        expect(stale).to_contain_text("Fresh bulletin")
    expect(stale).not_to_contain_text("The source failed.")

    section = (page.locator('.settings-disclosure[aria-controls="settings-connections"]') if mobile
               else page.locator('[data-settings="connections"]'))
    expect(section.locator("svg")).to_have_count(1)
    page.get_by_role("article", name="Connections health").get_by_role("button", name="Open Connections").click()
    expect(page.locator("#view-title")).to_have_text("Settings")
    expect(section).to_have_attribute("aria-expanded" if mobile else "aria-current", "true" if mobile else "page")
    apify = page.locator('[data-provider="apify"]')
    expect(apify.locator("xpath=ancestor::section/h3")).to_have_text("Available, not used")
    apify.get_by_role("button", name="Test Apify").click()
    expect(apify).to_contain_text("Test denied")
    expect(apify.locator(".connection-status")).to_have_text("Not used by Hearth")
    expect(apify.locator(".error, .unauthorized, .failed, .denied")).to_have_count(0)
    expect(page.locator(".sidebar [data-workspace-status]")).to_have_text("Mock mode")
    expect(page).to_have_url(base + "/#settings/connections/configured")
    if shots:
        page.reload()
        expect(apify).to_be_visible()
        expect(page.locator("#rescan-connections")).to_have_attribute("aria-disabled", "false")
        page.screenshot(path=shots / f"run22-settings-connections-{label}.png", animations="disabled")
    page.locator("#configured-tab").press("ArrowRight")
    expect(page.locator("#not-configured-tab")).to_be_focused()
    expect(page.locator("#not-configured-tab")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#not-configured-panel")).to_be_visible()
    page.go_back()
    expect(apify).to_be_visible()
    page.goto(base + "/#connections/not-configured")
    expect(page).to_have_url(base + "/#settings/connections/not-configured")
    expect(page.locator("#not-configured-panel")).to_be_visible()
    page.reload()
    expect(page.locator("#not-configured-panel")).to_be_visible()
    page.goto(base + "/#connections")
    expect(page).to_have_url(base + "/#settings/connections/not-configured")
    go(page, "Inbox", mobile)
    page.locator("#inbox-address").get_by_role("link", name="Open Connections").click()
    expect(page.locator("#settings-connections")).to_be_visible()
    page.go_back()
    expect(page.locator("#inbox-view")).to_be_visible()
    go(page, "Settings", mobile)
    page.locator('.settings-disclosure[aria-controls="settings-memory"]' if mobile else '[data-settings="memory"]').click()
    page.locator("#memory-connect").click()
    expect(page.locator("#settings-connections")).to_be_visible()
    page.go_back()
    expect(page.locator("#settings-memory")).to_be_visible()
    assert not errors, errors
    print(f"{label}: passed, minimum sampled text contrast {min(row['ratio'] for row in contrast):.2f}:1", flush=True)


def run(options):
    if options.shots:
        options.shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=options.chromium)
        for width, height, mobile in [(1440, 1080, False), (390, 844, True), (375, 812, True)]:
            for theme in ("light", "dark"):
                if options.only and options.only != f"{width}-{theme}":
                    continue
                with TemporaryDirectory(prefix="hearth-run22-") as directory, patch("hearth.home.weather_value", mock_weather):
                    storage = Storage(directory)
                    config = read_config(ROOT / "config/connectors.json")
                    config["brain"] = {"provider": "mock", "model": ""}
                    app = Application(storage, LocalCheckpoints(storage), config, gateway=FixtureGateway())
                    app.scan_connections()
                    seed(app)
                    with HTTPServer(("127.0.0.1", 0), app) as server:
                        threading.Thread(target=server.serve_forever, daemon=True).start()
                        context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=theme,
                                                      locale="en-US", timezone_id="UTC", reduced_motion="reduce",
                                                      is_mobile=mobile, has_touch=mobile)
                        try:
                            test_dashboard(context.new_page(), f"http://127.0.0.1:{server.server_port}",
                                           mobile, f"{width}-{theme}", options.shots, app)
                        finally:
                            context.close()
                            server.shutdown()
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--shots", type=Path)
    parser.add_argument("--chromium")
    parser.add_argument("--only")
    run(parser.parse_args())
