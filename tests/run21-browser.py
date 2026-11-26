"""Chromium regression checks and optional screenshots for Run 21."""

import argparse
import re
import threading
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

from hearth import office
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import read_config
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage
from test_uploads import image_bytes, pdf_bytes

STAMP = "2026-11-25T01:16:00+00:00"
ORDER = ["Home", "Chat", "Timeline", "Artifacts", "Reminders", "Inbox", "Memory", "Settings"]
BOOK = {"title": "Seattle travel budget", "sheets": [
    {"name": "Budget", "headers": ["TripExpenseCategory", "ProjectedCostInUSD",
                                  "DetailsForTravelPlanning", "ResponsiblePersonForPayment"],
     "rows": [["Ferry", 48, "Round trip", "Frank"], ["Lunch", 75, "Seafood", "Frank"]]}
]}


def write_fixtures(directory, photo):
    pdf = directory / "Library book club.pdf"
    pdf.write_bytes(pdf_bytes())
    book = directory / "Seattle travel budget.xlsx"
    book.write_bytes(office.generate("xlsx", office.prepare("xlsx", BOOK)))
    if photo is None:
        photo = directory / "Waterfront.png"
        photo.write_bytes(image_bytes())
    return [photo, pdf, book]


def seed(app):
    with app.storage.lock():
        thread = app.threads.create()["id"]
        app.threads.rename(thread, "Seattle trip")
        for title in ["Thanksgiving dinner", "Travel budget", "Book club", "Family plans", "Weekend errands"] * 4:
            sub = app.threads.create()
            app.threads.rename(sub["id"], title)
        app.threads.append(thread, "user", "Can you create a slide for Seattle trip?")
        reply = app.threads.append(thread, "assistant", "Here's your Seattle trip deck.", at=STAMP,
                                   routing={"provider": "mock", "model": "", "name": "Mock"})
    deck = app.artifacts.create("pptx", {"title": "Seattle trip", "subtitle": "Pike Place Market and Kerry Park",
                                         "slides": []}, origin={"thread_id": thread, "thread_title": "Seattle trip"})
    app.artifacts.bind([deck["id"]], thread, reply["id"])
    book = app.artifacts.create("xlsx", BOOK)
    with app.storage.lock():
        state = app.storage.load()
        state["artifacts"][book["id"]]["file_history"][0]["at"] = STAMP
        app.storage.save(state)
    return thread, book["id"]


def shot(page, output, name):
    if output:
        page.screenshot(path=output / f"run21-{name}.png", animations="disabled")


def test_navigation(page, mobile, output, label):
    if mobile:
        page.get_by_role("button", name="Open menu").click()
        sidebar = page.locator("#workspace-drawer")
        expect(sidebar).to_be_visible()
        settings = sidebar.get_by_role("button", name="Settings")
        edges = settings.bounding_box()
        assert edges["y"] > page.viewport_size["height"] - 80, edges
        drawer_body = sidebar.locator(".workspace-drawer-body")
        scrolled = drawer_body.evaluate("(e) => { e.scrollTop = 200; return e.scrollTop; }")
        assert scrolled > 0
        assert settings.bounding_box()["y"] == edges["y"]
        drawer_body.evaluate("(e) => e.scrollTop = 0")
    else:
        sidebar = page.locator(".sidebar")
        assert sidebar.get_by_role("button", name="Settings").bounding_box()["y"] > 780
    assert [text.strip() for text in sidebar.locator("nav button").all_text_contents()] == ORDER
    assert sidebar.locator('nav button svg[viewBox="0 0 24 24"][aria-hidden="true"][stroke-width="1.75"]').count() == len(ORDER)
    shot(page, output, f"nav-{label}")
    if mobile:
        sidebar.get_by_role("button", name="Close menu").click()


def test_preview(page, mobile, book, output, label):
    page.locator('[data-artifact-id="' + book + '"]').click()
    history = page.locator(".artifact-versions time")
    expect(history).to_have_text(re.compile(r"Nov 24,?\s+(at\s+)?5:16\s*PM"))
    assert history.get_attribute("datetime") == STAMP
    sheet = page.get_by_role("region", name="Budget spreadsheet")
    header = sheet.locator("th").first
    expect(header).to_have_text("TripExpenseCategory")
    if mobile:
        assert header.evaluate("""e => {
          const style = getComputedStyle(e);
          const text = new Range();
          text.selectNodeContents(e);
          return style.wordBreak === 'normal' && style.whiteSpace === 'nowrap' && text.getClientRects().length === 1;
        }""")
        assert sheet.evaluate("e => e.scrollWidth > e.clientWidth")
        sheet.evaluate("e => e.scrollLeft = 170")
        assert sheet.evaluate("e => e.scrollLeft") > 0
        sheet.evaluate("e => e.scrollLeft = 0")
        shot(page, output, f"xlsx-preview-{label}")
    page.get_by_role("button", name="Close artifact").click()


def test_actions(page, mobile, output, label):
    reply = page.locator(".message.assistant").filter(has_text="Here's your Seattle trip deck.").first
    expect(reply).to_be_visible()
    expect(reply.locator(".message-route time")).to_have_text(re.compile(r"5:16\s*PM"))
    assert not reply.locator(".message-body .message-menu, .message-body .share-message").count()
    toggle = reply.get_by_role("button", name="Helpful", exact=True)
    expected_size = 44 if mobile else 34
    assert toggle.bounding_box()["width"] == expected_size
    toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "true")
    expect(reply.get_by_role("button", name="Unhelpful")).to_have_attribute("aria-pressed", "false")
    reply.get_by_role("button", name="Copy").click()
    expect(page.get_by_role("status").filter(has_text=re.compile("^Copied$"))).to_be_visible()
    assert page.evaluate("navigator.clipboard.readText()") == "Here's your Seattle trip deck."
    expect(page.locator("#chat-toast")).to_be_hidden()
    user = page.locator(".message.user").first
    assert user.locator("button").count() == 0
    if mobile:
        user.tap()
    else:
        user.click(button="right")
    menu = page.get_by_role("dialog", name="Message actions")
    expect(menu.get_by_role("button", name="Share to Main")).to_be_visible()
    menu.get_by_role("button", name="Close message actions").click()
    if mobile:
        touch = page.context.new_cdp_session(page)
        bounds = user.bounding_box()
        point = {"x": bounds["x"] + bounds["width"] / 2, "y": bounds["y"] + bounds["height"] / 2}
        touch.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [point]})
        expect(menu).to_be_visible(timeout=1500)
        touch.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        touch.detach()
        expect(menu.get_by_role("button", name="Share to Main")).to_be_visible()
        menu.get_by_role("button", name="Close message actions").click()
    expect(page.locator(".header").get_by_role("button", name="Call Hearth")).to_be_visible()
    assert not page.locator("#composer #start-call").count()
    reply.scroll_into_view_if_needed()
    shot(page, output, f"chat-actions-{label}")


def test_attachments(page, fixtures, output, label):
    file_input = page.locator("#attachment-files")
    with page.expect_file_chooser() as dialog:
        page.get_by_role("button", name="Attach files").click()
    assert dialog.value.is_multiple()
    dialog.value.set_files(fixtures[:2])
    expect(page.locator('.attachment-chip[data-status="ready"]')).to_have_count(2)
    page.get_by_role("button", name="Remove Library book club.pdf").click()
    expect(page.locator(".attachment-chip")).to_have_count(1)
    for kind, filename, content_type, selector in (
        ("paste", fixtures[1], "application/pdf", "#message"),
        ("drop", fixtures[2], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".chat-pane"),
    ):
        page.locator(selector).evaluate("""(target, { kind, name, raw, mime }) => {
          const transfer = new DataTransfer();
          transfer.items.add(new File([new Uint8Array(raw)], name, { type: mime }));
          const event = kind === 'paste' ? new ClipboardEvent('paste', { bubbles: true, clipboardData: transfer })
            : new DragEvent('drop', { bubbles: true, dataTransfer: transfer });
          target.dispatchEvent(event);
        }""", {"kind": kind, "name": filename.name, "raw": list(filename.read_bytes()), "mime": content_type})
    expect(page.locator('.attachment-chip[data-status="ready"]')).to_have_count(3)
    expect(page.locator(".attachment-chip img")).to_be_visible()
    shot(page, output, f"attachments-composer-{label}")
    page.get_by_role("button", name="Send message").click()
    expect(page.locator(".attachment-card")).to_have_count(3)
    expect(page.locator(".message.assistant").filter(has_text="Demo PDF summary")).to_be_visible(timeout=15000)
    expect(page.locator(".attachment-sources button")).to_have_count(3)
    expect(page.locator(".composer-attachments")).to_be_hidden()
    page.reload()
    expect(page.locator(".attachment-card")).to_have_count(3)
    expect(page.locator(".attachment-thumbnail")).to_be_visible()
    page.get_by_role("button", name=f"Open {fixtures[0].name}").click()
    expect(page.locator(".attachment-preview")).to_be_visible()
    assert page.locator(".attachment-preview").evaluate("e => e.complete && e.naturalWidth > 0")
    page.get_by_role("button", name="Close artifact").click()
    page.locator(".attachment-cards").scroll_into_view_if_needed()
    shot(page, output, f"attachments-{label}")
    page.get_by_role("button", name=f"Open {fixtures[1].name}", exact=True).click()
    expect(page.locator(".artifact-pdf")).to_be_visible()
    page.get_by_role("button", name="Close artifact").click()
    page.get_by_role("button", name=f"Open {fixtures[2].name}", exact=True).click()
    expect(page.get_by_role("region", name="Budget spreadsheet")).to_be_visible()
    page.get_by_role("button", name="Close artifact").click()
    assert file_input.get_attribute("multiple") is not None


def run(options, directory):
    storage = Storage(directory / "data")
    app = Application(storage, LocalCheckpoints(storage), read_config(ROOT / "config/connectors.json"))
    thread, book = seed(app)
    fixtures = write_fixtures(directory, options.photo)
    with HTTPServer(("127.0.0.1", 0), app) as server, sync_playwright() as playwright:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_port}"
        browser = playwright.chromium.launch(executable_path=options.chromium)
        try:
            for width, height, mobile in [(1440, 900, False), (390, 844, True), (375, 812, True)]:
                for theme in ["light", "dark"]:
                    label = f"{width}-{theme}"
                    context = browser.new_context(
                        viewport={"width": width, "height": height},
                        color_scheme=theme, locale="en-US", timezone_id="UTC", reduced_motion="reduce",
                        is_mobile=mobile, has_touch=mobile, permissions=["clipboard-read", "clipboard-write"],
                    )
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(f"{base}/?thread={thread}")
                    expect(page.locator("#thread-title")).to_have_text("Seattle trip")
                    test_navigation(page, mobile, options.shots, label)
                    test_actions(page, mobile, options.shots, label)
                    if mobile:
                        page.get_by_role("button", name="Open menu").click()
                        page.locator("#workspace-drawer").get_by_role("button", name="Artifacts").click()
                    else:
                        page.locator(".sidebar").get_by_role("button", name="Artifacts").click()
                    test_preview(page, mobile, book, options.shots, label)
                    if mobile:
                        page.get_by_role("button", name="Open menu").click()
                        page.locator("#workspace-drawer").get_by_role("button", name="Chat", exact=True).click()
                    else:
                        page.locator(".sidebar").get_by_role("button", name="Chat", exact=True).click()
                    test_attachments(page, fixtures, options.shots, label)
                    assert not errors, errors
                    assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
                    context.close()
                    # Each browser configuration starts with the same side chat.
                    with storage.lock():
                        path = app.threads.path(thread)
                        path.write_text("\n".join(path.read_text().splitlines()[:2]) + "\n")
                    print(label, "passed", flush=True)
        finally:
            browser.close()
            server.shutdown()


if __name__ == "__main__":
    args = argparse.ArgumentParser()
    args.add_argument("--shots", type=Path)
    args.add_argument("--photo", type=Path)
    args.add_argument("--chromium")
    options = args.parse_args()
    if options.shots:
        options.shots.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="hearth-run21-browser-") as directory:
        run(options, Path(directory))
