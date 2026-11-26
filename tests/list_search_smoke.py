import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect

from test_list_search import seed_list_search


PAGES = {
    "reminders": ("Reminders", "#reminders-content [data-reminder]", 5, 2),
    "inbox": ("Inbox", "#inbox-content [data-inbox]", 4, 2),
    "skills": ("Skills", "#skill-list [data-skill]", 5, 1),
}


def capture(page, name):
    output = os.environ.get("HEARTH_LIST_SEARCH_SCREENSHOTS")
    if output:
        page.screenshot(path=Path(output) / name, animations="disabled")


def field(page, name):
    return page.get_by_role("searchbox", name=f"Search {name.lower()}")


def status(page, key):
    return page.locator(f"#{key}-search").get_by_role("status")


def total(page, key, count):
    expect(status(page, key)).to_have_text(f"{count} {'result' if count == 1 else 'results'}")


def open_list(page, key, *, mobile=False):
    assert page.goto("/").ok
    if mobile:
        page.get_by_role("button", name="Open menu").click()
    name, _, unfiltered, _ = PAGES[key]
    page.get_by_role("button", name=name, exact=True).click()
    total(page, key, unfiltered)


def verify_contrast(page, key):
    ratios = page.locator(f"#{key}-view").evaluate("""view => {
      const luminance = color => color.match(/[0-9.]+/g).slice(0, 3)
        .map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
        .reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
      const ratio = (foreground, background) => {
        const [a, b] = [luminance(foreground), luminance(background)].sort((a, b) => a - b);
        return (b + .05) / (a + .05);
      };
      const style = selector => getComputedStyle(view.querySelector(selector));
      const input = view.querySelector(".search-input");
      const field = style(".search-input");
      let surface = view;
      while (getComputedStyle(surface).backgroundColor === "rgba(0, 0, 0, 0)") surface = surface.parentElement;
      return [
        ratio(field.color, field.backgroundColor),
        ratio(getComputedStyle(input, "::placeholder").color, field.backgroundColor),
        ratio(style(".list-search-status").color, getComputedStyle(surface).backgroundColor),
        ratio(style("mark").color, style("mark").backgroundColor),
        ratio(style(".search-clear").color, field.backgroundColor),
        ratio(style(".chat-search-field > svg").color, field.backgroundColor),
        ratio(field.borderTopColor, field.backgroundColor),
      ];
    }""")
    assert all(ratio >= 4.5 for ratio in ratios[:5]) and all(ratio >= 3 for ratio in ratios[5:]), ratios


def desktop(page, key, scheme, skill_id):
    name, selector, unfiltered, count = PAGES[key]
    open_list(page, key)
    if key == "reminders":
        page.locator("#reminder-create summary").click()
        title = page.get_by_role("textbox", name="Title")
        title.press("/")
        expect(title).to_have_value("/")
        page.locator("#reminder-create summary").click()
    search = field(page, name)
    page.keyboard.press("/")
    expect(search).to_be_focused()
    search.press_sequentially("cafe")
    total(page, key, count)
    rows = page.locator(selector)
    expect(rows).to_have_count(count)
    expect(page.locator(f"#{key}-view mark").first).to_have_text(re.compile("café", re.IGNORECASE))
    verify_contrast(page, key)
    capture(page, f"{key}-search-1440-{scheme}.png")
    clear = page.locator(f"#{key}-search").get_by_role("button", name="Clear search")
    if key == "reminders":
        page.get_by_role("tab", name="Recurring tasks").click()
        expect(search).to_be_hidden()
        page.keyboard.press("/")
        expect(search).to_be_hidden()
        page.get_by_role("tab", name="Reminders", exact=True).click()
        expect(search).to_have_value("cafe")
        total(page, key, count)
        expect(page.get_by_role("heading", name="Delivered")).to_be_hidden()

    clear.click()
    expect(search).to_be_focused()
    expect(search).to_have_value("")
    total(page, key, unfiltered)
    page.go_back()
    expect(search).to_have_value("cafe")
    total(page, key, count)
    page.go_forward()
    expect(search).to_have_value("")
    total(page, key, unfiltered)
    page.go_back()
    expect(search).to_have_value("cafe")
    assert page.reload().ok
    expect(search).to_have_value("cafe")
    total(page, key, count)

    if key == "inbox":
        expect(page.locator("#inbox-content").get_by_role("heading", name="Review")).to_be_visible()
        expect(page.locator("#inbox-content").get_by_role("heading", name="Processed")).to_be_visible()
        search.fill("<img src=x>")
        total(page, key, 1)
        expect(rows.locator("mark")).to_have_text("<img src=x>")
        expect(rows.locator("img")).to_have_count(0)
        search.fill("no such correspondence")
        total(page, key, 0)
        expect(rows).to_have_count(0)
        empty = page.locator("#inbox-search-empty")
        expect(empty.get_by_text("No matches found.")).to_be_visible()
        capture(page, "inbox-search-empty-1440-light.png")
        empty.get_by_role("button", name="Clear search").click()
        expect(search).to_be_focused()
        total(page, key, unfiltered)

    if key == "skills":
        requested = []

        def record(request):
            parts = urlsplit(request.url)
            if parts.path == "/api/skills" and (query := parse_qs(parts.query).get("q")):
                requested.append(query[0])

        page.on("request", record)
        search.fill("")
        search.press_sequentially("picnic", delay=20)
        total(page, key, 1)
        expect(rows.first.locator("../..").get_by_text("picnic", exact=True)).to_be_visible()
        assert requested == ["picnic"], requested
        page.evaluate("(id) => location.hash = '#skills/' + id + '?q=picnic'", skill_id)
        dialog = page.get_by_role("dialog", name="Weekend planning")
        expect(dialog).to_be_visible()
        dialog.get_by_role("button", name="Close").click()
        expect(dialog).to_be_hidden()
        expect(search).to_have_value("picnic")
        assert urlsplit(page.url).fragment == "skills?q=picnic", page.url


def verify_mobile_geometry(page, key, width):
    state = page.locator(f"#{key}-view").evaluate("""view => {
      const field = view.querySelector(".search-input");
      const clear = view.querySelector(".search-clear");
      const toolbar = view.querySelector(".list-search");
      const bounds = field.getBoundingClientRect();
      return {
        viewport: innerWidth,
        document: document.documentElement.scrollWidth,
        panel: view.clientWidth,
        content: view.scrollWidth,
        field: bounds.width,
        toolbar: toolbar.clientWidth,
        fieldHeight: bounds.height,
        clearHeight: clear.getBoundingClientRect().height,
        font: parseFloat(getComputedStyle(field).fontSize),
        left: bounds.left, right: bounds.right,
      };
    }""")
    assert state["viewport"] == state["document"] == width and state["panel"] == state["content"], (key, width, state)
    assert state["left"] >= 0 and state["right"] <= width, (key, width, state)
    if width <= 760:
        assert state["field"] == state["toolbar"] and state["fieldHeight"] >= 44, (key, width, state)
        assert state["clearHeight"] >= 44 and state["font"] >= 16, (key, width, state)


def mobile(page, key, *, sweep):
    name, _, unfiltered, count = PAGES[key]
    open_list(page, key, mobile=True)
    search = field(page, name)
    search.fill("cafe")
    total(page, key, count)
    verify_mobile_geometry(page, key, 390)
    if key in ("inbox", "skills"):
        capture(page, f"{key}-search-390-light.png")
    if sweep:
        cdp = page.context.new_cdp_session(page)
        for width in range(390, 1921):
            cdp.send("Emulation.setDeviceMetricsOverride", {"width": width, "height": 844,
                                                           "deviceScaleFactor": 1, "mobile": False})
            verify_mobile_geometry(page, key, width)
        print(f"{name}: zero horizontal overflow at every integer width from 390 through 1920 px.", flush=True)
    page.locator(f"#{key}-search").get_by_role("button", name="Clear search").click()
    total(page, key, unfiltered)


def list_search_smoke(browser, app, origin, browser_page, *, sweep=False):
    skill_id = seed_list_search(app)
    for key in PAGES:
        with browser_page(browser, origin, viewport={"width": 1440, "height": 900}, color_scheme="light") as page:
            desktop(page, key, "light", skill_id)
        with browser_page(browser, origin, viewport={"width": 390, "height": 844}, color_scheme="light",
                          has_touch=True, is_mobile=True) as page:
            mobile(page, key, sweep=sweep)
    with browser_page(browser, origin, viewport={"width": 1440, "height": 900}, color_scheme="dark") as page:
        desktop(page, "reminders", "dark", skill_id)
    for key in ("inbox", "skills"):
        with browser_page(browser, origin, viewport={"width": 1440, "height": 900}, color_scheme="dark") as page:
            name, _, _, count = PAGES[key]
            open_list(page, key)
            field(page, name).fill("cafe")
            total(page, key, count)
            verify_contrast(page, key)
