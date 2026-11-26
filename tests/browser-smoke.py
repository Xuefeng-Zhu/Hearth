"""Run the offline Chromium smoke or the stream disconnect regression."""

import argparse
import os
import re
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright

from hearth import browserbase
from hearth.agent import Agent
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import ConnectorError, Gateway, read_config
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage
from hearth.threads import MAIN_ORIGIN

MOCK_REPLY = "I didn't find a matching note. Try “Plan Thanksgiving dinner”, read a note, or ask me to set a reminder."


class OfflineGateway(Gateway):
    def __init__(self):
        self.requests = []

    def discover(self):
        return {}, set()

    def request(self, path, *args, **kwargs):
        if path == f"{browserbase.PROVIDER}/{browserbase.TEST_PATH}":
            raise ConnectorError("No Browserbase connection configured.", 404, missing_connection=True)
        self.requests.append(path)
        raise AssertionError("The browser fixture attempted a gateway request.")


@contextmanager
def workspace():
    with TemporaryDirectory() as directory:
        storage = Storage(directory)
        gateway = OfflineGateway()
        config = read_config(ROOT / "config/connectors.json")
        config["brain"] = {"provider": "mock", "model": ""}
        with patch.dict(os.environ, {"HEARTH_SHARE_CONFIG": ""}):
            app = Application(storage, LocalCheckpoints(storage), config, gateway=gateway)
        with storage.lock():
            app.threads.create(title="Smoke side chat")
        with HTTPServer(("127.0.0.1", 0), app) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield app, f"http://127.0.0.1:{server.server_port}"
            finally:
                server.shutdown()
                thread.join()
            assert not gateway.requests, "Expected zero gateway requests."


@contextmanager
def browser_page(browser, origin, **options):
    context = browser.new_context(base_url=origin, service_workers="block", **options)
    blocked, errors = [], []

    def route_request(route):
        if route.request.url.startswith(origin + "/"):
            route.continue_()
        else:
            blocked.append(route.request.url)
            route.abort()

    context.route("**/*", route_request)
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("response", lambda response: errors.append(f"{response.status} {response.url}")
            if response.status >= 400 else None)
    try:
        yield page
        assert not blocked and not errors, (blocked, errors)
    except Exception as error:
        if blocked or errors:
            error.add_note(f"Blocked requests: {blocked}; browser errors: {errors}")
        raise
    finally:
        context.close()


@contextmanager
def hold_after_first_token(prompt):
    """Hold the real mock worker after the browser can receive a partial reply."""
    release = Event()
    original_chat = Agent.chat

    def chat(agent, text, event, *args, **kwargs):
        first_token = True

        def handle(name, data):
            nonlocal first_token
            event(name, data)
            if text == prompt and name == "token" and first_token:
                first_token = False
                if not release.wait(15):
                    raise AssertionError("The browser did not release the mock reply.")

        return original_chat(agent, text, handle, *args, **kwargs)

    with patch.object(Agent, "chat", chat):
        try:
            yield release
        finally:
            release.set()


def open_chat(page):
    assert page.goto("/").ok
    expect(page.get_by_role("heading", name="Home", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Edit layout")).to_be_enabled()
    page.get_by_role("button", name="Chat", exact=True).click()
    expect(page.get_by_role("heading", name="Main", exact=True)).to_be_visible()


def send(page, prompt):
    page.get_by_role("textbox", name="Message Hearth").fill(prompt)
    page.get_by_role("button", name="Send message").click()


def await_partial_reply(page):
    partial = page.locator("#transcript .message.assistant:not([data-message-id]) .message-body > p")
    expect(partial).to_have_text("I")
    stop = page.get_by_role("button", name="Stop reply")
    expect(stop).to_be_visible()
    return stop


def tab_to(page, target, key="Tab"):
    for _ in range(50):
        if target.evaluate("(element) => element === document.activeElement"):
            return
        page.keyboard.press(key)
    raise AssertionError(f"Could not reach {target} with {key}.")


def keyboard_send(page, prompt):
    composer = page.get_by_role("textbox", name="Message Hearth")
    tab_to(page, composer)
    page.keyboard.insert_text(prompt)
    tab_to(page, page.get_by_role("button", name="Send message"))
    page.keyboard.press("Enter")
    expect(composer).to_be_focused()


def track_reply_announcements(page):
    live = page.locator("#reply-status")
    expect(live).to_have_attribute("aria-live", "polite")
    live.evaluate("""element => {
      window.replyAnnouncements = [];
      new MutationObserver(records => {
        for (const {addedNodes} of records) {
          for (const node of addedNodes) {
            if (node.textContent) window.replyAnnouncements.push(node.textContent);
          }
        }
      }).observe(element, {childList: true, characterData: true, subtree: true});
    }""")


def expect_announcements(page, expected_count):
    announcements = page.evaluate("window.replyAnnouncements")
    assert len(announcements) == expected_count, announcements
    assert all(text.startswith("Hearth replied. I didn't find a matching note.")
               and len(text) <= 116 for text in announcements), announcements


def assert_column_edges(view, selectors):
    boxes = []
    for selector in selectors:
        blocks = view.locator(f"{selector}:visible")
        expect(blocks.first).to_be_visible()
        boxes.extend(block.bounding_box() for block in blocks.all())
    assert len(boxes) >= 2 and all(boxes), selectors
    left = [box["x"] for box in boxes]
    right = [box["x"] + box["width"] for box in boxes]
    assert max(left) - min(left) <= 1 and max(right) - min(right) <= 1, (selectors, left, right)


def artifact_layout(page, view, width):
    cards = view.locator(".artifact-card")
    expect(cards.first).to_be_visible()
    imported = cards.filter(has_text="Fixture receipt.bin")
    expect(imported.get_by_role("link", name="Download", exact=True)).to_be_visible()
    grid = cards.evaluate_all("""cards => {
      const rows = new Map();
      for (const card of cards) {
        const box = card.getBoundingClientRect();
        const foot = card.querySelector('.artifact-card-foot').getBoundingClientRect();
        const row = rows.get(box.y) || [];
        row.push({ top: foot.y, left: foot.left - box.left, right: box.right - foot.right });
        rows.set(box.y, row);
      }
      return [...rows.values()];
    }""")
    if width > 760:
        assert len(grid[0]) > 1, (width, grid)
    for row in grid:
        assert max(foot["top"] for foot in row) - min(foot["top"] for foot in row) <= 1, (width, row)
        assert all(abs(foot["left"] - 1) <= 1 and abs(foot["right"] - 1) <= 1 for foot in row), row
    expect(view.get_by_role("button", name="Retry sync")).to_have_count(0)
    view.get_by_role("button", name="List view").click()
    expect(view.get_by_role("table", name="Artifacts")).to_be_visible()
    expect(view.locator("#artifact-list")).to_have_attribute("aria-pressed", "true")
    if width >= 1280:
        expect(view.get_by_role("columnheader", name="Modified")).to_be_visible()
        rows = cards.evaluate_all("""cards => cards.map(card => {
          const rect = card.getBoundingClientRect();
          const center = box => box.y + box.height / 2;
          const actions = card.querySelectorAll('.artifact-row-action');
          return {height: rect.height,
            offsets: [...actions].map(el => center(el.getBoundingClientRect()) - center(rect))};
        })""")
        assert all(abs(offset) <= 1 for row in rows for offset in row["offsets"]), (width, rows)
        assert max(row["height"] for row in rows) - min(row["height"] for row in rows) <= 1, (width, rows)
        assert_column_edges(view, [".artifact-connection:not(.artifact-load-error)", ".artifact-toolbar", ".artifact-collection"])
        view.evaluate("view => view.scrollTop = 450")
        header_y = view.locator(".artifact-list-head").bounding_box()["y"]
        view_y = view.bounding_box()["y"]
        assert abs(header_y - view_y) <= 1, (width, header_y, view_y, view.evaluate("view => view.scrollTop"))
        view.evaluate("view => view.scrollTop = 0")

    view.get_by_role("button", name="Documents", exact=True).click()
    plans = view.get_by_role("button", name="Plans", exact=True)
    plans.press("Enter")
    expect(plans).to_have_attribute("aria-pressed", "true")
    expect(view.get_by_role("button", name="Documents", exact=True)).to_have_attribute("aria-pressed", "true")
    assert page.url.endswith("#artifacts/documents/plan"), page.url
    expect(cards.first).to_be_visible()
    assert cards.locator(".artifact-badge.is-docx").count() == cards.count()
    expect(view.locator('.artifact-card:not([data-kind="plan"])')).to_have_count(0)
    view.locator("#artifact-sort").press("ArrowDown")
    expect(view.locator("#artifact-sort")).to_have_value("name")
    view.get_by_role("searchbox", name="Search artifacts").fill("No matching file 1234")
    expect(view.get_by_role("heading", name="No matches")).to_be_visible()
    view.get_by_role("button", name="Clear filters").click()
    expect(view.locator("#artifact-search")).to_be_focused()
    expect(view.get_by_role("button", name="All", exact=True)).to_have_attribute("aria-pressed", "true")


def artifact_sync_smoke(page, view):
    connected = False

    def inventory(route):
        response = route.fetch()
        data = response.json()
        data["connected"] = connected
        failed = next(item for item in data["artifacts"] if item["format"] == "docx")
        failed.update(sync="error", sync_message="Fixture sync failed.")
        if connected:
            eligible = [item for item in data["artifacts"] if item["sync"] == "local" and item["format"] == "docx"]
            for item in eligible[:2]:
                item["ask_filename"] = item["filename"]
        route.fulfill(response=response, json=data)

    page.route("**/api/artifacts?refresh=1", inventory)
    status = view.locator("#artifact-box-status")
    refresh = view.get_by_role("button", name="Refresh artifacts")
    retry = view.get_by_role("button", name="Retry sync")
    refresh.click()
    expect(status).to_have_text("Box disconnected")
    expect(view.get_by_text("Sync error", exact=True)).to_have_count(1)
    expect(retry).to_have_count(0)
    connected = True
    refresh.click()
    expect(status).to_have_text("Box connected")
    expect(retry).to_have_count(1)
    failed = view.locator(".artifact-card:has(.artifact-sync.is-error)")
    expect(failed.get_by_role("button", name="Retry sync")).to_be_visible()
    expect(failed.get_by_role("link", name="Download", exact=True)).to_be_visible()
    page.route("**/api/artifacts/ask", lambda route: route.fulfill(json={"answer": "Fixture answer."}))
    ask = view.get_by_role("button", name="Ask my files")
    ask.click()
    dialog = page.get_by_role("dialog", name="Ask my files")
    dialog.get_by_role("radio", name="Select files").check()
    expect(dialog.get_by_role("button", name="Ask Hearth")).to_be_disabled()
    dialog.get_by_role("checkbox").first.check()
    dialog.get_by_role("textbox", name="Question").fill("What does the fixture say?")
    with page.expect_request("**/api/artifacts/ask") as query:
        dialog.get_by_role("button", name="Ask Hearth").click()
    assert len(query.value.post_data_json["artifact_ids"]) == 1
    expect(dialog.get_by_text("Fixture answer.")).to_be_visible()
    page.keyboard.press("Escape")
    expect(ask).to_be_focused()

    page.route("**/api/artifacts/retry", lambda route: route.fulfill(json={"sync": "synced"}))
    with page.expect_request("**/api/artifacts/retry") as request:
        retry.click()
    assert request.value.post_data_json["id"]
    expect(retry).to_have_count(0)


def layout_smoke(browser, app, origin):
    # Scrollable document previews can be wider than their own viewport.
    # The workspace and its page containers must still fit the screen.
    views = {
        "Home": ".home-heading",
        "Chat": ".thread-header",
        "Timeline": ".timeline-intro",
        "Artifacts": ".artifact-intro",
        "Reminders": ".automation-tabs",
        "Inbox": ".delivery-intro",
        "Memory": ".memory-intro",
        "Skills": ".section-intro",
        "Settings": ".settings-sections",
    }
    for index in range(15):
        title = f"File {index}" + (" · Coordination and contingencies for the Friday neighborhood market" if index % 2 else "")
        app.artifacts.create("docx", {"title": title, "sections": [{"heading": title, "paragraphs": ["Fixture document"]}]},
                             kind="plan" if index % 2 else "note")
    app.pages.save("Fixture page", "<html><body><h1>Fixture page</h1></body></html>", "First version", MAIN_ORIGIN)
    app.artifacts.import_mail("Fixture receipt.bin", b"fixture", origin={}, sync=False)
    wide_groups = {
        "Home": [".home-heading", ".home-grid"],
        "Timeline": [".timeline-today", ".timeline-controls", ".timeline-entry"],
        "Reminders": [".automation-tabs", "#reminder-create", ".delivery-empty"],
        "Inbox": [".delivery-intro", "#inbox-address"],
        "Memory": ["#memory-find", "#memory-tabs", "#memory-area"],
        "Skills": [".section-intro", "#skill-list"],
        "Settings": [".settings-entry"],
    }
    for width, height in ((390, 844), (768, 1024), (1440, 900), (1920, 1080)):
        mobile = width <= 760
        with browser_page(browser, origin, viewport={"width": width, "height": height},
                          is_mobile=mobile, has_touch=mobile) as page:
            assert page.goto("/").ok
            title = page.locator("#view-title")
            menu = page.locator("#open-menu")
            assert menu.is_visible() == mobile, width
            for name, content in views.items():
                view = page.locator(f"#{name.lower()}-view")
                if name != "Home":
                    if mobile:
                        menu.click()
                    nav = page.locator("#workspace-drawer" if mobile else ".sidebar")
                    nav.get_by_role("button", name=name, exact=True).click()
                expect(title).to_have_text(name)
                anchor = view.locator(content).first
                expect(anchor).to_be_visible()
                overflow = view.evaluate("""view => {
                  const visible = el => el.getClientRects().length > 0;
                  return [document.documentElement, document.querySelector('main'), view,
                    ...view.querySelectorAll('.home-inner, .chat-scroll, .composer, .artifact-toolbar, .settings-sections')]
                    .filter(el => visible(el) && el.scrollWidth > el.clientWidth + 1)
                    .map(el => [el.id || el.className, el.clientWidth, el.scrollWidth]);
                }""")
                assert not overflow, (name, width, overflow)
                if name != "Chat":
                    edge = (menu if mobile else title).bounding_box()["x"]
                    assert abs(edge - anchor.bounding_box()["x"]) <= 1, (name, width)
                if width >= 1440 and name in wide_groups:
                    assert_column_edges(view, wide_groups[name])
                    header = page.locator(".header").bounding_box()
                    sidebar = page.locator(".sidebar").bounding_box()
                    assert abs(sidebar["x"] + sidebar["width"] - header["x"]) <= 1
                    if name == "Settings":
                        view.locator('[data-settings="approvals"]').click()
                        expect(view.locator("#approval-policies select").first).to_be_visible()
                        assert_column_edges(view, [".settings-entry", "#settings-approvals"])
                for row in view.locator(".split-heading:visible").all():
                    left, right = row.locator(":scope > *").all()
                    left_box, right_box, row_box = left.bounding_box(), right.bounding_box(), row.bounding_box()
                    assert abs(right_box["x"] + right_box["width"] - row_box["x"] - row_box["width"]) <= 1, (name, width)
                    if right_box["y"] < left_box["y"] + left_box["height"]:
                        left_center = left_box["y"] + left_box["height"] / 2
                        right_center = right_box["y"] + right_box["height"] / 2
                        assert abs(left_center - right_center) <= 1, (name, width)
                if name == "Artifacts":
                    header_controls = view.locator(".artifact-box-control > *").all()
                    header_boxes = [control.bounding_box() for control in header_controls]
                    assert max(box["y"] for box in header_boxes) - min(box["y"] for box in header_boxes) <= 1, (width, header_boxes)
                    assert max(box["height"] for box in header_boxes) - min(box["height"] for box in header_boxes) <= 1, (width, header_boxes)
                    controls = view.locator(".artifact-toolbar :is(input, select, button)").all()
                    heights = [control.bounding_box()["height"] for control in controls]
                    assert max(heights) - min(heights) <= 1, (width, heights)
                    if mobile:
                        assert min(heights) >= 44, (width, heights)
                    for select in view.locator(".artifact-toolbar select").all():
                        style = select.evaluate("""control => {
                          const style = getComputedStyle(control);
                          return {
                            appearance: style.appearance,
                            chevron: style.backgroundImage,
                            start: parseFloat(style.paddingInlineStart),
                            end: parseFloat(style.paddingInlineEnd),
                          };
                        }""")
                        assert style["appearance"] == "none", (width, style)
                        assert style["chevron"].endswith('/icons/chevron.svg")'), (width, style)
                        assert style["end"] > style["start"] + 16, (width, style)
                    artifact_layout(page, view, width)
                    if width == 1440:
                        artifact_sync_smoke(page, view)


def smoke(browser, origin):
    with browser_page(browser, origin) as page:
        assert page.goto("/").ok
        expect(page.get_by_role("heading", name="Home", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Edit layout")).to_be_enabled()
        tab_to(page, page.get_by_role("button", name="Chat", exact=True))
        page.keyboard.press("Enter")
        expect(page.get_by_role("heading", name="Main", exact=True)).to_be_visible()
        track_reply_announcements(page)
        transcript = page.locator("#transcript")
        answers = transcript.locator(".message.assistant[data-message-id]")
        composer = page.get_by_role("textbox", name="Message Hearth")
        prompt = "Nebulaquill smoke fixture"
        with hold_after_first_token(prompt) as release:
            keyboard_send(page, prompt)
            await_partial_reply(page)
            expect_announcements(page, 0)
            release.set()
        expect(answers.get_by_text(MOCK_REPLY, exact=True)).to_be_visible()
        expect(composer).to_be_focused()
        expect_announcements(page, 1)

        side = page.get_by_role("button", name="Smoke side chat", exact=True)
        main_thread = page.locator('.thread-link[data-thread="main"]')
        prompt = "Nebulaquill switch fixture"
        with hold_after_first_token(prompt) as release:
            keyboard_send(page, prompt)
            await_partial_reply(page)
            tab_to(page, side, "Shift+Tab")
            page.keyboard.press("Enter")
            expect(page.get_by_role("heading", name="Smoke side chat", exact=True)).to_be_visible()
            expect(side).to_be_focused()
            expect(transcript.locator(".message")).to_have_count(0)
            expect_announcements(page, 1)
            tab_to(page, main_thread, "Shift+Tab")
            page.keyboard.press("Enter")
            expect(main_thread).to_be_focused()
            await_partial_reply(page)
            release.set()
        expect(answers.get_by_text(MOCK_REPLY, exact=True)).to_have_count(2)
        expect(main_thread).to_be_focused()
        expect_announcements(page, 2)

        prompt = "Nebulaquill stop fixture"
        with hold_after_first_token(prompt) as release:
            keyboard_send(page, prompt)
            stop = await_partial_reply(page)
            tab_to(page, stop)
            with page.expect_response(lambda response: response.url.endswith("/api/chat/stop")) as stopped:
                page.keyboard.press("Enter")
            assert stopped.value.json() == {"stopped": True}
            release.set()
            expect(transcript.get_by_text("Reply stopped.", exact=True)).to_be_visible()
            expect(stop).to_be_hidden()
        expect(composer).to_be_focused()
        expect(answers).to_have_count(2)
        expect_announcements(page, 2)
        page.get_by_role("button", name="Settings", exact=True).click()
        expect(page.get_by_role("heading", name="Settings", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name=re.compile(r"^Brain\b"))).to_be_visible()

    with browser_page(browser, origin, viewport={"width": 390, "height": 844},
                      is_mobile=True, has_touch=True) as page:
        assert page.goto("/").ok
        menu = page.get_by_role("button", name="Open menu")
        menu.click()
        drawer = page.get_by_role("dialog", name="Hearth")
        expect(drawer).to_be_visible()
        expect(menu).to_have_attribute("aria-expanded", "true")
        drawer.get_by_role("button", name="Chat", exact=True).click()
        expect(drawer).to_be_hidden()
        expect(page.get_by_role("heading", name="Main", exact=True)).to_be_visible()
        tab_to(page, menu, "Shift+Tab")
        page.keyboard.press("Enter")
        side = drawer.get_by_role("button", name="Smoke side chat", exact=True)
        tab_to(page, side)
        page.keyboard.press("Enter")
        expect(drawer).to_be_hidden()
        heading = page.get_by_role("heading", name="Smoke side chat", exact=True)
        expect(heading).to_be_focused()


def stale_refresh(browser, origin):
    with browser_page(browser, origin, color_scheme="dark", viewport={"width": 390, "height": 844}) as page:
        page.add_init_script("""(() => {
          const fetch = window.fetch.bind(window);
          window.refreshFixture = {path: '', fault: '', failures: 0, recovered: 0};
          window.fetch = async (url, options) => {
            const state = window.refreshFixture;
            if (url.split('?')[0] !== state.path) return fetch(url, options);
            if (state.fault) {
              state.failures++;
              if (state.fault === 'offline') throw new TypeError('Disconnected fixture');
              return new Response('{"error":"Private fixture detail"}', {status: 500});
            }
            const response = await fetch(url, state.path === '/api/home' ? {...options, headers: {}} : options);
            state.recovered = response.status;
            return response;
          };
        })()""")
        assert page.goto("/").ok
        expect(page.get_by_role("button", name="Edit layout")).to_be_enabled()
        status = page.locator("#refresh-status")
        expect(status).to_have_attribute("role", "status")

        def fail(path, fault, label):
            page.evaluate("""([path, fault]) => {
              Object.assign(window.refreshFixture, {path, fault, failures: 0, recovered: 0});
            }""", [path, fault])
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            page.wait_for_function("window.refreshFixture.failures === 1")
            expect(status).to_be_empty()
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            expect(status).to_have_text(label)
            expect(status).to_be_visible()
            contrast = status.evaluate("""element => {
              const style = getComputedStyle(element);
              const luminance = color => color.match(/\\d+/g).slice(0, 3).map(Number).map(value => {
                const channel = value / 255;
                return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
              }).reduce((sum, value, i) => sum + value * [0.2126, 0.7152, 0.0722][i], 0);
              const levels = [luminance(style.color), luminance(style.backgroundColor)].sort((a, b) => b - a);
              return (levels[0] + 0.05) / (levels[1] + 0.05);
            }""")
            assert contrast >= 4.5
            assert not page.get_by_text("Private fixture detail").is_visible()

        def recover(expected_code):
            page.evaluate("""() => {
              window.refreshFixture.fault = '';
              window.dispatchEvent(new Event('focus'));
            }""")
            expect(status).to_be_empty()
            assert page.evaluate("window.refreshFixture.recovered") == expected_code

        fail("/api/home", "server", "Stale · Server error")
        expect(page.get_by_role("heading", name="Today", exact=True)).to_be_visible()
        recover(200)
        page.get_by_role("button", name="Open menu").click()
        page.get_by_role("dialog", name="Hearth").get_by_role("button", name="Chat", exact=True).click()
        expect(page.get_by_role("heading", name="Main", exact=True)).to_be_visible()
        page.wait_for_function("performance.getEntriesByType('resource').some(entry => entry.name.includes('/api/state?'))")
        page.context.set_offline(True)
        fail("/api/state", "offline", "Stale · Offline")
        page.context.set_offline(False)
        recover(304)


def disconnect(browser, app, origin):
    with browser_page(browser, origin) as page:
        page.add_init_script("""(() => {
          const fetch = window.fetch.bind(window);
          window.fetch = (url, options) => {
            if (url !== '/api/chat' || options?.method !== 'POST') return fetch(url, options);
            const controller = new AbortController();
            window.disconnectChatStream = () => controller.abort();
            return fetch(url, {...options, signal: controller.signal});
          };
        })()""")
        open_chat(page)
        track_reply_announcements(page)
        prompt = "Nebulaquill disconnect fixture"
        with hold_after_first_token(prompt) as release:
            send(page, prompt)
            stop = await_partial_reply(page)
            expect_announcements(page, 0)
            page.evaluate("window.disconnectChatStream()")
            expect(stop).to_be_hidden()
            release.set()

        transcript = page.locator("#transcript")
        final = transcript.locator(".message.assistant[data-message-id]")
        expect(final.get_by_text(MOCK_REPLY, exact=True)).to_be_visible()
        with app.storage.lock():
            persisted = app.threads.messages("main")
        assert [(row["role"], row["content"]) for row in persisted] == [
            ("user", prompt), ("assistant", MOCK_REPLY),
        ]
        assert persisted[-1]["reply_to"] == persisted[0]["id"]
        expect(final).to_have_attribute("data-message-id", persisted[-1]["id"])
        expect(transcript.locator(".message.user")).to_have_count(1)
        expect(transcript.locator(".message.assistant"),
               "The persisted reply should replace the interrupted partial reply").to_have_count(1)
        expect(page.locator("#notice")).to_be_hidden()
        expect_announcements(page, 1)
        with page.expect_response(lambda response: "/api/state?" in response.url):
            page.evaluate("window.dispatchEvent(new Event('focus'))")
        expect_announcements(page, 1)


def self_update_smoke(browser, app, origin):
    path = "docs/self-update.md"
    with app.storage.lock():
        thread = app.threads.create(title="Hearth update smoke")
        app.threads.append(thread["id"], "user", f"Hearth, add a line to {path}.")
        app.threads.append(thread["id"], "assistant", "Review the proposed change below.", self_update_id="smoke")
    proposal = {
        "id": "smoke", "thread_id": thread["id"], "repository": "Xuefeng-Zhu/Hearth", "thread_title": thread["title"],
        "title": "Clarify the update guide", "summary": "Add a note about reviewing test results.",
        "head": "a" * 40, "files": [{"path": path, "added": 1, "removed": 1}],
        "diff": f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-Old\n+{'New text. ' * 55}\n",
        "number": 66, "url": "https://github.com/Xuefeng-Zhu/Hearth/pull/66", "status": "review", "checks": "pending",
        "guard": "hearth",
    }
    for width in (390, 1440):
        for scheme in ("light", "dark"):
            app.self_updates.store(proposal)
            with browser_page(browser, origin, viewport={"width": width, "height": 900}, color_scheme=scheme,
                              is_mobile=width == 390, has_touch=width == 390) as page:
                assert page.goto(f"/?thread={thread['id']}").ok
                expect(page).to_have_title("Hearth")
                card = page.get_by_role("region", name=proposal["title"])
                expect(card.get_by_text(proposal["summary"])).to_be_visible()
                expect(card.get_by_text(path, exact=True)).to_be_visible()
                expect(card.get_by_text(f"Head commit {proposal['head']}", exact=True)).to_be_visible()
                expect(card.get_by_text("+1", exact=True)).to_be_visible()
                expect(card.get_by_text("−1", exact=True)).to_be_visible()
                expect(card.get_by_role("link", name="Open PR #66")).to_have_attribute("href", proposal["url"])
                expect(card.get_by_text("CI · Tests running")).to_be_visible()
                expect(card.get_by_text("Waiting for tests", exact=True)).to_be_visible()
                expect(card.locator("pre")).to_be_hidden()
                card.locator("summary").click()
                expect(card.locator("pre")).to_be_visible()
                assert card.locator("pre").evaluate("(el) => el.scrollWidth > el.clientWidth")
                assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
                assert card.evaluate("(el) => el.scrollWidth === el.clientWidth")
                for control in card.locator("summary, button:visible, a:visible").all():
                    box = control.bounding_box()
                    assert box["height"] >= 44 and box["width"] >= 44, box
                contrast = card.evaluate("""(card) => {
                  const luminance = (value) => value.match(/[0-9.]+/g).slice(0, 3)
                    .map((n) => Number(n) / 255)
                    .map((n) => n <= 0.04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4)
                    .reduce((sum, n, i) => sum + n * [.2126, .7152, .0722][i], 0);
                  const surface = getComputedStyle(card).backgroundColor;
                  return [...card.querySelectorAll('h3, p:not([hidden]), li span:not(.self-update-counts), a:not([hidden]), summary, button:not([hidden])')]
                    .filter((el) => el.textContent && el.getClientRects().length)
                    .map((el) => {
                      const style = getComputedStyle(el);
                      const bg = style.backgroundColor === 'rgba(0, 0, 0, 0)' ? surface : style.backgroundColor;
                      const [a, b] = [luminance(bg), luminance(style.color)].sort((a, b) => a - b);
                      return [el.textContent, (b + .05) / (a + .05)];
                    });
                }""")
                assert all(ratio >= 4.5 for _, ratio in contrast), (width, scheme, contrast)
                screenshots = os.environ.get("HEARTH_SMOKE_SCREENSHOTS")
                if screenshots:
                    page.screenshot(path=Path(screenshots) / f"hearth-update-{width}-{scheme}.png")
                card.get_by_role("button", name="Request changes").click()
                feedback = card.get_by_role("textbox", name="What should change?")
                expect(feedback).to_be_focused()
                feedback.fill("Make the note shorter.")
                card.get_by_role("button", name="Cancel").click()
                expect(feedback).to_be_hidden()
                app.self_updates.store({**proposal, "status": "behind"})
                page.evaluate("window.dispatchEvent(new Event('focus'))")
                expect(card.get_by_role("button", name="Refresh proposal")).to_be_visible()
                expect(card.get_by_role("button", name="Approve and update")).to_be_hidden()
                app.self_updates.store({**proposal, "checks": "passed", "ready": True})
                page.evaluate("window.dispatchEvent(new Event('focus'))")
                expect(card.get_by_text("Ready to merge", exact=True)).to_be_visible()
                expect(card.get_by_text("Hearth's own checks: tests passed on an up-to-date branch")).to_be_visible()
                if screenshots:
                    page.screenshot(path=Path(screenshots) / f"hearth-update-ready-{width}-{scheme}.png")
                card.get_by_role("button", name="Approve and update").click()
                expect(card.get_by_text("Waiting for tests", exact=True)).to_be_visible()
                app.self_updates.store({**proposal, "status": "updated", "checks": "passed", "merge_sha": "b" * 40})
                page.evaluate("window.dispatchEvent(new Event('focus'))")
                expect(card.get_by_text("Hearth updated to bbbbbbb", exact=True)).to_be_visible()
                expect(card.get_by_text("Ask me to revert", exact=True)).to_be_visible()
                live = page.locator("#self-update-status")
                expect(live).to_have_text("Hearth updated to bbbbbbb")
                expect(live.locator("span")).to_have_count(1)
                expect(card.locator("pre")).to_be_visible()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disconnect", action="store_true", help="Run the SSE disconnect regression.")
    args = parser.parse_args()
    expect.set_options(timeout=5_000)
    with workspace() as (app, origin), sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--no-proxy-server"])
        try:
            if args.disconnect:
                disconnect(browser, app, origin)
            else:
                with workspace() as (layout_app, layout_origin):
                    layout_smoke(browser, layout_app, layout_origin)
                smoke(browser, origin)
                stale_refresh(browser, origin)
                self_update_smoke(browser, app, origin)
        finally:
            browser.close()
    print(f"Chromium {'stream disconnect' if args.disconnect else 'smoke'} passed.")


if __name__ == "__main__":
    main()
