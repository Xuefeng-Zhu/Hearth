# Run 84 · Preact migration phase 3, part 2

Timeline, Memory, Skills, and Inbox moved to Preact in the `hearth-preact` worktree on the local `preact-migration` branch. Each view has its own commit. The comparison revision is `f58a3fe` (`backup/pre-preact`). The main worktree was left alone. No commits were pushed or deployed.

The existing native import map loads the vendored Preact, hooks, and htm modules directly. All 14 CSS files match the baseline byte for byte. Baseline CSS manifest (`/workspace/tmp/hearth-qa/run84/css-baseline.txt`) · Branch CSS manifest (`/workspace/tmp/hearth-qa/run84/css-current.txt`)

## What moved

| View | Implementation |
| --- | --- |
| Timeline · `5cc6a00` | `web/timeline/` renders filters, activity groups, lazy details and raw payloads, and confirmations. The controller keeps native searchable selects, the mobile filter sheet, the SSE refresh, and checkpoint receipts. The baseline Timeline API returns a single snapshot. |
| Memory · `166d33f` | `web/memory/` renders profile and address fields, note navigation and editing, review proposals, and recall results. Recall also moved out of `app.js` and is shared with Settings. This restores the backend labels that the phase 2 extraction had left out of the app’s recall renderer. |
| Skills · `b36c1b9` | `web/skills/` renders the searchable library and the contents of the native editor dialog. The controller keeps deep links, version browsing, drafts, preview, and Try in Chat. Shared search markup lives in `web/list-search-view.js`, so the route and query helpers can still be imported in Node. |
| Inbox · `08caf26` | `web/inbox/` renders the review and processed groups, mail source disclosures, and the proposal editor. It owns polling and mail actions. Keyed cards retain their edit draft and focus across refreshes, while the existing motion helper measures before and after each list change. |

## Line counts

First-party frontend counts use Git insertions and deletions under `web/` excluding `web/vendor/`, against the Run 83 tip `7615e9f`.

| View | Added | Removed | Net |
| --- | ---: | ---: | ---: |
| Timeline | 733 | 817 | −84 |
| Memory | 666 | 705 | −39 |
| Skills | 147 | 137 | +10 |
| Inbox | 306 | 320 | −14 |
| **Run 84 frontend** | **1,852** | **1,979** | **−127** |

`web/app.js` went from 746 to 675 lines. `web/index.html` went from 382 to 254 lines. Run 84 removed **121** net implementation lines including the static asset allowlist. The first-party frontend across the migration is still **76** lines larger than `f58a3fe`.

## Visual parity

Chromium captured each state at 1440 × 900 light, 1440 × 900 dark, and 390 × 844 light. The fixture clock, locale, reduced-motion preference, and capture focus and scroll positions were matched. Every RGB pixel was compared without masks or tolerance. The DOM comparison checks ordered tag, ID, class, and role signatures in the captured view or dialog, excluding generated mascot gradient IDs. Capture scripts (`/workspace/tmp/hearth-qa/run84/screens.py`) · Chat capture (`/workspace/tmp/hearth-qa/run84/screens-chat.py`) · Settings capture (`/workspace/tmp/hearth-qa/run84/screens-settings.py`)

| View | Captured states | Pairs | Changed pixels | DOM mismatches |
| --- | --- | ---: | ---: | ---: |
| Timeline | Activity, expanded raw data, undo confirmation, filters, empty | 15 | 0 | 0 |
| Memory | Profile, topics, note, search, review | 15 | 0 | 0 |
| Skills | Library, search, source, preview, new skill | 15 | 0 | 0 |
| Inbox | Mail, search, source, editor, no matches | 15 | 0 | 0 |
| Home and Feed | Panels, edit, Add panel, Feed, Saved | 15 | 0 | 0 |
| Chat | Transcript, search | 6 | 0 | 0 |
| Artifacts | Grid, list, document drawer, page preview, Ask my files | 15 | 0 | 0 |
| Reminders and Automation | Reminders list, search, create, recurring tasks and editor, event rules and editor | 21 | 0 | 0 |
| Settings | Overview, panels, and workspace status | 57 | 0 | 0 |
| **Total** | | **174** | **0 / 169,427,280** | **0** |

Baseline PNGs (`/workspace/tmp/hearth-qa/run84/captures-baseline`) · Branch PNGs (`/workspace/tmp/hearth-qa/run84/captures-current`) · Diff PNGs (`/workspace/tmp/hearth-qa/run84/diffs`) · Full comparison log (`/workspace/tmp/hearth-qa/run84/pixel-diffs.log`)

## Verification

| Check | Result |
| --- | --- |
| Python unittest discovery with `HEARTH_CJK_FONT` | 342 passed using WenQuanYi Micro Hei. Log (`/workspace/tmp/hearth-qa/run84/logs/python.log`) |
| Node tests and `node --check` | 37 Node tests and 63 JavaScript modules passed. Node (`/workspace/tmp/hearth-qa/run84/logs/node.log`) · Syntax (`/workspace/tmp/hearth-qa/run84/logs/syntax.log`) |
| Browser smoke and stream disconnect | Passed. Default (`/workspace/tmp/hearth-qa/run84/logs/chromium-smoke.log`) · Disconnect (`/workspace/tmp/hearth-qa/run84/logs/chromium-disconnect.log`) |
| Chat search, list search, and searchable combobox | Passed, including Chat and list search width sweeps from 390 to 1920 px. Chat search (`/workspace/tmp/hearth-qa/run84/logs/chromium-chat-search.log`) · List search (`/workspace/tmp/hearth-qa/run84/logs/chromium-list-search.log`) · Combobox (`/workspace/tmp/hearth-qa/run84/logs/chromium-combobox.log`) |
| Motion and interaction regressions | Passed for Home FLIP, panel reorder and restoration, reminder add and cancel, and Inbox FLIP, insertions, inert exits, and reduced motion. Motion (`/workspace/tmp/hearth-qa/run84/logs/chromium-motion.log`) · Home (`/workspace/tmp/hearth-qa/run84/logs/home-behavior.log`) · Reminders (`/workspace/tmp/hearth-qa/run84/logs/reminders-behavior.log`) · Inbox (`/workspace/tmp/hearth-qa/run84/logs/inbox-behavior.log`) |
| Timeline, Memory, and Skills interactions | Passed for Timeline SSE, disclosure focus, undo/redo and restore receipts, Memory profile and note changes, source links and review decisions, repeated Settings recall tests, and Skills deep links, editor history, drafts, delete, and Try in Chat. Timeline (`/workspace/tmp/hearth-qa/run84/logs/timeline-behavior.log`) · Memory (`/workspace/tmp/hearth-qa/run84/logs/memory-behavior.log`) · Recall (`/workspace/tmp/hearth-qa/run84/logs/settings-recall.log`) · Skills (`/workspace/tmp/hearth-qa/run84/logs/skills-behavior.log`) |

The browser suites used offline fixtures and timeouts of six to ten minutes. The Timeline browser restore check exercises the restore confirmation and receipt against a fixture response. The Python suite covers checkpoint storage.

## Risks

- Native dialogs, searchable select wrappers, and editable inputs depend on stable mount points. Changing reconciliation keys can affect focus, disclosure state, and drafts during polling.
- The visual comparison covers settled Chromium frames. The motion checks separately inspect live animation frames and reduced-motion behavior. Live connector services, other browser engines, and very large Timeline histories remain outside this run.
