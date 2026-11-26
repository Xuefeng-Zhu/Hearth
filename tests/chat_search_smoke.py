import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import expect

from hearth.storage import atomic_write, iso


def seed_chat_search(app):
    now = datetime.now(timezone.utc)

    def row(identity, text, *, days, minutes=0, role="user"):
        return {"id": identity, "role": role, "content": text, "at": iso(now - timedelta(days=days, minutes=minutes))}

    updates = {
        12: ("greenhouse-first", "The orchid pots need fresh bark before the weather turns.", "user"),
        16: ("greenhouse-second", "Water the orchids on Saturday and let the pots drain before bringing them inside.", "assistant"),
        20: ("greenhouse-hit", "The orchid near the east window has two new blooms. Keep it out of direct afternoon sun.", "assistant"),
    }
    with app.storage.lock():
        garden = app.threads.create(title="Weekend greenhouse")["id"]
        shared = app.threads.create(title="Shared garden notes")["id"]
        field = app.threads.create(title="Field journal")["id"]
        records = []
        for index in range(90):
            identity, content, role = updates.get(index, (f"greenhouse-{index}",
                f"Garden log {index + 1}. Checked the seed trays and moved the rosemary indoors for the evening.",
                "user" if index % 2 == 0 else "assistant"))
            records.append(row(identity, content, days=3, minutes=90 - index, role=role))
        threads = {
            garden: records,
            "main": [
                row("main-plants", "Could you help me plan a more consistent watering schedule for the houseplants?", days=10),
                row("main-orchid", "Add the orchid and the fern to the Sunday watering list.", days=8),
                row("main-list", "Here is a Sunday checklist. Check each pot before watering, and move the fern away from the heater.",
                    days=8, role="assistant"),
                row("main-light", "Which corner gets the best light early in the day?", days=6),
                row("main-answer", "Try the east window in the morning. The light is gentler there than in the living room.",
                    days=6, role="assistant"),
            ],
            shared: [
                row("shared-note", "Put the orchid labels in the green tin by the door.", days=13),
                row("shared-answer", "I’ve added the orchid labels to the list for the next garden swap.", days=12, role="assistant"),
                row("shared-escaped", "Markup example <img onerror=alert(1)>", days=12),
            ],
            field: [row(f"field-{i}", f"Fieldwork journal entry {i + 1}.", days=20, minutes=52 - i) for i in range(52)],
        }
        for thread, rows in threads.items():
            atomic_write(app.threads.path(thread), "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in rows))
        app.storage.bump_revision(threads=True)
    return garden


def capture(page, name):
    output = os.environ.get("HEARTH_CHAT_SEARCH_SCREENSHOTS")
    if output:
        page.screenshot(path=Path(output) / name, animations="disabled")


def open_chat(page, *, mobile=False):
    assert page.goto("/").ok
    if mobile:
        page.get_by_role("button", name="Open menu").click()
    page.get_by_role("button", name="Chat", exact=True).click()
    expect(page.locator('[data-message-id="main-light"]')).to_be_visible()


def verify_contrast(page):
    ratios = page.locator("#chat-search-dialog").evaluate("""dialog => {
      const luminance = color => color.match(/[0-9.]+/g).slice(0, 3)
        .map(v => v / 255)
        .map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
        .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
      const ratio = (fore, back) => {
        const [a, b] = [luminance(fore), luminance(back)].sort((a, b) => a - b);
        return (b + 0.05) / (a + 0.05);
      };
      const paint = selector => getComputedStyle(dialog.querySelector(selector));
      const surface = getComputedStyle(dialog).backgroundColor;
      const input = dialog.querySelector("input");
      const active = paint('[aria-selected="true"]');
      return [
        ratio(paint('h2').color, surface),
        ratio(paint('.chat-search-status').color, surface),
        ratio(paint('.chat-search-group-title').color, surface),
        ratio(paint('input').color, paint('input').backgroundColor),
        ratio(getComputedStyle(input, '::placeholder').color, paint('input').backgroundColor),
        ratio(paint('.chat-search-meta').color, active.backgroundColor),
        ratio(paint('.chat-search-snippet').color, active.backgroundColor),
        ratio(paint('mark').color, paint('mark').backgroundColor),
        ratio(paint('[aria-pressed="true"]').color, paint('[aria-pressed="true"]').backgroundColor),
        ratio(active.outlineColor, active.backgroundColor),
      ];
    }""")
    assert all(ratio >= 4.5 for ratio in ratios[:-1]) and ratios[-1] >= 3, ratios


def verify_hit(page, identity):
    target = page.locator(f'[data-message-id="{identity}"]')
    expect(target).to_have_class("message assistant chat-search-hit" if identity != "greenhouse-first"
                                else "message user chat-search-hit")
    assert target.evaluate("""message => {
      const item = message.getBoundingClientRect();
      const chat = document.querySelector('#chat-scroll').getBoundingClientRect();
      return item.top >= chat.top && item.bottom <= chat.bottom;
    }""")
    return target


def desktop_flow(page, garden, scheme):
    open_chat(page)
    trigger = page.get_by_role("button", name="Search chats")
    composer = page.locator("#message")
    composer.press("/")
    expect(composer).to_have_value("/")
    composer.fill("")
    composer.press("Control+k")
    search = page.get_by_role("combobox", name="Search messages")
    expect(search).to_be_focused()
    expect(page.locator("#chat-search-status")).to_have_text("Enter at least 2 characters to search.")
    search.press("Escape")
    expect(composer).to_be_focused()
    trigger.press("/")
    expect(search).to_be_focused()
    dialog = page.locator("#chat-search-dialog")
    expect(dialog).to_have_css("opacity", "1")
    anchor, popover = trigger.bounding_box(), dialog.bounding_box()
    assert popover["y"] >= anchor["y"] + anchor["height"] and popover["x"] + popover["width"] == anchor["x"] + anchor["width"]

    search.fill("orchid")
    options = page.get_by_role("listbox", name="Matching messages").get_by_role("option")
    expect(options).to_have_count(6)
    expect(options.first.locator("mark")).to_have_text("orchid", ignore_case=True)
    search.press("ArrowDown")
    expect(options.first).to_have_attribute("aria-selected", "true")
    verify_contrast(page)
    capture(page, f"chat-search-1440-{scheme}.png")
    if scheme == "dark":
        return

    with page.expect_request(lambda request: "/api/state?" in request.url and
                             "around=greenhouse-hit" in request.url and f"thread={garden}" in request.url):
        search.press("Enter")
    expect(page.locator("#thread-title")).to_have_text("Weekend greenhouse")
    expect(search).to_be_hidden()
    target = verify_hit(page, "greenhouse-hit")
    expect(target).to_be_focused()
    expect(page.locator('[data-message-id="greenhouse-89"]')).to_have_count(0)
    capture(page, "chat-search-jump-1440-light.png")
    expect(target).not_to_have_class("message assistant chat-search-hit")
    page.get_by_role("button", name="Back to latest").click()
    expect(page.locator('[data-message-id="greenhouse-89"]')).to_be_visible()

    trigger.click()
    page.get_by_role("button", name="This chat").click()
    field = page.get_by_role("searchbox", name="Search messages")
    expect(field).to_be_focused()
    status = page.locator("#chat-search-status")
    expect(status).to_have_text("1 of 3")
    verify_hit(page, "greenhouse-hit")
    field.press("ArrowDown")
    expect(status).to_have_text("2 of 3")
    verify_hit(page, "greenhouse-second")
    capture(page, "chat-find-in-thread-1440-light.png")
    page.get_by_role("button", name="Next match").click()
    expect(status).to_have_text("3 of 3")
    verify_hit(page, "greenhouse-first")
    page.get_by_role("button", name="Previous match").click()
    expect(status).to_have_text("2 of 3")
    page.keyboard.press("Escape")
    expect(trigger).to_be_focused()

    trigger.click()
    search.fill("Markup example")
    expect(options).to_have_count(1)
    expect(options.first.locator(".chat-search-snippet img")).to_have_count(0)
    expect(options.first).to_contain_text("<img onerror=alert(1)>")
    page.get_by_role("button", name="Clear search").click()
    expect(search).to_be_focused()
    expect(search).to_have_value("")
    search.fill("missing phrase")
    expect(status).to_have_text("No matching messages.")
    search.fill("fieldwork")
    expect(options).to_have_count(50)
    expect(status).to_have_text("50 results · more available")
    page.get_by_role("button", name="Show more").click()
    expect(options).to_have_count(52)
    expect(status).to_have_text("52 results")
    search.press("Escape")
    expect(trigger).to_be_focused()

    trigger.click()
    failure = "**/api/chat/search?q=delayed+fixture&*"
    page.route(failure, lambda route: route.abort())
    search.fill("delayed fixture")
    expect(status).to_have_text("Couldn’t search messages. Try again.")
    page.unroute(failure)
    slow = lambda request: "/api/chat/search?q=slow+fixture&" in request.url
    held = []
    page.route("**/api/chat/search?q=slow+fixture&*", lambda route: held.append(route))
    with page.expect_event("request", predicate=slow):
        search.fill("slow fixture")
    search.fill("orchid")
    expect(options).to_have_count(6)
    assert len(held) == 1
    held[0].abort()
    expect(status).to_have_text("6 results")


def mobile_flow(page):
    open_chat(page, mobile=True)
    trigger = page.get_by_role("button", name="Search chats")
    trigger.click()
    dialog = page.get_by_role("dialog", name="Search chats")
    expect(dialog).to_be_visible()
    bounds = dialog.bounding_box()
    assert bounds == {"x": 0, "y": 0, "width": 390, "height": 844}, bounds
    search = page.get_by_role("combobox", name="Search messages")
    expect(search).to_be_focused()
    search.fill("orchid")
    options = page.get_by_role("option")
    expect(options).to_have_count(6)
    for control in [trigger, search, *dialog.get_by_role("button").all(), *options.all()]:
        box = control.bounding_box()
        assert box["height"] >= 44 and box["width"] >= 44, box
    capture(page, "chat-search-390-light.png")
    options.first.click()
    expect(dialog).to_be_hidden()
    target = verify_hit(page, "greenhouse-hit")
    expect(target).to_be_focused()
    assert target.locator(".message-body").evaluate("node => getComputedStyle(node).animationName") == "none"


def overflow_sweep(page):
    open_chat(page, mobile=True)
    page.get_by_role("button", name="Search chats").click()
    page.get_by_role("combobox", name="Search messages").fill("orchid")
    expect(page.get_by_role("option")).to_have_count(6)
    cdp = page.context.new_cdp_session(page)
    for width in range(390, 1921):
        cdp.send("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900,
                                                       "deviceScaleFactor": 1, "mobile": False})
        state = page.evaluate("""() => new Promise(resolve => requestAnimationFrame(() => {
          const dialog = document.querySelector('#chat-search-dialog');
          const results = document.querySelector('#chat-search-results');
          const rect = dialog.getBoundingClientRect();
          resolve([innerWidth, document.documentElement.scrollWidth, dialog.clientWidth, dialog.scrollWidth,
            results.clientWidth, results.scrollWidth, rect.left, rect.right, rect.height, dialog.open]);
        }))""")
        actual, whole, dialog, content, results, result_content, left, right, height, modal = state
        assert actual == whole == width and content == dialog and results == result_content, (width, state)
        assert left >= 0 and right <= width and height > 0 and modal == (width <= 760), (width, state)
    print("Zero horizontal overflow at every integer width from 390 through 1920 px.", flush=True)


def chat_search_smoke(browser, app, origin, browser_page, *, sweep=False):
    garden = seed_chat_search(app)
    for scheme in ("light", "dark"):
        with browser_page(browser, origin, viewport={"width": 1440, "height": 900}, color_scheme=scheme) as page:
            desktop_flow(page, garden, scheme)
    with browser_page(browser, origin, viewport={"width": 390, "height": 844}, color_scheme="light",
                      reduced_motion="reduce", has_touch=True, is_mobile=True) as page:
        mobile_flow(page)
    if sweep:
        with browser_page(browser, origin, viewport={"width": 390, "height": 900}) as page:
            overflow_sweep(page)
