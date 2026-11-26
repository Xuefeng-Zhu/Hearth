from playwright.sync_api import expect


def motion_smoke(browser, origin, browser_page):
    for reduced_motion in ("no-preference", "reduce"):
        with browser_page(browser, origin, viewport={"width": 1440, "height": 900},
                          reduced_motion=reduced_motion) as page:
            reduced = reduced_motion == "reduce"
            page.add_init_script("""(() => {
              window.viewTransitions = 0;
              const start = document.startViewTransition.bind(document);
              document.startViewTransition = (update) => {
                window.viewTransitions++;
                const transition = start(update);
                transition.ready.then(() => {
                  window.viewFrames = document.getAnimations().map(animation => animation.animationName);
                }, () => {});
                return transition;
              };
            })();""")
            assert page.goto("/").ok
            expect(page.get_by_role("button", name="Edit layout")).to_be_enabled()
            page.locator(".sidebar [data-view=chat]").click()
            expect(page.locator("#chat-view")).to_be_visible()
            assert page.evaluate("window.viewTransitions") == (0 if reduced else 1)
            if not reduced:
                page.wait_for_function("window.viewFrames?.includes('workspace-in') && window.viewFrames.includes('workspace-out')")
            trigger = page.get_by_role("button", name="Actions for Smoke side chat")
            trigger.focus()
            page.keyboard.press("ArrowDown")
            popup = page.locator("#thread-menu")
            expect(popup.get_by_role("menuitem", name="Summary")).to_be_focused()
            if reduced:
                assert popup.evaluate("""menu => getComputedStyle(menu).scale === "none" &&
                  getComputedStyle(menu).translate === "none" &&
                  menu.getAnimations().every(animation => animation.transitionProperty !== "scale" &&
                    animation.transitionProperty !== "translate")""")
            expect(popup).to_have_css("opacity", "1")

            closing = popup.evaluate("""menu => {
              const trigger = document.querySelector('[aria-controls="thread-menu"][aria-expanded="true"]');
              menu.querySelector('[role="menuitem"]').dispatchEvent(new KeyboardEvent('keydown',
                {key: 'Escape', bubbles: true, cancelable: true}));
              const styles = getComputedStyle(menu);
              return {
                focused: document.activeElement === trigger,
                open: menu.matches(':popover-open'),
                inert: menu.inert,
                display: styles.display,
                pointer: styles.pointerEvents,
                transitions: menu.getAnimations().map(animation => animation.transitionProperty),
              };
            }""")
            assert closing["focused"] and closing["inert"] and not closing["open"], closing
            assert closing["pointer"] == "none" and closing["display"] != "none", closing
            assert {"opacity", "display", "overlay"} <= set(closing["transitions"]), closing
            assert ("scale" in closing["transitions"]) != reduced, closing
            expect(popup).to_have_css("display", "none")
            expect(trigger).to_be_focused()

            page.locator(".sidebar [data-view=home]").click()
            page.get_by_role("button", name="Edit layout").click()
            panels = page.locator("#home-grid [data-panel]")
            first = panels.first.get_attribute("data-panel")
            second = panels.nth(1).get_attribute("data-panel")
            panels.first.locator('[data-control="down"]').press("Enter")
            expect(panels.first).to_have_attribute("data-panel", second)
            expect(panels.nth(1)).to_have_attribute("data-panel", first)
            if reduced:
                assert panels.evaluate_all("""panels => panels.every(panel => panel.getAnimations().length === 0
                  && getComputedStyle(panel).translate === 'none' && getComputedStyle(panel).scale === 'none')""")
            else:
                page.wait_for_function("""() => [...document.querySelectorAll('#home-grid [data-panel]')].some(panel =>
                  panel.getAnimations().some(animation => animation.effect.getKeyframes().some(frame => frame.translate)))""")

    with browser_page(browser, origin, viewport={"width": 390, "height": 844},
                      reduced_motion="reduce", is_mobile=True, has_touch=True) as page:
        assert page.goto("/").ok
        page.get_by_role("button", name="Open menu").click()
        drawer = page.locator("#workspace-drawer")
        expect(drawer).to_have_css("translate", "none")
        drawer.get_by_role("button", name="Chat", exact=True).click()
        opener = page.get_by_role("button", name="Search chats")
        opener.click()
        sheet = page.locator("#chat-search-dialog")
        expect(sheet).to_have_css("translate", "none")
        expect(sheet).to_have_css("scale", "none")
        page.keyboard.press("Escape")
        expect(sheet).to_have_css("display", "none")
        expect(opener).to_be_focused()
