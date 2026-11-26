"""Exercise Settings → Skills in Chromium across desktop and mobile themes."""

import argparse
import re
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright

from hearth.agent import tool_call
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import ConnectorError, read_config
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage
from test_skills import Disconnected, playbook

NAV = ["home", "chat", "timeline", "artifacts", "reminders", "inbox", "memory", "settings"]
DINNER = "Plan a dinner party"
CHAT_SKILL = "Water the seedlings"
CONTRAST = """(root) => {
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
  return [...root.querySelectorAll("*")].flatMap(element => {
    const style = getComputedStyle(element);
    const text = element.matches("textarea, select") ? element.value
      : [...element.childNodes].find(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim())?.textContent;
    if (!text || !element.checkVisibility() || element.tagName === "OPTION" || element.className === "visually-hidden") return [];
    const a = luminance(rgb(style.color)), b = luminance(background(element));
    const large = parseFloat(style.fontSize) >= (Number(style.fontWeight) >= 700 ? 18.67 : 24);
    return [{text, ratio: (Math.max(a,b)+.05) / (Math.min(a,b)+.05), min: large ? 3 : 4.5}];
  });
}"""


class FixtureGateway(Disconnected):
    def request(self, path, body, headers, timeout, *, method=None):
        raise ConnectorError("No connection in the browser fixture.", 404, missing_connection=True)


def fixture_completion(model, messages, tools, emit):
    available = {tool["function"]["name"] for tool in tools}
    if messages[-1]["role"] == "tool":
        return {"role": "assistant", "content": "Check the soil before watering."}
    if "skill_create" in available:
        return tool_call("skill_create", {"name": CHAT_SKILL, "description": "Check and water seedlings.",
                                         "content": "1. Check the soil before watering."})
    raise AssertionError("Unexpected fixture model call")


def choose(page, label, mobile):
    if mobile:
        page.get_by_role("button", name="Open menu").click()
    region = page.locator("#workspace-drawer" if mobile else ".sidebar")
    region.get_by_role("button", name=label, exact=True).click()
    expect(page.get_by_role("heading", name=label, exact=True, level=1)).to_be_visible()


def open_skills(page, mobile):
    choose(page, "Settings", mobile)
    section = page.locator('[data-settings="skills"]')
    expect(section.locator("svg")).to_have_count(2)
    section.click()


def verify(page, origin, width, theme, output, app):
    mobile = width < 760
    page.add_init_script('localStorage.setItem("hearth-avatar-view", "beside")')
    errors = []
    captures = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda event: errors.append((event.text, event.location.get("url")))
            if event.type in ("error", "warning") else None)
    response = page.goto(origin, wait_until="domcontentloaded")
    assert response.status == 200 and page.title() == "Hearth" and page.url == origin + "/"
    for scope in (".sidebar", "#workspace-drawer"):
        assert page.locator(f"{scope} [data-view]").evaluate_all("(items) => items.map(item => item.dataset.view)") == NAV

    def capture(name, root):
        rules = page.locator(root).evaluate(CONTRAST)
        assert rules, root
        failures = [row for row in rules if row["ratio"] + 0.005 < row["min"]]
        assert not failures, failures
        captures.extend(row["ratio"] for row in rules)
        assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
        page.screenshot(path=output / f"{name}-{width}-{theme}.png", animations="disabled")

    page.goto(origin + "/#skills")
    expect(page).to_have_url(origin + "/#settings/skills")
    expect(page.get_by_role("heading", name="Settings", level=1)).to_be_visible()
    expect(page.locator('[data-settings="skills"]')).to_have_attribute("aria-expanded", "true")
    dinner = page.get_by_role("button", name=DINNER, exact=True)
    expect(dinner).to_be_visible()
    expect(page.locator(".skill-badge")).to_have_count(4)
    expect(page.get_by_text("Never used", exact=True)).to_have_count(4)
    capture("skills-library", "#settings-skills")

    dinner.focus()
    page.keyboard.press("Enter")
    editor = page.get_by_role("dialog", name=DINNER, exact=True)
    expect(editor).to_be_visible()
    expect(editor.get_by_role("button", name="Close skill editor")).to_be_focused()
    expect(editor.get_by_role("region", name="Markdown preview")).to_contain_text("known allergies")
    expect(editor.get_by_role("button", name="Save skill")).to_be_hidden()
    capture("skills-built-in", "#skill-editor")
    editor.get_by_role("button", name="Markdown", exact=True).click()
    expect(editor.get_by_role("textbox", name="Skill Markdown")).to_have_attribute("readonly", "")
    page.keyboard.press("Escape")
    expect(dinner).to_be_focused()

    page.get_by_role("button", name="New skill").click()
    editor = page.locator("#skill-editor")
    source = editor.get_by_role("textbox", name="Skill Markdown")
    expect(source).to_be_focused()
    source.fill(playbook(body="## Before leaving\n\n- Pack boots."))
    editor.get_by_role("button", name="Preview").click()
    expect(editor.get_by_role("heading", name="Before leaving")).to_be_visible()
    expect(editor.get_by_text("Pack boots.", exact=True)).to_be_visible()
    editor.get_by_role("button", name="Save skill").click()
    expect(editor.get_by_role("status")).to_have_text("Skill saved.")
    editor.get_by_role("button", name="Markdown", exact=True).click()
    source.fill(playbook(body="## Before leaving\n\n- Pack boots and a rain jacket."))
    editor.get_by_role("button", name="Save skill").click()
    history = editor.get_by_label("Version history")
    expect(history.locator("option").first).to_have_text("Version 2 · Current")
    capture("skills-editor", "#skill-editor")
    history.select_option(index=1)
    expect(source).to_have_value(re.compile(r"Pack boots\.$", re.M))
    expect(source).to_have_attribute("readonly", "")
    history.select_option(index=0)
    expect(source).to_have_value(re.compile("rain jacket"))
    editor.get_by_role("button", name="Delete", exact=True).click()
    expect(editor.get_by_role("button", name="Cancel")).to_be_focused()
    editor.get_by_role("button", name="Cancel").click()
    expect(editor.get_by_role("button", name="Delete", exact=True)).to_be_focused()
    editor.get_by_role("button", name="Delete", exact=True).click()
    editor.get_by_role("button", name="Delete skill").click()
    expect(editor).to_be_hidden()
    expect(page.get_by_role("button", name="Pack for camp")).to_have_count(0)
    choose(page, "Timeline", mobile)
    change = page.locator(".timeline-entry").filter(has_text="Skill deleted · Pack for camp")
    change.get_by_role("button", name="Undo", exact=True).click()
    expect(change.get_by_text("Undo this skill change?")).to_be_visible()
    change.get_by_role("button", name="Undo change").click()
    expect(change.get_by_text("Undone", exact=True)).to_be_visible()

    open_skills(page, mobile)
    expect(page.get_by_role("button", name="Pack for camp")).to_be_visible()
    dinner.click()
    editor.get_by_role("button", name="Duplicate to edit").click()
    expect(editor.get_by_role("heading", name=f"{DINNER} (copy)", exact=True)).to_be_visible()
    expect(source).to_be_editable()
    editor.get_by_role("button", name="Close skill editor").click()
    dinner.click()
    editor.get_by_role("button", name="Try it").click()
    expect(page.get_by_text(f"Skill ready: {DINNER}")).to_be_visible()
    message = page.locator("#message")
    message.fill("Make a menu for four this Saturday.")
    page.get_by_role("button", name="Send message").click()
    chip = page.locator("#transcript").get_by_role("link", name=f"Using skill: {DINNER}", exact=True)
    expect(chip).to_be_visible()
    expect(chip.locator("svg")).to_have_count(1)
    expect(chip).to_have_attribute("href", "#settings/skills/plan-dinner-party")
    expect(page.get_by_text("Confirm allergies and quantities before shopping.", exact=False)).to_be_visible()
    expect(page.get_by_role("heading", name="Shopping list", exact=True)).to_be_visible()
    expect(page.get_by_text(re.compile(r"^XLSX · "))).to_be_visible()
    capture("skills-chat", "#transcript")
    page.reload(wait_until="domcontentloaded")
    choose(page, "Chat", mobile)
    expect(chip).to_be_visible()
    chip.press("Enter")
    expect(page).to_have_url(origin + "/#settings/skills/plan-dinner-party")
    expect(editor).to_be_visible()
    page.go_back()
    expect(chip).to_be_visible()
    expect(editor).to_be_hidden()
    page.go_forward()
    expect(editor).to_be_visible()
    page.reload()
    expect(editor).to_be_visible()
    editor.get_by_role("button", name="Close skill editor").click()
    expect(page).to_have_url(origin + "/#settings/skills")
    expect(dinner).to_be_focused()
    dinner_card = dinner.locator("xpath=ancestor::article")
    expect(dinner_card.get_by_text("1 use", exact=True)).to_be_visible()
    expect(dinner_card.locator("time")).to_have_attribute("datetime", re.compile(r"^\d{4}-\d{2}-\d{2}T"))

    choose(page, "Settings", mobile)
    approvals = page.get_by_role("button", name="Approvals", exact=True)
    approvals.click()
    policy = page.locator("#approval-settings-form").get_by_label("Skills", exact=True)
    expect(policy).to_have_value("ask")
    policy.select_option("allow")
    page.locator("#approval-settings-form").get_by_role("button", name="Save settings").click()
    expect(page.locator("#approval-settings-feedback")).to_have_text("Settings saved.")
    assert app.storage.load()["approval_policy"]["skills"] == "allow"
    policy.select_option("ask")
    page.locator("#approval-settings-form").get_by_role("button", name="Save settings").click()
    expect(policy).to_have_value("ask")
    choose(page, "Chat", mobile)
    # Return to Main so this request can propose a new playbook outside the pinned scope.
    if mobile:
        page.get_by_role("button", name="Open menu").click()
        page.locator("#workspace-drawer").get_by_role("button", name="Main", exact=True).click()
    else:
        page.locator("#chat-view").get_by_role("button", name="Main", exact=True).click()
    original_models = app.agent.models
    app.agent.models = [{"provider": "test-brain", "model": "fixture"}]
    try:
        with patch.object(app.agent, "model_completion", side_effect=fixture_completion):
            message.fill("Save a skill called Water the seedlings.")
            page.get_by_role("button", name="Send message").click()
            card = page.locator(".automation-approval").filter(has_text=f"Create skill · {CHAT_SKILL}")
            expect(card.get_by_text("Needs approval")).to_be_visible()
            card.get_by_text("Review proposed Markdown").click()
            expect(card.get_by_text("Check the soil before watering.", exact=False).first).to_be_visible()
            assert all(row["name"] != CHAT_SKILL for row in app.agent.skills.list())
            card.get_by_role("button", name="Approve", exact=True).click()
            expect(page.get_by_text(f"Skill created · {CHAT_SKILL}", exact=False).first).to_be_visible()
    finally:
        app.agent.models = original_models
    assert any(row["name"] == CHAT_SKILL for row in app.agent.skills.list())
    assert not errors, errors
    print(f"{width} {theme}: navigation, edit/preview, versions, delete/Undo, duplicate, Try it, and chat approval. "
          f"Minimum sampled text contrast {min(captures):.2f}:1.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--chromium")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.chromium)
        for width, height in ((375, 812), (390, 844), (1440, 1000)):
            for theme in ("light", "dark"):
                with TemporaryDirectory() as directory:
                    storage = Storage(directory)
                    config = read_config(ROOT / "config/connectors.json")
                    config["brain"] = {"provider": "mock", "model": ""}
                    app = Application(storage, LocalCheckpoints(storage), config, gateway=FixtureGateway())
                    with HTTPServer(("127.0.0.1", 0), app) as server:
                        worker = threading.Thread(target=server.serve_forever, daemon=True)
                        worker.start()
                        context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=theme,
                                                      is_mobile=width < 760, has_touch=width < 760)
                        try:
                            verify(context.new_page(), f"http://127.0.0.1:{server.server_port}", width, theme, args.output, app)
                        finally:
                            context.close()
                            server.shutdown()
                            worker.join()
        browser.close()


if __name__ == "__main__":
    main()
