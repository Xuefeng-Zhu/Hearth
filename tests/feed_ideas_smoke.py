import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import expect

from hearth import feed, scheduler
from hearth.ideas import options
from hearth.proactive_context import Context
from hearth.storage import iso
from test_ideas_goals import idea


def seed_ideas(app):
    now = datetime.now(timezone.utc)
    with app.storage.lock():
        state = app.storage.load()
        app.storage.write("topics/seed-swap.md", "# Seed swap\n\nPlan the seed exchange and set out the trays.")
        source = "memory:topics/seed-swap.md"
        job = scheduler.add_job(state, "Open the garden gates", at=iso(now + timedelta(days=2)), clock=now)
        app.storage.save(state)
        items = [
            idea("automation", f"reminder:{job['id']}", "Close the garden shed", delay_minutes=120,
                 detail="Set a follow-up for after the garden gates open."),
            idea("slides", source, "Seed library slides", detail="Outline a short introduction for new volunteers."),
            idea("reminder", source, "Pack seed trays", at=iso(now + timedelta(days=1)),
                 detail="Get the trays ready before the seed swap."),
            idea("chat", source, "Seed-swap plan", detail="Draft a checklist for the weekend seed exchange."),
        ]
        state["ideas"] = {}
        context = Context(app, state)
        app.ideas.publish(state, context, options(context, now, None), [], items, feed.settings(state), now)
        app.storage.save(state)


def check_actions(card, width):
    dismiss = card.get_by_role("button", name="Dismiss", exact=True)
    uninterested = card.get_by_role("button", name="Not interested", exact=True)
    for button, name in ((dismiss, "Dismiss"), (uninterested, "Not interested")):
        expect(button).to_have_attribute("aria-label", name)
        expect(button).to_have_attribute("title", name)
        expect(button).to_have_text("")
        expect(button.locator("svg")).to_have_attribute("aria-hidden", "true")
    assert dismiss.locator("path").get_attribute("d") != uninterested.locator("path").get_attribute("d")

    row = card.locator(".feed-actions")
    expect(row.get_by_role("button")).to_have_count(3)
    primary, cross, thumb, right, left = row.evaluate("""row => [
        ...Array.from(row.children, button => button.getBoundingClientRect().toJSON()),
        row.getBoundingClientRect().right, row.getBoundingClientRect().left
    ]""")
    assert abs(thumb["right"] - right) < 1 and primary["left"] >= left - 1, (width, primary, thumb, right, left)
    assert primary["right"] < cross["left"] < cross["right"] < thumb["left"], (width, primary, cross, thumb)
    for icon in (cross, thumb):
        assert abs(icon["top"] - primary["top"]) < 1, (width, primary, icon)
        assert icon["width"] == icon["height"] == primary["height"], (width, primary, icon)
    if width <= 760:
        assert min(min(box["width"], box["height"]) for box in (primary, cross, thumb)) >= 44, width


def feed_ideas_smoke(browser, app, origin, browser_page):
    seed_ideas(app)
    output = os.environ.get("HEARTH_FEED_IDEAS_SCREENSHOTS")
    if output:
        Path(output).mkdir(parents=True, exist_ok=True)
    for width, height, theme in ((1440, 900, "light"), (1440, 900, "dark"), (761, 900, "light"),
                                 (760, 900, "light"), (320, 640, "light"), (390, 844, "light")):
        with browser_page(browser, origin, viewport={"width": width, "height": height},
                          color_scheme=theme, is_mobile=width <= 760, has_touch=width <= 760) as page:
            assert page.goto("/").ok
            panel = page.get_by_role("article", name="Feed", exact=True)
            ideas = panel.get_by_role("region", name="Ideas", exact=True)
            cards = ideas.get_by_role("article")
            expect(cards).to_have_count(4)
            for card in cards.all():
                check_actions(card, width)
            if output and width in (1440, 390):
                panel.evaluate("panel => panel.scrollIntoView({block: 'start'})")
                page.screenshot(path=Path(output) / f"feed-ideas-{width}-{theme}.png", animations="disabled")
            if width != 390:
                continue

            automation = ideas.get_by_role("article", name="Close the garden shed")
            automation.get_by_role("button", name="Review automation").press("Tab")
            dismiss = automation.get_by_role("button", name="Dismiss", exact=True)
            expect(dismiss).to_be_focused()
            dismiss.press("Enter")
            expect(automation).to_have_count(0)
            status = ideas.get_by_role("status")
            expect(status).to_have_text("Idea dismissed.")
            expect(status).to_be_focused()

            slides = ideas.get_by_role("article", name="Seed library slides")
            slides.get_by_role("button", name="Not interested", exact=True).tap()
            expect(slides).to_have_count(0)
            expect(status).to_have_text("Similar Ideas will be hidden.")
            expect(status).to_be_focused()
            data = app.storage.load()["ideas"]
            assert data["blocked"] == {feed.topic_key("Seed library slides"): True}

            ideas.get_by_role("button", name="Open draft").tap()
            expect(page.locator("#message")).to_have_value(re.compile("Seed-swap plan"))
            page.get_by_role("button", name="Open menu").tap()
            page.get_by_role("button", name="Home", exact=True).tap()
            expect(cards).to_have_count(1)
            check_actions(cards.first, width)
            ideas.get_by_role("button", name="Review reminder").tap()
            expect(ideas.get_by_text("Needs approval")).to_be_visible()
