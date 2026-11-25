"""Exercise the structured Memory page in four viewport and theme combinations."""

import argparse
import re
import runpy
import threading
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import read_config
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage

PREVIOUS_FIXTURE = runpy.run_path(str(Path(__file__).with_name("run30-browser.py")))
CONTRAST = PREVIOUS_FIXTURE["CONTRAST"]
choose = PREVIOUS_FIXTURE["choose"]
FixtureGateway = PREVIOUS_FIXTURE["FixtureGateway"]


def verify(page, origin, width, theme, output, app):
    page.set_default_timeout(8000)
    errors = []
    contrast = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda event: errors.append(event.text) if event.type in {"error", "warning"} else None)
    response = page.goto(origin, wait_until="domcontentloaded")
    assert response.status == 200 and page.title() == "Hearth" and page.url == origin + "/"

    def capture(name):
        root = page.locator("#memory-view")
        ratios = root.evaluate(CONTRAST)
        assert ratios and not [row for row in ratios if row["ratio"] + 0.005 < row["min"]], ratios
        contrast.extend(row["ratio"] for row in ratios)
        assert root.evaluate("(element) => element.scrollWidth === element.clientWidth")
        assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
        page.screenshot(path=output / f"{name}-{width}-{theme}.png", animations="disabled")

    def tab(name):
        return page.get_by_role("tab", name=re.compile(rf"^{name}\b"))

    view = page.locator("#memory-view")
    choose(page, "Memory", width == 390)
    expect(view.get_by_role("heading", name="What Hearth knows about you")).to_be_visible()
    expect(tab("Profile")).to_have_attribute("aria-selected", "true")
    expect(view.get_by_label("Preferred name", exact=True)).to_have_value("Avery")
    capture("memory-profile")
    view.get_by_label("Preferred name", exact=True).fill("Avery Demo")
    view.get_by_role("button", name="Add address").click()
    view.get_by_label("Address ID").fill("demo-home")
    view.get_by_label("Label", exact=True).fill("Demo home")
    view.get_by_label("Address", exact=True).fill("1 Example Lane")
    view.get_by_role("button", name="Save profile").click()
    expect(view.get_by_role("status")).to_contain_text("Profile saved.")
    assert "Avery Demo" in app.storage.read("USER.md")

    tab("Profile").focus()
    page.keyboard.press("ArrowRight")
    expect(tab("People")).to_be_focused()
    expect(view.get_by_role("heading", name="Daniel", exact=True)).to_be_visible()
    view.get_by_role("button", name=re.compile("^Maya")).click()
    expect(view.get_by_text("She is vegetarian", exact=False)).to_be_visible()
    expect(view.get_by_role("heading", name="Related notes")).to_be_visible()
    capture("memory-people")
    view.get_by_role("button", name="Thanksgiving dinner", exact=True).click()
    expect(tab("Topics")).to_have_attribute("aria-selected", "true")
    expect(view.get_by_text("Plan to confirm the headcount", exact=False)).to_be_visible()
    tab("Places").click()
    expect(view.get_by_role("heading", name="Juniper Park", exact=True)).to_be_visible()
    tab("Daily").click()
    expect(view.get_by_text("Started planning Thanksgiving", exact=False)).to_be_visible()

    query = view.get_by_role("searchbox", name="Search memory")
    query.fill("vegetarian")
    query.press("Enter")
    result = view.locator("#memory-find-results")
    expect(result).to_contain_text("vegetarian")
    capture("memory-search")
    result.locator(".result-title").filter(has_text="people/maya.md").click()
    expect(view.locator(".is-highlighted").first).to_be_visible()
    query.fill("")

    view.get_by_role("button", name="Edit", exact=True).click()
    source = view.get_by_label("Markdown and front matter")
    source.fill(source.input_value() + "\n## Fixture note\n\nEnjoys Saturday walks.\n")
    view.get_by_role("button", name="Save note").click()
    expect(view.get_by_text("Enjoys Saturday walks.", exact=True)).to_be_visible()
    view.get_by_role("button", name="Rename", exact=True).click()
    view.get_by_label("New Markdown path").fill("people/maya-demo.md")
    page.once("dialog", lambda dialog: dialog.accept())
    view.get_by_role("button", name="Rename note").click()
    expect(view.get_by_text("people/maya-demo.md", exact=True)).to_be_visible()
    assert "people/maya-demo" in app.storage.read("USER.md")
    page.once("dialog", lambda dialog: dialog.accept())
    view.get_by_role("button", name="Delete", exact=True).click()
    expect(view.get_by_text("Daniel", exact=True).first).to_be_visible()
    assert "people/maya-demo.md" not in app.storage.files()
    choose(page, "Timeline", width == 390)
    removed = page.locator(".timeline-entry").filter(has_text="Memory forgotten")
    removed.get_by_role("button", name="Undo", exact=True).click()
    removed.get_by_role("button", name="Undo change").click()
    expect(page.get_by_text("Memory change undone.", exact=True)).to_be_visible()
    renamed = page.locator(".timeline-entry").filter(has_text="Memory renamed")
    renamed.get_by_role("button", name="Undo", exact=True).click()
    renamed.get_by_role("button", name="Undo change").click()
    expect(renamed.get_by_role("button", name="Redo", exact=True)).to_be_visible()
    assert "people/maya.md" in app.storage.files()
    assert "people/maya-demo.md" not in app.storage.files()
    assert not errors, errors
    print(f"{width} {theme} passed. Minimum sampled text contrast {min(contrast):.2f}:1.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--chromium")
    options = parser.parse_args()
    options.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=options.chromium)
        for width, height in [(390, 844), (1440, 1000)]:
            for theme in ["light", "dark"]:
                with TemporaryDirectory() as directory:
                    storage = Storage(directory)
                    config = read_config(ROOT / "config/connectors.json")
                    config["brain"] = {"provider": "mock", "model": ""}
                    app = Application(storage, LocalCheckpoints(storage), config, gateway=FixtureGateway())
                    with HTTPServer(("127.0.0.1", 0), app) as server:
                        serving = threading.Thread(target=server.serve_forever, daemon=True)
                        serving.start()
                        context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=theme,
                                                      is_mobile=width == 390, has_touch=width == 390)
                        try:
                            verify(context.new_page(), f"http://127.0.0.1:{server.server_port}", width, theme,
                                   options.output, app)
                        finally:
                            context.close()
                            server.shutdown()
                            serving.join()
                            app.workers.executor.shutdown()
        browser.close()


if __name__ == "__main__":
    main()
