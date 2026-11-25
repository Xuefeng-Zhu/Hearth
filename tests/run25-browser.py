"""Exercise Page artifacts and capture all four viewport/theme combinations."""

import argparse
import re
import threading
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

from hearth.browserbase import TEST_PATH
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import ConnectorError, read_config
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage
from test_pages import seed_legacy_page

NAV_ORDER = ["home", "chat", "timeline", "artifacts", "reminders", "inbox", "connections", "memory", "skills", "settings"]
FILES = {
    "Documents": ("docx", {"title": "Dinner notes", "sections": [{"paragraphs": ["Bring dessert."]}]}),
    "PDFs": ("pdf", {"title": "Dinner plan", "sections": [{"paragraphs": ["Dinner starts at 5 PM."]}]}),
    "Sheets": ("xlsx", {"title": "Shopping list", "sheets": [{"name": "Groceries", "headers": ["Item"], "rows": [["Pie"]]}]}),
    "Slides": ("pptx", {"title": "Menu", "slides": [{"title": "Dinner", "bullets": ["Roast squash"]}]}),
}


class DisconnectedGateway:
    def discover(self):
        return {}, set()

    def request(self, path, body, headers, timeout):
        assert path == f"browserbase/{TEST_PATH}"
        raise ConnectorError("No Browserbase connection.", 404, missing_connection=True)


Contrast = """() => {
  const rgb = value => (value.match(/[\\d.]+/g) || []).map(Number);
  const luminance = colors => colors.slice(0, 3).reduce((sum, value, index) => {
    const s = value / 255;
    return sum + [0.2126, 0.7152, 0.0722][index] * (s <= .04045 ? s / 12.92 : ((s + .055) / 1.055)**2.4);
  }, 0);
  const background = element => {
    for (let node = element; node; node = node.parentElement) {
      const color = rgb(getComputedStyle(node).backgroundColor);
      if (color.length === 3 || color[3] === 1) return color;
    }
    return [255, 255, 255];
  };
  return [...document.querySelectorAll('body *')].flatMap(element => {
    const text = [...element.childNodes].find(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
    if (!text || !element.checkVisibility()) return [];
    const style = getComputedStyle(element);
    const a = luminance(rgb(style.color)), b = luminance(background(element));
    const large = parseFloat(style.fontSize) >= (Number(style.fontWeight) >= 700 ? 18.67 : 24);
    return [{ text: text.textContent.trim(), ratio: (Math.max(a,b)+.05) / (Math.min(a,b)+.05), min: large ? 3 : 4.5 }];
  });
}"""


def go(page, name, mobile):
    if mobile:
        page.get_by_role("button", name="Open menu").click()
        scope = page.locator("#workspace-drawer")
    else:
        scope = page.locator(".sidebar")
    scope.get_by_role("button", name=name, exact=True).click()


def send(page, text):
    field = page.locator("#message")
    field.fill(text)
    field.press("Enter")


def verify(page, context, origin, width, theme, output):
    mobile = width == 390
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda event: errors.append(event.text) if event.type in ("error", "warning") else None)
    app_requests = []
    page.on("request", lambda request: app_requests.append(request.url))
    outcome = page.goto(origin + "/#pages", wait_until="domcontentloaded")
    assert outcome.status == 200 and page.title() == "Hearth"
    expect(page).to_have_url(origin + "/#artifacts/pages")
    expect(page.get_by_role("heading", name="Artifacts", exact=True)).to_be_visible()
    for scope in (".sidebar", "#workspace-drawer"):
        nav = page.locator(f"{scope} [data-view]")
        assert nav.evaluate_all("(items) => items.map(item => item.dataset.view)") == NAV_ORDER
        expect(page.locator(f'{scope} .workspace-settings [data-view="settings"]')).to_have_count(1)
    filters = page.get_by_role("group", name="Artifact type")
    assert filters.get_by_role("button").all_text_contents() == ["All", *FILES, "Pages"]
    expect(filters.get_by_role("button", name="Pages")).to_have_attribute("aria-pressed", "true")
    collection = page.locator("#artifact-collection")
    expect(collection.get_by_role("article")).to_have_count(1)
    expect(collection.get_by_role("button", name="Weekend market guide")).to_be_visible()
    filters.get_by_role("button", name="All", exact=True).click()
    expect(collection.get_by_role("article")).to_have_count(5)
    for category, (_, file) in FILES.items():
        filters.get_by_role("button", name=category, exact=True).click()
        expect(collection.get_by_role("article")).to_have_count(1)
        expect(collection.get_by_role("button", name=file["title"])).to_be_visible()
    page.go_back()
    expect(filters.get_by_role("button", name="Sheets")).to_have_attribute("aria-pressed", "true")
    page.go_forward()
    expect(filters.get_by_role("button", name="Slides")).to_have_attribute("aria-pressed", "true")
    filters.get_by_role("button", name="Documents").click()
    collection.get_by_role("button", name="Dinner notes").click()
    office = page.get_by_role("dialog", name="Dinner notes")
    expect(office.get_by_text("Bring dessert.")).to_be_visible()
    office.get_by_role("button", name="Close artifact").click()

    go(page, "Chat", mobile)
    legacy = page.locator("#transcript .chat-page-file").filter(has_text="Weekend market guide")
    expect(legacy).to_have_text(re.compile("Weekend market guidePage · v1"))
    legacy.click()
    expect(page.frame_locator("#page-preview-fit iframe").get_by_role("heading", name="Weekend market guide")).to_be_visible()
    page.get_by_role("button", name="Close page preview").click()
    expect(legacy).to_be_focused()
    page.locator("#message").focus()
    expect(page.locator("#message")).to_be_focused()
    send(page, "Make a page for our Thanksgiving dinner.")
    first = page.locator("#transcript .chat-page-file").filter(has_text="Thanksgiving dinner").filter(has_text="Page · v1")
    expect(first).to_be_visible(timeout=15000)
    first.click()
    preview = page.get_by_role("dialog", name="Thanksgiving dinner")
    expect(preview).to_be_visible()
    expect(page.frame_locator("#page-preview-fit iframe").get_by_role("heading", name="Thanksgiving dinner")).to_be_visible()
    page.get_by_role("button", name="Close page preview").click()
    expect(first).to_be_focused()
    send(page, "Make the header green.")
    latest = page.locator("#transcript .chat-page-file").filter(has_text="Page · v2")
    expect(latest).to_be_visible(timeout=15000)
    latest.click()
    expect(preview.get_by_text("Version 2 · Current")).to_be_visible()
    page.get_by_role("button", name="Close page preview").click()

    def capture(name):
        assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
        page.screenshot(path=output / f"run25-artifacts-{name}-{width}-{theme}.png", animations="disabled")

    go(page, "Home", mobile)
    recent = page.get_by_role("heading", name="Recent files").locator("..").locator("..")
    home_file = recent.get_by_role("button", name="Page Thanksgiving dinner")
    expect(home_file).to_be_visible()
    home_file.click()
    expect(preview.get_by_text("Version 2 · Current")).to_be_visible()
    page.get_by_role("button", name="Close page preview").click()
    expect(home_file).to_be_focused()
    go(page, "Artifacts", mobile)
    filters.get_by_role("button", name="Pages").click()
    expect(page).to_have_url(origin + "/#artifacts/pages")
    expect(collection.get_by_role("article")).to_have_count(2)
    page.get_by_role("button", name="List view").click()
    expect(collection).to_have_attribute("data-layout", "list")
    expect(collection.get_by_role("article")).to_have_count(2)
    page.get_by_role("button", name="Grid view").click()
    tile = collection.get_by_role("article").filter(has_text="Thanksgiving dinner")
    expect(tile.get_by_text("HTML / Page")).to_be_visible()
    expect(tile.get_by_text("v2")).to_be_visible()
    expect(tile.locator(".page-tile-art")).to_be_visible()
    expect(tile.locator("time")).to_have_attribute("datetime", re.compile(r"\d{4}-\d\d-\d\dT"))
    capture("pages")
    thumbnail = tile.locator(".page-tile-art").bounding_box()
    page.mouse.click(thumbnail["x"] + thumbnail["width"] / 2, thumbnail["y"] + thumbnail["height"] / 2)
    expect(preview.get_by_text("Version 2 · Current")).to_be_visible()
    generated = page.frame_locator("#page-preview-fit iframe")
    expect(preview.locator("iframe")).to_have_attribute("sandbox", "")
    expect(generated.get_by_role("heading", name="Thanksgiving dinner")).to_be_visible()
    expect(generated.get_by_text("Maya and Daniel", exact=False)).to_be_visible()
    expect(preview.get_by_role("button", name="Save HTML to Box")).to_be_visible()
    capture("detail")

    ratios = []
    for device, frame_width in (("Phone", 390), ("Desktop", 1440)):
        preview.get_by_role("button", name=device).click()
        expect(preview.get_by_role("button", name=device)).to_have_attribute("aria-pressed", "true")
        expect(preview.get_by_text(f"{frame_width} px")).to_be_visible()
        metrics = generated.locator("html").evaluate(
            """() => ({ width: innerWidth, overflow: document.documentElement.scrollWidth > innerWidth,
                  dark: matchMedia('(prefers-color-scheme: dark)').matches,
                  header: getComputedStyle(document.querySelector('header')).backgroundColor })"""
        )
        assert metrics == {"width": frame_width, "overflow": False, "dark": theme == "dark",
                           "header": "rgb(24, 59, 48)" if theme == "dark" else "rgb(36, 88, 70)"}, metrics
        contrast = generated.locator("html").evaluate(Contrast)
        assert contrast and all(row["ratio"] >= row["min"] for row in contrast), contrast
        ratios.extend(row["ratio"] for row in contrast)
        preview.evaluate("element => element.scrollTop = 0")

    artifacts = context.request.get(origin + "/api/artifacts").json()["artifacts"]
    identity = next(item["id"] for item in artifacts if item["title"] == "Thanksgiving dinner")
    old = preview.get_by_role("button", name="Preview version 1")
    old.click()
    expect(preview.get_by_text("Version 1", exact=True)).to_be_visible()
    expect(preview.get_by_role("link", name="Open in new tab")).to_have_attribute("href", f"/pages/{identity}/v/1")
    with page.expect_popup() as new_tab:
        preview.get_by_role("link", name="Open in new tab").click()
    expect(new_tab.value.get_by_role("heading", name="Thanksgiving dinner")).to_be_visible()
    new_tab.value.close()
    with page.expect_download() as downloaded:
        preview.get_by_role("link", name="Download .html").click()
    assert downloaded.value.suggested_filename == "Thanksgiving dinner.html"

    preview.get_by_role("button", name="Share link", exact=True).click()
    expect(preview.get_by_text("Share version 1?")).to_be_visible()
    expect(preview.get_by_role("link", name="Open public link")).to_have_count(0)
    preview.get_by_role("button", name="Approve share link").click()
    public_link = preview.get_by_role("link", name="Open public link")
    expect(public_link).to_be_visible()
    token = public_link.get_attribute("href")
    assert context.request.get(origin + token).status == 200
    preview.get_by_role("button", name="Revoke link").click()
    expect(preview.get_by_text("Share link revoked.")).to_be_visible()
    assert context.request.get(origin + token).status == 404

    preview.get_by_role("button", name="Restore v1").click()
    expect(preview.get_by_text("Version 3 · Current")).to_be_visible()
    expect(preview.get_by_text("Reverted to v1.")).to_be_visible()
    page.get_by_role("button", name="Close page preview").click()
    expect(tile.get_by_text("v3")).to_be_visible()
    expect(tile.get_by_role("button", name="Thanksgiving dinner")).to_be_focused()
    go(page, "Timeline", mobile)
    feed = page.locator("#timeline-view")
    expect(feed.get_by_text("Page created · Thanksgiving dinner", exact=True)).to_be_visible()
    restored = feed.locator(".timeline-entry").filter(has_text="Page updated · Thanksgiving dinner").first
    expect(restored).to_be_visible()
    restored.get_by_role("button", name="Undo", exact=True).click()
    restored.get_by_role("button", name="Undo change").click()
    expect(page.get_by_text("Page change undone.")).to_be_visible()
    assert context.request.get(origin + f"/api/artifacts/detail?id={identity}").json()["version_number"] == 2
    assert not errors, errors
    assert all(url.startswith(origin) for url in app_requests), app_requests
    print(f"{width} {theme}: routing, filters, Chat, Home, preview, sharing, download, restore and Undo passed. "
          f"Minimum sampled preview contrast {min(ratios):.2f}:1.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chromium")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.chromium)
        for width, height in ((390, 844), (1440, 1000)):
            for theme in ("light", "dark"):
                with TemporaryDirectory() as directory:
                    storage = Storage(directory)
                    config = read_config(ROOT / "config/connectors.json")
                    config["brain"] = {"provider": "mock", "model": ""}
                    app = Application(storage, LocalCheckpoints(storage), config, gateway=DisconnectedGateway())
                    seed_legacy_page(app)
                    for fmt, value in FILES.values():
                        app.artifacts.create(fmt, value)
                    with HTTPServer(("127.0.0.1", 0), app) as server:
                        worker = threading.Thread(target=server.serve_forever, daemon=True)
                        worker.start()
                        origin = f"http://127.0.0.1:{server.server_port}"
                        context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=theme,
                                                      is_mobile=width == 390, has_touch=width == 390)
                        try:
                            verify(context.new_page(), context, origin, width, theme, args.output)
                        finally:
                            context.close()
                            server.shutdown()
                            worker.join()
        browser.close()


if __name__ == "__main__":
    main()
