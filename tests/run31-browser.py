"""Exercise parallel worker chat, approval, Home, Timeline, and Brain controls in Chromium."""

import argparse
import runpy
import threading
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

from hearth.server import HTTPServer
from hearth.storage import Storage
from test_workers import ASSIGNMENTS, WorkerGateway, fixture_app

CONTRAST = runpy.run_path(str(Path(__file__).with_name("run30-browser.py")))["CONTRAST"]
ASSIGNMENTS = [
    ASSIGNMENTS[0],
    {"title": "Playbook", "instructions": "Create the requested rehearsal skill.", "tools": ["skill_create"]},
    {"title": "Slow archive", "instructions": "Check the public archive.", "tools": []},
    {"title": "Slow records", "instructions": "Check the public records.", "tools": []},
]


def choose(page, label, mobile):
    if mobile:
        page.get_by_role("button", name="Open menu").click()
    region = page.locator("#workspace-drawer" if mobile else ".sidebar")
    region.get_by_role("button", name=label, exact=True).click()
    expect(page.get_by_role("heading", name=label, exact=True, level=1)).to_be_visible()


def verify(page, origin, width, theme, output):
    mobile = width == 390
    page.add_init_script('localStorage.setItem("hearth-avatar-view", "beside")')
    errors = []
    contrast = []

    def capture(name, selector):
        root = page.locator(selector)
        expect(root).to_be_visible()
        root.scroll_into_view_if_needed()
        ratios = root.evaluate(CONTRAST)
        assert ratios, name
        assert not [row for row in ratios if row["ratio"] + 0.005 < row["min"]], ratios
        contrast.extend(row["ratio"] for row in ratios)
        assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
        page.screenshot(path=output / f"{name}-{width}-{theme}.png", animations="disabled")

    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda event: errors.append(event.text) if event.type in ("error", "warning") else None)
    response = page.goto(origin, wait_until="domcontentloaded")
    assert response.status == 200 and page.title() == "Hearth" and page.url == origin + "/"
    choose(page, "Settings", mobile)
    page.get_by_role("button", name="Brain", exact=True).click()
    cap = page.get_by_label("Parallel workers")
    expect(cap).to_be_enabled()
    expect(cap).to_have_value("4")
    cap.select_option("2")
    page.locator("#brain-save").click()
    expect(page.get_by_text("Brain settings saved.")).to_be_visible()

    choose(page, "Chat", mobile)
    message = page.locator("#message")
    message.fill("Create a rehearsal skill and compare the sample grant notes with parallel workers.")
    message.press("Enter")
    card = page.get_by_role("region", name="Workers", exact=True)
    expect(card.get_by_text("Waiting for approval", exact=True)).to_be_visible()
    expect(card.get_by_text("Queued", exact=True)).to_be_visible()
    expect(card.get_by_text("Running", exact=True)).to_be_visible()
    expect(card.get_by_text("Done", exact=True)).to_be_visible()
    approval = page.locator("#chat-view .automation-approval")
    expect(approval.get_by_text("Worker · Playbook", exact=True)).to_be_visible()

    grant = card.locator("summary").filter(has_text="Grants")
    grant.focus()
    page.keyboard.press("Enter")
    expect(card.get_by_text("Reading a note", exact=True)).to_be_visible()
    capture("workers-running", "#chat-view .workers-card")

    choose(page, "Home", mobile)
    home = page.get_by_role("region", name="Running now")
    expect(home.get_by_text("Playbook", exact=True)).to_be_visible()
    expect(home.get_by_text("Slow records", exact=True)).to_be_visible()
    capture("workers-home", "#home-workers .workers-card")

    choose(page, "Chat", mobile)
    card.get_by_role("button", name="Stop Slow records", exact=True).click()
    expect(card.locator("summary").filter(has_text="Slow records")).to_contain_text("Stopped")
    approval.get_by_role("button", name="Approve", exact=True).click()
    expect(card.locator("summary").filter(has_text="Playbook")).to_contain_text("Done")
    card.get_by_role("button", name="Stop all workers").click()
    expect(card.locator("summary").filter(has_text="Slow archive")).to_contain_text("Stopped")
    expect(page.get_by_text("Combined findings", exact=True)).to_be_visible()
    expect(approval).to_contain_text("Completed")
    capture("workers-result", "#chat-view .workers-card")

    page.reload(wait_until="domcontentloaded")
    if not page.locator("#chat-view").is_visible():
        choose(page, "Chat", mobile)
    expect(card.locator("summary")).to_have_count(4)
    expect(card.get_by_role("button", name="Stop all workers")).to_be_hidden()

    choose(page, "Timeline", mobile)
    expect(page.locator(".timeline-entry").filter(has=page.get_by_text("Worker", exact=True))).to_have_count(4)
    choose(page, "Home", mobile)
    expect(home).to_be_hidden()
    assert not errors, errors
    print(f"{width} {theme} passed. Minimum sampled text contrast {min(contrast):.2f}:1.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--chromium")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.chromium)
        for width, height in [(390, 844), (1440, 1000)]:
            for theme in ["light", "dark"]:
                with TemporaryDirectory() as directory:
                    release = threading.Event()
                    app = fixture_app(Storage(directory), WorkerGateway(assignments=ASSIGNMENTS, hold=release))
                    with HTTPServer(("127.0.0.1", 0), app) as server:
                        serving = threading.Thread(target=server.serve_forever, daemon=True)
                        serving.start()
                        context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=theme,
                                                      is_mobile=width == 390, has_touch=width == 390)
                        try:
                            verify(context.new_page(), f"http://127.0.0.1:{server.server_port}", width, theme, args.output)
                        finally:
                            release.set()
                            context.close()
                            server.shutdown()
                            serving.join()
                            app.workers.executor.shutdown()
        browser.close()


if __name__ == "__main__":
    main()
