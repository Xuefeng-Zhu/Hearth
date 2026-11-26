"""Audit the workspace in WebKit with disposable, fictional data."""
import argparse
import json
import runpy
import threading
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright

from hearth import proactivity, tasks
from hearth.agent import DEMO_FILES
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import ConnectorError, read_config
from hearth.proactive_context import Context
from hearth.server import Application, HTTPServer
from hearth.storage import ROOT, Storage, iso
from hearth.threads import MAIN_ORIGIN

HERE = Path(__file__).parent
CONTRAST_FIXTURE = runpy.run_path(str(HERE / "contrast-fixture.py"))
HOME_FIXTURE = runpy.run_path(str(HERE / "run22-browser.py"))
THREADS = runpy.run_path(str(HERE / "run38-browser.py"))["THREADS"]
CONTRAST = "function " + (HERE / "contrast-pairs.mjs").read_text().split("export function ", 1)[1]
SETTINGS = ("brain", "memory", "search", "voice", "connections", "artifacts", "reminders",
            "feed", "proactivity", "automations", "watchers", "approvals", "home", "appearance")
SIZES = (("iPhone SE", 375, 667), ("iPhone 13", 390, 844), (None, 1440, 1000))
OFFER = {
    "id": "sample-offer", "title": "Prepare for Saturday’s garden workshop",
    "why": "The weather may change and there is still time to make a rain plan.",
    "kind": "planning", "urgency": "soon", "action_label": "Make a rain plan",
    "expires_at": "2030-04-04T17:00:00Z",
}


def seed_offer(app, state, now):
    source = "memory:topics/seattle.md"
    context = Context(app, state)
    row, = proactivity.candidates([{
        **OFFER, "dedupe_key": "sample-offer", "expiry_hours": 24, "sources": [source],
        "action": {"type": "chat", "label": OFFER["action_label"], "prompt": "Draft a weekend rain plan."},
    }], {source: context.get(source)}, {}, context.rules, 1, now)
    state.setdefault("proactivity", {}).setdefault("cards", {})[row["id"]] = row


# Intrinsically wide tables, PDF sheets and authored preview frames have their own local scrolling.
# Inspect scroll containers as well as the root, since a clipped pane can hide a layout regression.
GEOMETRY = r"""() => {
  const modal = [...document.querySelectorAll('dialog:modal')].at(-1);
  const scope = modal || document.querySelector('main');
  const visible = el => el.getClientRects().length && el.checkVisibility({visibilityProperty: true})
    && !el.closest('.visually-hidden, [hidden], [inert]');
  const name = el => el.id ? '#' + el.id : el.tagName.toLowerCase() + '.' + (el.classList[0] || '')
    + ' ' + (el.getAttribute('aria-label') || el.textContent.trim()).replace(/\s+/g, ' ').slice(0, 55);
  const containers = [document.documentElement, scope, ...scope.querySelectorAll(
    '.view, .chat-pane, .chat-scroll, .transcript, .composer, .workspace-drawer-body, .threads, '
    + '.artifact-drawer-body, .skill-editor-body, .connection-tabs, .settings-body, .notice')];
  const overflow = containers.filter(el => visible(el) && el.scrollWidth - el.clientWidth > 1)
    .map(el => [name(el), el.scrollWidth - el.clientWidth]);
  const targets = [...scope.querySelectorAll('button, summary, select, textarea, a[href], input')]
    .filter(el => visible(el) && !el.matches(':disabled, [aria-disabled=true], input[type=hidden]'))
    .filter(el => !el.matches('a') || !el.closest('.chat-markdown, .markdown, .connection-guidance'))
    .map(el => el.matches('input[type=checkbox], input[type=radio]') && el.labels?.length ? el.labels[0] : el);
  const small = [...new Set(targets)].map(el => [el, el.getBoundingClientRect()])
    .filter(([, rect]) => Math.min(rect.width, rect.height) < 43.5)
    .map(([el, rect]) => [name(el), Math.round(rect.width), Math.round(rect.height)]);
  return { overflow, small };
}"""


class AuditGateway(CONTRAST_FIXTURE["ContrastGateway"]):
    def json(self, config, path, *args, **kwargs):
        if path == "search":
            raise ConnectorError("The connector check failed.", 503)
        return super().json(config, path, *args, **kwargs)


def seed(app, gateway):
    CONTRAST_FIXTURE["seed"](app, gateway)
    now = datetime.now(timezone.utc)
    with app.storage.lock():
        for title in THREADS:
            app.threads.create(title=title)
        action = next(a for a in app.storage.load()["actions"].values() if a["kind"] == "email")
        prompt = app.threads.append("main", "user", "Confirm the dinner headcount and prepare an invitation.")
        app.threads.append("main", "assistant",
                           "I drafted an invitation and checked the itinerary.\n\n"
                           "**Before sending:** confirm the venue, dietary needs, and the RSVP deadline.",
                           action_ids=[action["id"]], worker_turn_id=prompt["id"])
        app.threads.append("main", "assistant",
                           "Reference: " + "GardenWorkshopSchedule" * 12 + "\n\n" + ("The group will meet near the main entrance. " * 46))
        state = app.storage.load()
        seed_offer(app, state, now)
        state.setdefault("workers", {})["fictional-worker"] = {
            "id": "fictional-worker", "thread_id": "main", "turn_id": prompt["id"],
            "status": "running", "title": "Compare community garden workshop schedules",
            "started_at": iso(now), "steps": [{"label": "Review the sample itinerary", "status": "running"}],
            "summary": "Checking the venue schedule and the rain plan.",
        }
        app.storage.save(state)
    for index in range(11):
        detail = {key: value for key, value in DEMO_FILES["pdf"][1].items() if key != "kind"}
        detail["title"] = f"Community garden workshop checklist {index + 1}"
        app.artifacts.create("pdf", detail, origin=MAIN_ORIGIN)
    app.pages.save("Community garden workshop", "<html><head><title>Workshop plan</title></head>"
                   "<body><h1>Workshop plan</h1><p>Bring gloves and a water bottle.</p></body></html>",
                   "First outline", MAIN_ORIGIN)
    app.home.refresh_weather(now)
    task = tasks.mutate(app.storage, "create", {
        "name": "Weekly garden workshop brief", "instruction": "Review the workshop and rain plan.",
        "schedule": {"type": "weekly", "days": [5], "time": "09:00"},
    }, clock=now)
    with app.storage.lock():
        state = app.storage.load()
        state.setdefault("task_runs", {})["fixture-run"] = {
            "id": "fixture-run", "task_id": task["id"], "thread_id": "main",
            "status": "complete", "started_at": iso(now), "duration_ms": 550, "attempts": 1,
            "output": "The volunteers are confirmed. Bring gloves and a water bottle.",
        }
        app.storage.save(state)


def go(page, name):
    mobile = page.locator("#open-menu").is_visible()
    if mobile:
        page.locator("#open-menu").click()
    scope = "#workspace-drawer" if mobile else ".sidebar"
    page.locator(f'{scope} [data-view="{name}"]').click()
    expect(page.locator(f"#{name}-view")).to_be_visible()


def setting(page, name):
    button = page.locator(f'[data-settings="{name}"]')
    if button.get_attribute("aria-expanded") != "true":
        button.click()
    expect(page.locator(f"#settings-{name}")).to_be_visible()


def close_modal(page, selector):
    if page.locator(selector).is_visible():
        page.keyboard.press("Escape")
        expect(page.locator(selector)).to_be_hidden()


def keyboard_preview(page, capture, baseline):
    original = page.locator(".layout").bounding_box()
    page.locator("#message").focus()
    page.locator("#message").fill("A multiline draft\n" * 12)
    page.evaluate("""() => {
      const viewport = window.visualViewport;
      Object.defineProperties(viewport, {
        height: {configurable: true, value: 350},
        offsetTop: {configurable: true, value: 18},
      });
      viewport.dispatchEvent(new Event('resize'));
    }""")
    expect(page.locator("html")).to_have_attribute("data-keyboard", "")
    capture("chat-keyboard")
    if not baseline:
        for selector in ("#message", "#send", "#mic", "#attach"):
            bounds = page.locator(selector).bounding_box()
            assert bounds["y"] >= 18 and bounds["y"] + bounds["height"] <= 369, bounds
    page.locator("#message").fill("")
    page.locator("#message").blur()
    page.evaluate("""() => {
      delete visualViewport.height;
      delete visualViewport.offsetTop;
      visualViewport.dispatchEvent(new Event('resize'));
    }""")
    expect(page.locator("html")).not_to_have_attribute("data-keyboard", "")
    assert page.locator(".layout").bounding_box() == original


def verify_threads(page, app, mobile, capture):
    if mobile:
        page.locator("#open-menu").click()
    thread = next(item for item in app.threads.list() if item["title"] == "Seattle notes")
    identity = thread["id"]
    row = page.locator(f'.thread-link[data-thread="{identity}"]')
    expect(row.locator(".mascot, .thread-dot")).to_have_count(0)
    expect(page.locator("#threads .mascot")).to_have_count(0)
    with app.turn_lock:
        app.turns[identity] = None
    try:
        expect(row).to_have_accessible_name("Seattle notes · Working", timeout=6500)
        expect(row.locator(".thread-dot")).to_have_attribute("data-status", "working")
        expect(page.locator("#thread-list-status")).to_contain_text("Seattle notes: Working")
        capture("thread-working")
        with app.storage.lock():
            app.threads.append(identity, "assistant", "The workshop is booked for Saturday.")
    finally:
        with app.turn_lock:
            del app.turns[identity]
    expect(row).to_have_accessible_name("Seattle notes · Unread reply", timeout=6500)
    expect(row.locator(".thread-dot")).to_have_attribute("data-status", "unread")
    expect(page.locator("#thread-list-status")).to_contain_text("Seattle notes: Unread reply")
    capture("thread-unread")
    row.click()
    expect(page.locator("#transcript")).to_contain_text("The workshop is booked for Saturday.")
    if mobile:
        expect(page.locator("#thread-title")).to_be_focused()
        page.locator("#open-menu").click()
    expect(row).to_have_accessible_name("Seattle notes")
    expect(row.locator(".thread-dot")).to_have_count(0)
    if mobile:
        close_modal(page, "#workspace-drawer")


def verify(context, origin, tag, output, baseline, app):
    page = context.new_page()
    page.add_init_script("Object.defineProperty(navigator, 'clipboard', {value: {writeText: async () => {}}})")
    page.set_default_timeout(6500)
    errors, findings = [], []
    low_contrast = {}
    contrast_measurements = 0
    page.on("pageerror", lambda error: errors.append(str(error)))
    mobile = page.viewport_size["width"] == 375 or page.viewport_size["width"] == 390

    assert page.goto(origin).ok

    def capture(name):
        nonlocal contrast_measurements
        result = page.evaluate(GEOMETRY)
        if result["overflow"] or (mobile and result["small"]):
            findings.append({"state": name, "overflow": result["overflow"], "small": result["small"] if mobile else []})
        pairs = page.evaluate(CONTRAST, {"dark": tag.endswith("-dark"), "allControls": True})
        assert pairs, name
        contrast_measurements += len(pairs)
        for pair in pairs:
            if pair["ratio"] + .005 < pair["threshold"]:
                key = (pair["element"], pair["colors"], pair["threshold"])
                low_contrast.setdefault(key, {"state": name, **pair})
        if output:
            page.screenshot(path=output / f"{name}-{tag}.png", animations="disabled")

    expect(page.locator(".suggestion-card").first if baseline else page.get_by_role(
        "article", name=OFFER["title"])).to_be_visible()
    capture("home")
    health = page.locator('[data-panel="connections"]')
    health.scroll_into_view_if_needed()
    capture("home-health")
    page.locator("#home-edit").click()
    capture("home-layout")
    if not baseline:
        expect(page.get_by_role("button", name="Make a rain plan")).to_be_visible()
    page.locator("#home-edit").click()
    if mobile:
        page.locator("#open-menu").click()
        expect(page.locator(".thread-link")).to_have_count(len(THREADS) + 2)
        capture("drawer")
        close_modal(page, "#workspace-drawer")
        expect(page.locator("#open-menu")).to_be_focused()
        if not baseline:
            page.locator("#open-menu").click()
            page.get_by_role("link", name="Check connections").click()
            expect(page.locator("#settings-connections")).to_be_visible()
            expect(page.locator('[data-settings="connections"]')).to_be_focused()
    go(page, "chat")
    expect(page.locator(".chat-markdown table")).to_be_visible()
    capture("chat")
    page.get_by_role("link", name="Using skill: Research and compare").scroll_into_view_if_needed()
    capture("chat-files-skill")
    if mobile:
        page.locator("#open-menu").click()
    more = page.locator(".thread-overflow:visible").first
    if more.count():
        more.click()
        capture("thread-menu")
        close_modal(page, "#thread-menu")
    if mobile:
        close_modal(page, "#workspace-drawer")
    page.locator("#transcript .workers-card .worker-summary").first.click()
    capture("chat-workers-stop")
    page.locator("#transcript").get_by_text("Seattle itinerary", exact=False).first.scroll_into_view_if_needed()
    capture("chat-approval")
    page.locator(".message.assistant").first.press("Enter")
    expect(page.locator("#message-menu")).to_be_visible()
    capture("message-menu")
    page.get_by_role("button", name="Copy", exact=True).last.click()
    expect(page.locator("#chat-toast")).to_have_text("Copied")
    capture("toast")
    page.locator("#attachment-files").set_input_files({
        "name": "community-garden-workshop-notes.txt", "mimeType": "text/plain", "buffer": b"Bring gloves.",
    })
    expect(page.locator("#composer-attachments")).to_be_visible()
    capture("chat-attachment")
    if mobile:
        keyboard_preview(page, capture, baseline)
    page.locator("#mic").click()
    capture("chat-voice")
    page.keyboard.press("Escape")
    page.locator("#start-call").click()
    expect(page.locator("#call-sheet")).to_be_visible()
    expect(page.locator("#call-captions li").first).to_be_visible(timeout=12000)
    capture("call")
    page.keyboard.press("Escape")
    if page.locator("#call-done").is_visible():
        page.locator("#call-done").click()
    close_modal(page, "#call-sheet")

    go(page, "timeline")
    if not baseline:
        expect(page.locator("#notice")).to_be_hidden()
        if mobile:
            expect(page.locator("#view-title")).to_be_focused()
    first = page.locator(".timeline-card-head").first
    expect(first).to_be_visible()
    capture("timeline")
    first.click()
    capture("timeline-expanded")
    page.locator("#timeline-search").fill("no matching activity fixture")
    expect(page.locator(".timeline-empty")).to_be_visible()
    capture("timeline-empty")
    go(page, "artifacts")
    expect(page.locator(".artifact-card")).to_have_count(16)
    capture("artifacts")
    if not baseline:
        ask_files = page.get_by_role("button", name="Ask my files")
        ask_files.click()
        dialog = page.get_by_role("dialog", name="Ask my files")
        expect(dialog.get_by_text("Connect Box in Settings to ask about your files.")).to_be_visible()
        expect(dialog.get_by_text("Answered by Hearth from your Box files")).to_have_count(0)
        expect(dialog.get_by_role("button", name="Ask Hearth")).to_be_disabled()
        capture("ask-my-files-empty")
        dialog.get_by_role("button", name="Close Ask my files").click()
        expect(ask_files).to_be_focused()
    page.locator("#artifact-list").click()
    capture("artifacts-list")
    page.get_by_role("button", name="Pages", exact=True).click()
    expect(page.locator(".artifact-card")).to_have_count(1)
    capture("artifacts-pages")
    page.locator(".artifact-card-title").first.click()
    expect(page.locator(".page-frame")).to_be_visible()
    capture("page-preview")
    page.locator("#page-close").click()
    page.locator("#artifact-search").fill("no matching artifact fixture")
    expect(page.locator("#artifact-empty")).to_be_visible()
    capture("artifacts-empty")
    page.locator("#artifact-search").fill("")
    page.get_by_role("button", name="PDFs", exact=True).click()
    page.locator(".artifact-card-title").first.click()
    expect(page.locator(".artifact-pdf")).to_be_visible()
    capture("artifact-pdf")
    page.locator("#artifact-close").click()
    go(page, "reminders")
    expect(page.locator(".delivery-card").first).to_be_visible()
    capture("reminders")
    page.locator("#reminder-create summary").click()
    capture("reminder-create")
    page.locator("#tasks-tab").click()
    page.get_by_role("button", name="Weekly garden workshop brief", exact=True).click()
    task = page.locator("#tasks-panel article").filter(has_text="Weekly garden workshop brief")
    expect(task).to_be_visible()
    task.locator(".automation-run summary").click()
    capture("recurring-tasks")
    go(page, "inbox")
    expect(page.locator(".inbox-card").first).to_be_visible()
    capture("inbox")
    source = page.locator(".inbox-source summary").first
    if source.is_visible():
        source.click()
        capture("inbox-source")
    go(page, "memory")
    expect(page.locator("#memory-tabs button").first).to_be_visible()
    capture("memory-profile")
    for name in ("People", "Places", "Topics", "Daily"):
        tab = page.get_by_role("tab", name=name)
        tab.click()
        expect(tab).to_have_attribute("aria-selected", "true")
        capture(f"memory-{name.lower()}")
    if baseline:
        go(page, "settings")
        setting(page, "skills")
    else:
        go(page, "skills")
    expect(page.locator(".skill-card").first).to_be_visible()
    capture("skills")
    page.locator("#skill-new").click()
    capture("skill-editor")
    close_modal(page, "#skill-editor")
    go(page, "settings")
    capture("settings")
    for key in SETTINGS:
        setting(page, key)
        if key == "connections":
            expect(page.locator("#rescan-connections")).to_have_attribute("aria-disabled", "false")
            for tab in ("configured", "not-configured"):
                page.locator(f"#{tab}-tab").click()
                expect(page.locator(f"#{tab}-panel .connection-card").first).to_be_visible()
                capture(f"settings-connections-{tab}")
        else:
            capture(f"settings-{key}")

    # Delay and then fail the first list request to observe both states.
    requests = []
    page.route("**/api/artifacts", lambda route: requests.append(route))
    try:
        page.goto(origin + "/?fixture=loading#artifacts")
        expect(page.locator("#artifacts-view")).to_be_visible()
        expect(page.locator("#artifact-count")).to_contain_text("Loading")
        capture("artifacts-loading")
        requests.pop(0).fulfill(status=503, json={"error": "Couldn’t load your saved work. Try again."})
        error = "#artifact-count" if baseline else "#artifact-error-message"
        expect(page.locator(error)).to_contain_text("Couldn’t load")
        capture("artifacts-error")
    finally:
        page.unroute("**/api/artifacts")
    if not baseline:
        page.locator("#artifact-try-again").click()
        expect(page.locator(".artifact-card")).to_have_count(16)
        expect(page.locator("#artifact-refresh")).to_be_focused()
    go(page, "chat")
    if not baseline and tag in ("390x844-dark", "1440x1000-dark"):
        verify_threads(page, app, mobile, capture)
    if mobile:
        page.locator("#open-menu").click()
    page.locator("#new-thread").click()
    expect(page.locator("#side-welcome")).to_be_visible()
    capture("chat-empty")
    contrast = list(low_contrast.values())
    if output:
        (output / f"geometry-{tag}.json").write_text(json.dumps(findings, indent=2))
        (output / f"contrast-{tag}.json").write_text(json.dumps(contrast, indent=2))
    assert not errors, errors
    print(f"{tag}: {contrast_measurements:,} contrast measurements, {len(contrast)} distinct failures", flush=True)
    return findings, contrast


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--size", type=int, choices=(375, 390, 1440))
    parser.add_argument("--theme", choices=("dark", "light"))
    args = parser.parse_args()
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright, playwright.webkit.launch() as browser, \
            patch("hearth.home.weather_value", HOME_FIXTURE["mock_weather"]):
        results = []
        for device, width, height in SIZES:
            for theme in ("dark", "light"):
                if (args.size and width != args.size) or (args.theme and theme != args.theme):
                    continue
                tag = f"{width}x{height}-{theme}"
                options = playwright.devices[device] if device else {}
                with TemporaryDirectory(prefix="hearth-run39-") as temporary, browser.new_context(**{
                    **options, "viewport": {"width": width, "height": height}, "device_scale_factor": 1,
                    "color_scheme": theme, "reduced_motion": "reduce",
                }) as context:
                    storage = Storage(temporary)
                    config = read_config(ROOT / "config/connectors.json")
                    config["brain"] = {"provider": "mock", "model": ""}
                    gateway = AuditGateway()
                    app = Application(storage, LocalCheckpoints(storage), config, gateway=gateway)
                    app.scan_connections()
                    seed(app, gateway)
                    with (
                        patch.object(app.proactivity, "list", return_value=[OFFER]),
                        HTTPServer(("127.0.0.1", 0), app) as server,
                    ):
                        worker = threading.Thread(target=server.serve_forever, daemon=True)
                        worker.start()
                        try:
                            issues, contrast = verify(context, f"http://127.0.0.1:{server.server_port}", tag,
                                                      args.output, args.baseline, app)
                            results.extend((tag, issue) for issue in issues + contrast)
                            print(f"WebKit {tag}: reviewed workspace, {len(issues)} geometry findings", flush=True)
                        finally:
                            server.shutdown()
                            worker.join()
                            app.workers.executor.shutdown()
    if not args.baseline:
        assert not results, results


if __name__ == "__main__":
    main()
