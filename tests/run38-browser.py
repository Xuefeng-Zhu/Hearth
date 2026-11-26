"""Check the grouped Settings accordion and mobile drawer in WebKit."""

import argparse
import runpy
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from playwright.sync_api import Error, expect, sync_playwright

from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import read_config
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage

HOME_FIXTURE = runpy.run_path(str(Path(__file__).with_name("run22-browser.py")))
NAV = ["Home", "Chat", "Timeline", "Artifacts", "Reminders", "Inbox", "Memory"]
GROUPS = {
    "Assistant": ["Brain", "Memory", "Skills", "Search", "Voice"],
    "Connected": ["Connections", "Artifacts"],
    "Notifications": ["Reminders", "Proactivity", "Approvals"],
    "App": ["Home", "Appearance"],
}
THREADS = [
    "Plan the neighborhood dinner and shopping list for twelve guests",
    "Compare train schedules and lodging for the weekend trip",
    "Prepare discussion questions for the next book club meeting",
    "Review the budget for tools and supplies at the community garden",
    "Choose appetizers and a main course for Saturday night",
    "Outline the camping trip and check the equipment list",
    "Draft the volunteer schedule for the school fundraiser",
    "Collect notes for the library's spring workshop",
    "Compare recipes and plan lunches for the week",
    "Revisit the rain forecast and choose a backup picnic spot",
    "Estimate paint and hardware for the kitchen shelves",
    "Sort photos and write captions for the family album",
]


def verify_drawer(page, capture):
    page.get_by_role("button", name="Open menu").click()
    drawer = page.locator("#workspace-drawer")
    body = drawer.locator(".workspace-drawer-body")
    expect(drawer.get_by_role("heading", name="Threads", exact=True)).to_be_visible()
    expect(drawer.get_by_role("button", name="New chat", exact=True)).to_be_visible()
    expect(drawer.locator(".thread-link")).to_have_count(len(THREADS) + 1)
    expect(drawer.get_by_role("navigation", name="Workspace").get_by_role("button")).to_have_text(NAV, use_inner_text=True)
    assert drawer.evaluate("(drawer) => drawer.scrollWidth <= drawer.clientWidth")
    assert body.evaluate("""(body) => {
      const bounds = body.getBoundingClientRect();
      const nav = body.querySelector('nav');
      const links = [...nav.querySelectorAll('button')];
      const rects = links.map(link => link.getBoundingClientRect());
      const threads = body.querySelector('.threads');
      return body.scrollTop === 0 && body.scrollWidth <= body.clientWidth
        && nav.scrollHeight <= nav.clientHeight && nav.scrollWidth <= nav.clientWidth
        && threads.scrollHeight <= threads.clientHeight && threads.scrollWidth <= threads.clientWidth
        && new Set(rects.map(area => area.left)).size === 2
        && rects.every((area, index) => area.width > 0 && area.height > 0
          && area.top >= bounds.top && area.bottom <= bounds.bottom
          && area.left >= bounds.left && area.right <= bounds.right
          && links[index].contains(document.elementFromPoint(
            area.left + area.width / 2, area.top + area.height / 2)));
    }""")
    assert drawer.locator(".thread-label").nth(1).evaluate("""(label) => {
      const style = getComputedStyle(label);
      return label.clientWidth > 120 && label.scrollWidth > label.clientWidth
        && style.textOverflow === 'ellipsis' && style.whiteSpace === 'nowrap';
    }""")
    header = drawer.get_by_role("heading", name="Threads")
    new_chat = drawer.get_by_role("button", name="New chat")
    assert header.bounding_box()["x"] < new_chat.bounding_box()["x"]
    assert abs(header.bounding_box()["y"] - new_chat.bounding_box()["y"]) < 15
    settings = drawer.get_by_role("button", name="Settings")
    pinned = settings.bounding_box()
    assert pinned["y"] + pinned["height"] >= page.viewport_size["height"] - 20
    capture("drawer")
    body.evaluate("(body) => body.scrollTop = body.scrollHeight")
    assert body.evaluate("(body) => body.scrollTop > 0")
    assert drawer.locator(".thread-link").last.evaluate("""(last) => {
      const body = last.closest('.workspace-drawer-body').getBoundingClientRect();
      const row = last.getBoundingClientRect();
      return row.top >= body.top && row.bottom <= body.bottom;
    }""")
    assert settings.bounding_box() == pinned
    settings.click()
    expect(drawer).to_be_hidden()


def verify_settings(page, origin, mobile, capture):
    view = page.locator("#settings-view")
    expect(page.get_by_role("heading", name="Settings", level=1)).to_be_visible()
    disclosures = view.locator(".settings-disclosure")
    expect(disclosures).to_have_count(sum(map(len, GROUPS.values())))
    expect(view.locator(".settings-body:visible")).to_have_count(0)
    expect(view.locator(".settings-group-label")).to_have_text(list(GROUPS))
    for title, sections in GROUPS.items():
        group = view.get_by_role("group", name=title)
        expect(group.locator(".settings-title")).to_have_text(sections)
    assert disclosures.evaluate_all("""rows => {
      const signature = row => {
        const style = getComputedStyle(row);
        const icon = row.querySelector('svg');
        const title = getComputedStyle(row.querySelector('.settings-title'));
        return [row.clientHeight, style.padding, style.border, style.borderRadius, title.fontWeight,
          icon.getAttribute('width'), icon.getAttribute('stroke-width'), getComputedStyle(icon).color].join('|');
      };
      return rows.every(row => row.querySelectorAll('svg[aria-hidden=true]').length === 2
        && row.querySelector('svg path') && row.querySelector('.settings-subtitle').textContent.trim()
        && signature(row) === signature(rows[0]));
    }""")
    capture("settings-closed")
    for name in (name for group in GROUPS.values() for name in group):
        row = view.get_by_role("button", name=name, exact=True)
        dimensions = row.bounding_box()
        row.press("Enter")
        expect(row).to_have_attribute("aria-expanded", "true")
        panel = page.locator(f"#{row.get_attribute('aria-controls')}")
        expect(panel).to_be_visible()
        expect(view.locator(".settings-body:visible")).to_have_count(1)
        expect(panel.locator(":scope > .section-intro, h1, h2")).to_have_count(0)
        assert row.bounding_box()["height"] == dimensions["height"]
        assert view.evaluate("(view) => view.scrollWidth <= view.clientWidth")
        if name == "Appearance" and mobile:
            expect(panel.get_by_label("Ember view")).to_be_visible()
        row.press("Enter")
        expect(row).to_have_attribute("aria-expanded", "false")
        expect(panel).to_be_hidden()
        expect(page).to_have_url(origin + "/#settings")

    page.goto(origin + "/#connections")
    expect(page).to_have_url(origin + "/#settings/connections/configured")
    expect(view.get_by_role("button", name="Connections", exact=True)).to_have_attribute("aria-expanded", "true")
    expect(view.get_by_role("button", name="Refresh", exact=True)).to_have_attribute("aria-disabled", "false")
    expect(view.get_by_role("searchbox", name="Search providers")).to_be_visible()
    expect(view.locator("#configured-panel .connection-card").first).to_be_visible()
    capture("settings-connections")
    page.goto(origin + "/#skills")
    expect(page).to_have_url(origin + "/#settings/skills")
    expect(view.get_by_role("button", name="Skills", exact=True)).to_have_attribute("aria-expanded", "true")
    expect(view.get_by_role("button", name="New skill")).to_be_visible()
    expect(view.get_by_role("button", name="Plan a dinner party")).to_be_visible()
    if not mobile:
        capture("settings-skills")


def verify(context, origin, width, theme, output):
    page = context.new_page()
    page.add_init_script('localStorage.setItem("hearth-avatar-view", "beside")')
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    response = page.goto(origin)
    assert response.ok, response.status
    mobile = width < 760
    height = page.viewport_size["height"]

    def capture(name):
        if name == "drawer" or width >= 390:
            page.screenshot(path=output / f"{name}-{width}x{height}-{theme}.png", animations="disabled")

    if mobile:
        verify_drawer(page, capture)
    else:
        page.locator('.sidebar [data-view="settings"]').click()
    verify_settings(page, origin, mobile, capture)
    assert not errors, errors
    print(f"{context.browser.browser_type.name} {width}x{height} {theme} passed", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="hearth-run38-") as directory, sync_playwright() as playwright, \
            patch("hearth.home.weather_value", HOME_FIXTURE["mock_weather"]):
        storage = Storage(directory)
        config = read_config(ROOT / "config/connectors.json")
        config["brain"] = {"provider": "mock", "model": ""}
        app = Application(storage, LocalCheckpoints(storage), config, gateway=HOME_FIXTURE["FixtureGateway"]())
        app.scan_connections()
        with storage.lock():
            for title in THREADS:
                app.threads.create(title=title)
        with HTTPServer(("127.0.0.1", 0), app) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                browser = playwright.webkit.launch()
            except Error as error:
                print(f"WebKit launch unavailable, using Chromium with iPhone emulation ({str(error).splitlines()[0]}).")
                browser = playwright.chromium.launch()
            with browser:
                origin = f"http://127.0.0.1:{server.server_port}"
                for width, height, device in ((375, 667, "iPhone SE"), (390, 844, "iPhone 13"),
                                              (1440, 1000, None)):
                    for theme in ("light", "dark"):
                        options = playwright.devices[device] if device else {}
                        with browser.new_context(**{**options, "viewport": {"width": width, "height": height},
                                                    "device_scale_factor": 1, "color_scheme": theme,
                                                    "reduced_motion": "reduce"}) as context:
                            verify(context, origin, width, theme, args.output)
            server.shutdown()
            worker.join()


if __name__ == "__main__":
    main()
