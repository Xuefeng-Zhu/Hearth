import os
from pathlib import Path

from playwright.sync_api import expect

from hearth import skills, timeline

THREAD_NAMES = ("Café plans", "December calendar", "Garden notes", "House projects", "Reading list",
                "School dates", "Travel ideas", "Weekly meals", "Weekend plans", "Winter errands")
MODEL_NAMES = ("atlas/chat-base", "atlas/chat-plus", "atlas/vision", "lumen/fast-chat", "lumen/vision",
               "northstar/instruct", "northstar/vision-lite", "orbit/reasoning", "sable/code", "sable/chat")


def seed_activity(app):
    threads = {}
    for index, title in enumerate(THREAD_NAMES, 1):
        with app.storage.lock():
            thread = app.threads.create(title=title)
            threads[title] = thread["id"]
        timeline.record(app.storage, "reminder" if index % 2 else "artifact", f"{title} sample activity",
                        {"thread_id": thread["id"], "thread_title": title})
    return threads


def capture(page, name):
    output = os.environ.get("HEARTH_SMOKE_SCREENSHOTS")
    if output:
        page.screenshot(path=Path(output) / name, animations="disabled")


def open_timeline(page):
    assert page.goto("/").ok
    expect(page).to_have_title("Hearth")
    page.get_by_role("button", name="Timeline", exact=True).click()
    expect(page.get_by_role("heading", name="Workspace activity")).to_be_visible()
    expect(page.locator(".timeline-title").filter(has_text="Café plans sample activity")).to_be_visible()


def trigger(page, selector):
    return page.locator(f"{selector} + .combobox-trigger")


def assert_enhanced(page, selector, count):
    expect(page.locator(f"{selector} option")).to_have_count(count)
    expect(trigger(page, selector)).to_have_count(int(count > 8))


def verify_dark_contrast(page):
    ratios = page.locator(".combobox-popup").evaluate("""popup => {
      const luminance = color => color.match(/[0-9.]+/g).slice(0, 3)
        .map(value => value / 255)
        .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
        .reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
      const ratio = (fg, bg) => {
        const [a, b] = [luminance(fg), luminance(bg)].sort((a, b) => a - b);
        return (b + 0.05) / (a + 0.05);
      };
      const paper = getComputedStyle(popup).backgroundColor;
      const search = popup.querySelector("input");
      const field = getComputedStyle(search);
      const active = getComputedStyle(popup.querySelector("[data-active]"));
      return [
        ratio(field.color, field.backgroundColor),
        ratio(getComputedStyle(search, "::placeholder").color, field.backgroundColor),
        ratio(active.color, active.backgroundColor),
        ratio(getComputedStyle(popup.querySelector(".combobox-option:not([data-active])")).color, paper),
        ratio(getComputedStyle(popup.querySelector(".combobox-search-row > svg")).color, field.backgroundColor),
        ratio(active.outlineColor, active.backgroundColor),
      ];
    }""")
    assert all(ratio >= 4.5 for ratio in ratios[:-1]) and ratios[-1] >= 3, ratios


def verify_timeline(page, thread_id, scheme):
    open_timeline(page)
    thread = trigger(page, "#timeline-thread")
    category = trigger(page, "#timeline-category")
    expect(thread).to_have_accessible_name("Thread All threads")
    expect(category).to_have_accessible_name("Category All categories")
    assert_enhanced(page, "#timeline-thread", 11)
    assert_enhanced(page, "#timeline-category", 31)
    thread.click()
    search = page.get_by_role("combobox", name="Search thread")
    options = page.get_by_role("listbox", name="Thread")
    expect(search).to_be_focused()
    expect(options.get_by_role("option", name="All threads")).to_have_attribute("aria-selected", "true")
    expect(options.get_by_role("option", name="All threads").locator("svg")).to_have_count(1)
    popup = page.locator(".combobox-popup")
    expect(popup).to_have_css("opacity", "1")
    anchored = popup.bounding_box()
    anchor = thread.bounding_box()
    assert anchored["x"] == anchor["x"] and anchored["y"] >= anchor["y"] + anchor["height"]
    if scheme == "dark":
        verify_dark_contrast(page)
    search.fill("ca")
    expect(options.get_by_role("option", name="Café plans")).to_be_visible()
    capture(page, f"timeline-thread-search-1440-{scheme}.png")
    search.fill("absent")
    expect(page.get_by_role("status").filter(has_text="No matches")).to_be_visible()
    search.press("Escape")
    expect(thread).to_be_focused()
    expect(thread).to_have_accessible_name("Thread All threads")

    page.locator("#timeline-thread").evaluate("""select => {
      window.comboEvents = [];
      for (const type of ['input', 'change']) select.addEventListener(type,
        event => window.comboEvents.push([event.type, event.target.value]));
    }""")
    thread.press("c")
    expect(search).to_have_value("c")
    search.fill("CAFE")
    expect(options.get_by_role("option")).to_have_count(1)
    search.press("Enter")
    expect(thread).to_be_focused()
    expect(thread).to_have_accessible_name("Thread Café plans")
    expect(page.locator("#timeline-thread")).to_have_value(thread_id)
    assert page.evaluate("window.comboEvents") == [["input", thread_id], ["change", thread_id]]
    expect(page.locator(".timeline-title")).to_have_text(["Café plans sample activity"])

    thread.press("ArrowDown")
    search.press("End")
    last = options.get_by_role("option", name=THREAD_NAMES[-1])
    expect(search).to_have_attribute("aria-activedescendant", last.get_attribute("id"))
    search.press("Home")
    search.press("ArrowDown")
    search.press("ArrowUp")
    first = options.get_by_role("option", name="All threads")
    expect(search).to_have_attribute("aria-activedescendant", first.get_attribute("id"))
    search.press("Tab")
    expect(options).to_be_hidden()
    expect(category).to_be_focused()
    expect(page.locator("#timeline-thread")).to_have_value(thread_id)
    thread.click()
    first.click()
    expect(thread).to_have_accessible_name("Thread All threads")

    category.click()
    search = page.get_by_role("combobox", name="Search category")
    search.fill("rem")
    option = page.get_by_role("option", name="Reminder", exact=True)
    expect(option).to_be_visible()
    if scheme == "light":
        capture(page, "timeline-category-search-1440-light.png")
    option.click()
    expect(category).to_be_focused()
    expect(page.locator(".timeline-entry[data-kind=artifact]")).to_have_count(0)
    assert page.locator(".timeline-entry[data-kind=reminder]").count() > 0


def verify_runtime_lists(page, app):
    brain = app.brain_info()
    brain.update(mode="openai", selection={"provider": "openai", "model": MODEL_NAMES[0]},
                 providers=[{"provider": "openai", "name": "Fixture provider", "available": True, "supported": True,
                             "default_model": MODEL_NAMES[0]}], pool=[], default_pool=[])
    models = {"models": MODEL_NAMES, "tags": {model: {} for model in MODEL_NAMES}, "detail": ""}
    page.route("**/api/brain", lambda route: route.fulfill(json=brain))
    page.route("**/api/brain/models?*", lambda route: route.fulfill(json=models))
    page.route("**/api/brain/route", lambda route: route.fulfill(json={"preview": brain["preview"]}))
    page.goto("/#settings/brain")
    model = trigger(page, "#brain-model")
    expect(model).to_be_enabled()
    expect(model).to_have_accessible_name(f"Model {MODEL_NAMES[0]}")
    assert_enhanced(page, "#brain-model", 11)
    model.click()
    search = page.get_by_role("combobox", name="Search model")
    search.fill("vision")
    expect(page.get_by_role("listbox", name="Model").get_by_role("option")).to_have_count(3)
    capture(page, "brain-model-search-1440-light.png")
    search.press("Escape")
    page.select_option("#brain-provider", "smart")
    expect(trigger(page, "#pool-model")).to_be_visible()
    assert_enhanced(page, "#pool-model", 11)

    memory = app.memory_info()
    memory["models"] = {f"fixture/{name}": name for name in MODEL_NAMES}
    memory["selection"].update(backend="huggingface", model=f"fixture/{MODEL_NAMES[0]}")
    page.route("**/api/memory/settings", lambda route: route.fulfill(json=memory))
    page.goto("/#settings/memory")
    expect(trigger(page, "#memory-model")).to_be_visible()
    assert_enhanced(page, "#memory-model", 10)
    expect(trigger(page, "#memory-test-thread")).to_be_attached()
    assert_enhanced(page, "#memory-test-thread", 13)

    page.goto("/#settings/voice")
    assert_enhanced(page, "#call-language", 3)
    expect(page.locator("#call-language")).to_be_visible()
    assert_enhanced(page, "#voice-language", 12)
    trigger(page, "#voice-language").click()
    page.get_by_role("combobox", name="Search language").fill("espanol")
    expect(page.get_by_role("option", name="Español")).to_be_visible()
    page.keyboard.press("Enter")
    expect(page.locator("#voice-language")).to_have_value("es-ES")

    page.get_by_role("button", name="Chat", exact=True).click()
    expect(trigger(page, "#thread-select")).to_be_attached()
    assert_enhanced(page, "#thread-select", 12)
    expect(trigger(page, "#thread-select")).to_be_hidden()
    page.set_viewport_size({"width": 770, "height": 900})
    expect(trigger(page, "#thread-select")).to_be_visible()
    page.set_viewport_size({"width": 1440, "height": 900})

    library = app.agent.skills
    def playbook(version):
        return skills.format_skill({"name": "Weekend planning", "description": "Make weekend plans.",
                                    "when_to_use": "When planning weekends.", "tools": [],
                                    "content": f"Planning notes for version {version}."})
    skill, _ = library.mutate("create", {"markdown": playbook(1)})
    for version in range(2, 10):
        skill, _ = library.mutate("save", {"id": skill["id"], "revision": skill["revision"], "markdown": playbook(version)})
    page.goto(f"/#skills/{skill['id']}")
    history = trigger(page, "#skill-versions")
    expect(history).to_be_visible()
    assert_enhanced(page, "#skill-versions", 9)
    history.click()
    page.get_by_role("combobox", name="Search version history").fill("Version 2")
    page.get_by_role("option", name="Version 2", exact=False).click()
    expect(page.locator("#skill-markdown")).to_have_value(playbook(2))
    expect(history).to_be_focused()
    page.get_by_role("button", name="Close skill editor").click()

    page.goto("/#settings/connections/not-configured")
    selector = "#not-configured-panel .connection-filters select"
    expect(trigger(page, selector)).to_be_visible()
    assert_enhanced(page, selector, 10)
    trigger(page, selector).click()
    page.get_by_role("combobox", name="Search category").fill("stor")
    page.get_by_role("listbox", name="Category").get_by_role("option", name="Data and storage").click()
    expect(page.locator(selector)).to_have_value("Data and storage")
    expect(page.locator("#not-configured-panel [data-provider=pinecone]")).to_be_visible()
    expect(page.locator("#not-configured-panel [data-provider=github]")).to_have_count(0)
    page.locator('.sidebar [data-view="artifacts"]').click()
    assert_enhanced(page, "#artifact-sort", 2)
    page.locator('.sidebar [data-view="settings"]').click()
    page.locator('[data-settings="search"]').click()
    assert_enhanced(page, "#search-recency", 5)
    page.locator('[data-settings="connections"]').click()
    expect(trigger(page, selector)).to_be_visible()


def verify_mutations(page):
    page.evaluate("""() => {
      const form = document.createElement('form');
      form.id = 'combo-fixture-form';
      form.innerHTML = '<label for="combo-fixture">Test choices</label><select id="combo-fixture" name="choice">' +
        '<option value="base">Default</option><option value="second">Second</option></select>' +
        '<button type="button">Next control</button>';
      document.querySelector('#settings-connections').prepend(form);
    }""")
    select = page.locator("#combo-fixture")
    button = trigger(page, "#combo-fixture")
    expect(button).to_have_count(0)
    select.evaluate("""select => {
      const group = document.createElement('optgroup');
      group.label = 'Places';
      group.append(new Option('Québec', 'qc'), new Option('Montréal', 'mtl'),
        ...Array.from({length: 5}, (_, i) => new Option('District ' + i, 'district-' + i)));
      group.firstChild.disabled = true;
      select.append(group);
    }""")
    expect(button).to_have_accessible_name("Test choices Default")
    select.evaluate("select => { select.value = 'mtl'; }")
    expect(button).to_have_accessible_name("Test choices Montréal")
    page.locator('label[for="combo-fixture"]').click()
    options = page.get_by_role("listbox", name="Test choices")
    expect(options).to_be_visible()
    expect(options.get_by_role("group", name="Places")).to_be_visible()
    expect(options.get_by_role("option", name="Québec")).to_have_attribute("aria-disabled", "true")
    search = page.get_by_role("combobox", name="Search test choices")
    search.fill("MTL")
    expect(options.get_by_role("option")).to_have_count(1)
    expect(options.get_by_role("option", name="Montréal")).to_be_visible()
    select.evaluate("select => { select.options[3].text = 'Montréal Centre'; }")
    expect(options.get_by_role("option", name="Montréal Centre")).to_be_visible()
    search.press("Enter")
    assert page.locator("#combo-fixture-form").evaluate("form => new FormData(form).get('choice')") == "mtl"
    page.locator("#combo-fixture-form").evaluate("form => form.reset()")
    expect(button).to_have_accessible_name("Test choices Default")
    select.evaluate("select => { select.disabled = true; }")
    expect(button).to_be_disabled()
    select.evaluate("select => { select.disabled = false; select.lastChild.remove(); }")
    expect(button).to_have_count(0)
    expect(select).to_be_visible()
    select.evaluate("select => select.setAttribute('data-searchable', '')")
    expect(button).to_be_visible()
    button.click()
    select.evaluate("select => select.remove()")
    expect(search).to_be_hidden()
    expect(select).to_have_count(0)


def verify_mobile(page, thread_id):
    assert page.goto("/").ok
    page.get_by_role("button", name="Open menu").tap()
    page.get_by_role("button", name="Timeline", exact=True).tap()
    expect(page.get_by_role("heading", name="Timeline", exact=True)).to_be_visible()
    expect(page.locator(".timeline-title").filter(has_text="Café plans sample activity")).to_be_visible()
    rows_before = page.locator(".timeline-title").count()
    page.get_by_role("button", name="Filter", exact=True).tap()
    sheet = page.get_by_role("dialog", name="Filter activity")
    thread = trigger(page, "#timeline-thread")
    expect(thread).to_be_visible()
    thread.tap()
    search = page.get_by_role("combobox", name="Search thread")
    expect(search).to_be_focused()
    search.fill("ca")
    option = page.get_by_role("option", name="Café plans")
    popup = page.locator(".combobox-popup")
    expect(popup).to_have_css("translate", "none")
    assert popup.bounding_box()["width"] == 390
    assert all(item.bounding_box()["height"] >= 44 for item in (search, option, thread))
    assert int(search.evaluate("el => parseFloat(getComputedStyle(el).fontSize)")) >= 16
    assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
    capture(page, "timeline-search-390-light.png")
    search.press("Escape")
    expect(sheet).to_be_visible()
    expect(thread).to_be_focused()
    thread.tap()
    search.fill("cafe")
    option.tap()
    expect(page.locator("#timeline-thread")).to_have_value(thread_id)
    expect(page.locator(".timeline-title")).to_have_count(rows_before)
    sheet.get_by_role("button", name="Apply").tap()
    expect(sheet).to_be_hidden()
    expect(page.locator(".timeline-title")).to_have_text(["Café plans sample activity"])


def combobox_smoke(browser, app, origin, browser_page):
    threads = seed_activity(app)
    for scheme in ("light", "dark"):
        with browser_page(browser, origin, viewport={"width": 1440, "height": 900}, color_scheme=scheme) as page:
            verify_timeline(page, threads["Café plans"], scheme)
    with browser_page(browser, origin, viewport={"width": 390, "height": 844}, color_scheme="light",
                      is_mobile=True, has_touch=True) as page:
        verify_mobile(page, threads["Café plans"])
    with browser_page(browser, origin, viewport={"width": 1440, "height": 900}, color_scheme="light") as page:
        verify_runtime_lists(page, app)
        verify_mutations(page)
