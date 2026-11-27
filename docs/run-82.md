# Run 82 · Preact migration phase 2

Settings moved to Preact on the local `preact-migration` branch in the `hearth-preact` worktree. The `main` ref and `backup/pre-preact` both point to the comparison baseline, `f58a3fe`. The browser still loads the vendored Preact and htm modules directly through the Run 81 import map.

## What moved

| Group | Implementation |
| --- | --- |
| Settings navigation and disclosures | `web/settings/workspace.js` renders the groups, disclosures, stable section hosts, and About card. It handles Settings hashes, including the legacy Connections bookmark. A deep link focuses its disclosure once the destination view is visible. |
| Brain | `web/settings/brain.js` owns the model and worker form, model pool and tags, model test, and routing preview and prompt test. |
| Connections | `web/settings/connections.js` owns both tabs, cross-tab filtering and history, connector drafts, GitHub settings, refresh and test feedback, and the Pinecone health check. |
| Memory and Search | `web/settings/preferences.js` owns recall and search settings, folder scope, test forms, Browserbase preferences, and Pinecone sync and reindex status. The Memory review scheduler and shared recall results use their existing controllers. |
| Appearance and Voice | `web/settings/persona.js` renders the forms and preview controls. The shared Chat store carries avatar, dictation, and call preferences. Calls capture the saved preferences when they start. |
| Workspace status | `web/settings/status.js` renders the sidebar and drawer status and handles connector warnings and active model labels. |
| Supporting sections | `web/settings/sections.js` mounts the existing forms and cards for Artifacts, Reminders, Feed, Action suggestions, Automations, Watchers, Approvals, and Home. Their feature modules still handle requests and form behavior. |

Each group has its own commit. Settings panels remain mounted when collapsed, so disclosure changes can preserve form controls and pending work. The app shell supplies routing, polling, and cross-view callbacks.

## Line counts

Git insertions and deletions compare Phase 2 with the Run 81 head, `1995c74`.

| Scope | Removed | Added | Net |
| --- | ---: | ---: | ---: |
| `web/app.js` | 1,208 | 70 | −1,138, from 1,875 to 737 lines |
| `web/index.html` | 478 | 3 | −475 |
| `web/settings/*.js` | 0 | 1,928 | +1,928 |
| All first-party frontend files | 1,895 | 2,017 | +122 |
| All Phase 2 code and tests before this report | 1,895 | 2,127 | +232 |

The first-party frontend grew by 122 lines in Phase 2 and by 347 lines across both phases relative to `f58a3fe`. The seven Settings modules include the relocated HTML and the component and controller boundaries.

## Visual parity

All 14 CSS files have the same Git blob IDs as `f58a3fe`. The capture matrix covers the overview, all 15 sections, an expanded populated model pool, the configured connector tab with a tested connector, and the workspace connection warning. The two revisions use the same loopback fixtures, times, viewport, locale, color scheme, and reduced-motion setting. Chromium hides transient scrollbars and fully repaints the settled settings pane before capture. The comparison checks every RGB pixel, with no masks or tolerance. Diff images would highlight changed pixels in magenta. [CSS manifest](/workspace/tmp/hearth-qa/run82/css-current.txt) · [Capture script](/workspace/tmp/hearth-qa/run82/screens.py) · [Full comparison log](/workspace/tmp/hearth-qa/run82/pixel-diffs.log)

| Viewport | Pairs | Changed pixels | Example |
| --- | ---: | ---: | --- |
| 1440 × 900, light | 19 | 0 / 24,624,000 | [Brain pool](/workspace/tmp/hearth-qa/run82/captures-current/brain-pool-1440-light.png) · [Diff](/workspace/tmp/hearth-qa/run82/diffs/brain-pool-1440-light.png) |
| 1440 × 900, dark | 19 | 0 / 24,624,000 | [Memory](/workspace/tmp/hearth-qa/run82/captures-current/memory-1440-dark.png) · [Diff](/workspace/tmp/hearth-qa/run82/diffs/memory-1440-dark.png) |
| 390 × 844, light | 19 | 0 / 6,254,040 | [Connections](/workspace/tmp/hearth-qa/run82/captures-current/connections-configured-390-light.png) · [Diff](/workspace/tmp/hearth-qa/run82/diffs/connections-configured-390-light.png) |

All 57 captures match the ordered Settings tag, ID, class, and role signatures. The comparison omits the avatar drawing’s generated SVG gradient IDs, whose numbering already differed after Phase 1. [Baseline captures](/workspace/tmp/hearth-qa/run82/captures-baseline) · [Migration captures](/workspace/tmp/hearth-qa/run82/captures-current) · [Diff images](/workspace/tmp/hearth-qa/run82/diffs)

## Verification

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests` with `HEARTH_CJK_FONT` | 342 passed. [Log](/workspace/tmp/hearth-qa/run82/python.log) |
| `node --test tests/*.test.mjs` | 37 passed. [Log](/workspace/tmp/hearth-qa/run82/node.log) |
| `node --check` on the JavaScript files under `web/` | 51 passed. [Log](/workspace/tmp/hearth-qa/run82/js-syntax.log) |
| `PYTHONPATH=. python tests/browser-smoke.py` | Passed with a 600-second timeout. [Log](/workspace/tmp/hearth-qa/run82/chromium-smoke.log) |
| `PYTHONPATH=. python tests/browser-smoke.py --disconnect` | Passed. [Log](/workspace/tmp/hearth-qa/run82/chromium-disconnect.log) |
| `PYTHONPATH=. python tests/browser-smoke.py --chat-search` | Passed. Zero horizontal overflow from 390 through 1920 px. [Log](/workspace/tmp/hearth-qa/run82/chromium-chat-search.log) |

The Settings smoke covers deep-link focus after a view transition, connector drafts across filtering and history, a pending connector test, Brain preview and model testing, Memory and Search saves, and saved avatar and voice preferences across Chat and a reload. [Test](../tests/settings_smoke.py) · [Settings log](/workspace/tmp/hearth-qa/run82/chromium-settings.log)

## Risks

- The Settings form hosts are persistent. Native controls and existing controllers own transient edits, validation, combobox enhancement, and some live feedback inside those hosts. Changes to mounting order or form ownership can affect those interactions.
- Visual and interaction verification ran on Chromium with offline fixtures. Live provider calls and authorization, Pinecone jobs against a live index, and other browser engines remain outside the run.
