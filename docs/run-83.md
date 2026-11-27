# Run 83 · Preact migration phase 3, part 1

Artifacts, Automation, Reminders, and Home, including Feed, moved to Preact on the local `preact-migration` branch in `hearth-preact`. There is one implementation commit per view. Each replacement passed its local pixel and interaction checks before the old renderer was removed. The branch stayed local, with no push or deployment. The comparison revision is `f58a3fe` (`backup/pre-preact`), which is also the tip of `main`.

The existing import map loads vendored Preact and htm directly. All 14 CSS files have the same blob IDs as the baseline. [Baseline CSS manifest](/workspace/tmp/hearth-qa/run83/css-baseline.txt) · [Run 83 CSS manifest](/workspace/tmp/hearth-qa/run83/css-current.txt)

## What moved

| View | Implementation |
| --- | --- |
| Artifacts · `2349f10` | `web/artifacts/` mounts the library and the file, page, and Ask my files dialog contents. Grid and list rows, file drawer actions, previews, and version history use Preact. The existing page and file-question controllers still handle their native dialogs and requests. Shared Markdown and routing helpers live in `format.js`. |
| Automation · `804fefb` | `web/automation/` renders recurring task selection and run history, event rules, editor forms, approval cards, and Inbox run summaries. The dynamic schedule and rule controls keep their native form values and validation. |
| Reminders · `d0b3153` | `web/reminders/` mounts the creation form and renders Upcoming, Snoozed, Delivered, and Outbox results, including search highlights, delivery chips, and the shared email status card. The existing Inbox review and edit controller lives alongside the Reminders API logic. |
| Home and Feed · `40e3e40` | `web/home/` mounts Home, renders keyed panels and their edit and restore controls, and renders Feed, Ideas, Saved, and suggestion actions. The Feed root remains mounted within its panel during updates and reorders. Goals uses its existing editor and approval controller. |

Home and Reminders measure their lists before the synchronous Preact commit and run the existing motion helper after it. Chromium exercised Home FLIP reordering, dragging, panel removal and restoration, reminder insertion and cancellation, inert exit copies, and reduced motion. The browser checks also exercised the Add panel handoff to Chat, artifact download and drawer focus, task approval and undo, and Feed pagination, feedback, and steering. [Motion smoke](/workspace/tmp/hearth-qa/run83/logs/chromium-motion.log) · [Targeted browser script](/workspace/tmp/hearth-qa/run83/behavior.py)

## Line counts

First-party frontend counts are Git insertions and deletions under `web/`, excluding `web/vendor/`, relative to Run 82 (`3d90bd9`).

| View | Added | Removed | Net |
| --- | ---: | ---: | ---: |
| Artifacts | 559 | 583 | −24 |
| Automation | 271 | 296 | −25 |
| Reminders | 148 | 151 | −3 |
| Home and Feed | 448 | 540 | −92 |
| **Run 83 frontend** | **1,426** | **1,570** | **−144** |

`web/index.html` went from 589 to 382 lines. `web/app.js` went from 737 to 746 lines. Across all implementation changes, including the server asset allowlist and Node test imports, Run 83 removed a net 138 lines. Across all three runs, the first-party frontend is still 203 lines larger than `f58a3fe`.

## Visual parity

Each state was captured at 1440 × 900 light, 1440 × 900 dark, and 390 × 844 light. Both revisions used the same offline fixtures, fixed browser clock, locale, reduced-motion setting, and repaint sequence. The comparison checks every RGB pixel and the ordered tag, ID, class, and role signatures of the captured view or dialog. No pixel masks or tolerances were used. [Capture script](/workspace/tmp/hearth-qa/run83/screens.py) · [Pixel and DOM comparison](/workspace/tmp/hearth-qa/run83/pixel-diffs.log)

| View | Captured states | Pairs | Changed pixels | DOM mismatches |
| --- | --- | ---: | ---: | ---: |
| Artifacts | Grid, list, document drawer, page preview, Ask my files | 15 | 0 / 14,605,800 | 0 |
| Automation | Recurring tasks, task editor, event rules, event editor | 12 | 0 / 11,684,640 | 0 |
| Reminders | Scheduled and delivered list, search results, creation form | 9 | 0 / 8,763,480 | 0 |
| Home | Panels, edit mode, Add panel, Feed, Saved Feed | 15 | 0 / 14,605,800 | 0 |
| **Total** | | **51** | **0 / 49,659,720** | **0** |

[Baseline PNGs](/workspace/tmp/hearth-qa/run83/captures-baseline) · [Branch PNGs](/workspace/tmp/hearth-qa/run83/captures-current) · [Diff PNGs](/workspace/tmp/hearth-qa/run83/diffs)

## Verification

The Python suite used `HEARTH_CJK_FONT` with the WenQuanYi Micro Hei fixture. Browser smoke ran against loopback fixtures with outer timeouts of six to ten minutes.

| Check | Result |
| --- | --- |
| Python unittest discovery | 342 passed. [Log](/workspace/tmp/hearth-qa/run83/logs/python.log) |
| Node tests | 37 passed. [Log](/workspace/tmp/hearth-qa/run83/logs/node.log) |
| `node --check` under `web/` | 57 modules passed. [Log](/workspace/tmp/hearth-qa/run83/logs/syntax.log) |
| Default browser smoke and stream disconnect | Passed. [Default](/workspace/tmp/hearth-qa/run83/logs/chromium-smoke.log) · [Disconnect](/workspace/tmp/hearth-qa/run83/logs/chromium-disconnect.log) |
| Chat search and list search | Passed, including width sweeps from 390 through 1920 px. [Chat search](/workspace/tmp/hearth-qa/run83/logs/chromium-chat-search.log) · [List search](/workspace/tmp/hearth-qa/run83/logs/chromium-list-search.log) |
| Motion and searchable combobox | Passed. [Motion](/workspace/tmp/hearth-qa/run83/logs/chromium-motion.log) · [Combobox](/workspace/tmp/hearth-qa/run83/logs/chromium-combobox.log) |
| Home dashboard browser regression | Passed at 1440, 390, and 375 px in light and dark. [Log](/workspace/tmp/hearth-qa/run83/logs/chromium-home-dashboard.log) |
| Per-view browser interactions | Passed. [Artifact layout and file Q&A](/workspace/tmp/hearth-qa/run83/logs/artifact-behavior.log) · [Artifact drawers](/workspace/tmp/hearth-qa/run83/logs/artifacts-dialogs.log) · [Automation](/workspace/tmp/hearth-qa/run83/logs/automation-behavior.log) · [Reminders](/workspace/tmp/hearth-qa/run83/logs/reminders-behavior.log) · [Home and Feed](/workspace/tmp/hearth-qa/run83/logs/home-behavior.log) |

## Risks

- Native dialogs, dynamic editor inputs, and embedded approval and Goals cards share mount points with Preact. Their controllers still handle focus, browser validation, and pending operations. Changes to component keys or mount timing can affect those interactions, especially across a poll or navigation.
- The visual matrix covers settled Chromium frames. The motion checks exercise animation keyframes and focus separately. Live Box and mail providers, live Feed refresh, and other browser engines are outside this run.
