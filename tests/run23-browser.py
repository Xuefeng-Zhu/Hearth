"""Exercise the Pages UI and capture all four viewport/theme combinations."""

import argparse
import re
import threading
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import read_config
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage

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
    outcome = page.goto(origin, wait_until="domcontentloaded")
    assert outcome.status == 200 and page.title() == "Hearth" and page.url.rstrip("/") == origin
    nav = page.locator(".sidebar [data-view]")
    assert nav.evaluate_all("(items) => items.map(item => item.dataset.view)") == [
        "home", "chat", "timeline", "artifacts", "pages", "reminders", "inbox", "connections", "memory", "settings"
    ]
    go(page, "Pages", mobile)
    expect(page.get_by_role("heading", name="No pages yet")).to_be_visible()
    page.get_by_role("button", name="Build in Chat").click()
    expect(page.locator("#message")).to_be_focused()
    send(page, "Make a page for our Thanksgiving dinner.")
    first = page.locator(".page-chat-card").filter(has_text="v1")
    expect(first).to_be_visible(timeout=15000)
    first.click()
    preview = page.get_by_role("dialog", name="Thanksgiving dinner")
    expect(preview).to_be_visible()
    expect(page.frame_locator("#page-preview-fit iframe").get_by_role("heading", name="Thanksgiving dinner")).to_be_visible()
    page.get_by_role("button", name="Close page preview").click()
    expect(first).to_be_focused()
    send(page, "Make the header green.")
    latest = page.locator(".page-chat-card").filter(has_text="v2")
    expect(latest).to_be_visible(timeout=15000)

    def capture(name):
        page.screenshot(path=output / f"run23-{name}-{width}-{theme}.png", animations="disabled")

    capture("chat-card")
    go(page, "Pages", mobile)
    tile = page.locator(".page-tile")
    expect(tile).to_contain_text("Thanksgiving dinner")
    expect(tile.locator("time")).to_have_attribute("datetime", re.compile(r"\d{4}-\d\d-\d\dT"))
    capture("pages-list")
    tile.click()
    expect(preview.get_by_text("Version 2 · Current")).to_be_visible()
    generated = page.frame_locator("#page-preview-fit iframe")
    expect(preview.locator("iframe")).to_have_attribute("sandbox", "")
    expect(generated.get_by_role("heading", name="Thanksgiving dinner")).to_be_visible()
    expect(generated.get_by_text("Maya and Daniel", exact=False)).to_be_visible()

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
        capture("preview-" + device.lower())

    details = context.request.get(origin + "/api/pages").json()["pages"][0]
    identity = details["id"]
    old = preview.get_by_role("button", name="Preview version 1")
    old.click()
    expect(preview.get_by_text("Version 1", exact=True)).to_be_visible()
    expect(preview.get_by_role("link", name="Open in new tab")).to_have_attribute("href", f"/pages/{identity}/v/1")
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
    go(page, "Timeline", mobile)
    restored = page.locator(".timeline-entry").filter(has_text="Restored page · Thanksgiving dinner")
    expect(restored).to_be_visible()
    restored.get_by_role("button", name="Undo", exact=True).click()
    restored.get_by_role("button", name="Undo change").click()
    expect(page.get_by_text("Page change undone.")).to_be_visible()
    assert context.request.get(origin + "/api/pages").json()["pages"][0]["version"] == 2
    assert not errors, errors
    assert all(url.startswith(origin) for url in app_requests), app_requests
    print(f"{width} {theme}: page/card/preview/share/download/revert/undo passed. Minimum sampled page contrast {min(ratios):.2f}:1.")


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
                    app = Application(storage, LocalCheckpoints(storage), config)
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
