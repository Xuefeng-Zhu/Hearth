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
                expect(card.get_by_text("+1", exact=True)).to_be_visible()
                expect(card.get_by_text("−1", exact=True)).to_be_visible()
                expect(card.get_by_role("link", name="Open PR #66")).to_have_attribute("href", proposal["url"])
                expect(card.get_by_text("CI · Tests running")).to_be_visible()
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
                smoke(browser, origin)
                stale_refresh(browser, origin)
                self_update_smoke(browser, app, origin)
        finally:
            browser.close()
    print(f"Chromium {'stream disconnect' if args.disconnect else 'smoke'} passed.")


if __name__ == "__main__":
    main()
