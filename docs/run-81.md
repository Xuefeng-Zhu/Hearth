# Run 81 · Preact migration phase 1

Phase 1 is on the local `preact-migration` branch in the `hearth-preact` worktree. It was neither pushed nor deployed. The Run 80 baseline is `f58a3fe`, saved as `backup/preact-migration-run81`, tagged `backup/pre-preact`, and archived in the workspace bundle `/workspace/backups/hearth-pre-preact-f58a3fe.bundle`.

## What moved

- The workspace serves Preact 10.29.8, its matching hooks, and htm 3.1.1 as local ES modules with their npm licenses. `index.html` resolves them through an import map. The workspace page’s Content Security Policy allows that map by SHA-256 hash. The frontend still runs directly from `web/` with static assets and htm templates.
- `web/store.js` holds the current thread, thread summaries, composer and dictation state, and avatar and voice preferences. Components subscribe to the state they use. Store updates commit before controller code reads the DOM for focus, scrolling, or geometry.
- `web/chat/threads.js` renders the thread rows, their overflow buttons, the desktop action menu contents, and the thread and avatar select options. The existing menu controller handles anchoring, keyboard navigation, focus return, and the mobile sheet.
- `web/chat/conversation.js` renders the transcript, optimistic turns, streamed replies, call records, and message actions. `web/chat/composer.js` renders the editor, attachments entry point, voice controls, Send, and Stop reply. The existing attachment uploader, dictation and call clients, Markdown renderer, and message cards are reused.
- `web/chat/search.js` renders the all-chat search panel and the find-in-thread bar, including result groups, keyboard selection, pagination, and match navigation. The same panel moves between the desktop popover, mobile dialog, and inline bar.
- `web/chat/workspace.js` owns the Chat controller extracted from `app.js`, including API requests, SSE reconnection, per-thread drafts, transcript paging, and integrations with existing views. The workspace shell still owns routing and the other pages.

## Line counts

Counts are Git insertions and deletions against `f58a3fe`, except for the resulting file lengths.

| Scope | Removed | Added | Result |
| --- | ---: | ---: | --- |
| `web/app.js` | 1,925 | 62 | 1,875 lines, down from 3,738 (49.8% smaller) |
| `web/chat/*.js` | 0 | 2,422 | Six files, including the 1,731-line workspace controller |
| First-party frontend, including the rows above | 2,347 | 2,572 | Net +225 lines |
| Vendored libraries and licenses | 0 | 228 | Three ES modules and two licenses |
| All changes before this report | 2,352 | 2,889 | Includes server and test changes |

## Visual parity and behavior

There are no intended user-facing changes. CSS is byte-identical to the baseline. The captures use the same offline seeded workspace, clock, viewport, color scheme, and reduced-motion setting for both revisions. The diff images show the baseline dimmed and would highlight changed pixels in magenta.

| State | Viewport | Changed pixels | Capture | Diff |
| --- | --- | ---: | --- | --- |
| Chat, light | 1440 × 900 | 0 / 1,296,000 | PNG (`/workspace/tmp/hearth-qa/run81/chat-1440-light.png`) | PNG (`/workspace/tmp/hearth-qa/run81/diff-chat-1440-light.png`) |
| Chat, dark | 1440 × 900 | 0 / 1,296,000 | PNG (`/workspace/tmp/hearth-qa/run81/chat-1440-dark.png`) | PNG (`/workspace/tmp/hearth-qa/run81/diff-chat-1440-dark.png`) |
| Chat, mobile light | 390 × 844 | 0 / 329,160 | PNG (`/workspace/tmp/hearth-qa/run81/chat-390-light.png`) | PNG (`/workspace/tmp/hearth-qa/run81/diff-chat-390-light.png`) |
| Chat search, light | 1440 × 900 | 0 / 1,296,000 | PNG (`/workspace/tmp/hearth-qa/run81/chat-search-1440-light.png`) | PNG (`/workspace/tmp/hearth-qa/run81/diff-chat-search-1440-light.png`) |

## Verification

The Browser plugin was unavailable. Playwright ran Chromium with temporary workspaces on `127.0.0.1` and offline fixtures. The composer regression checks that dictation inserts at the caret, a draft and uploaded attachment survive a thread switch, and removing the attachment or leaving Face to face restores focus. The HTTP test checks the composer mount point, the import map’s CSP hash, and the vendored modules’ MIME types. Browser smoke checks the mounted composer’s accessible labels and interactions. The Chat search field retains disabled spellcheck, which requires passing a boolean through Preact.

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests` with `HEARTH_CJK_FONT` | 342 passed. Log (`/workspace/tmp/hearth-qa/run81/python.log`) |
| `node --test tests/*.test.mjs` | 37 passed. Log (`/workspace/tmp/hearth-qa/run81/node.log`) |
| `node --check` on every `web/` JavaScript module | 44 passed. Log (`/workspace/tmp/hearth-qa/run81/js-syntax.log`) |
| `PYTHONPATH=. python tests/browser-smoke.py` | Passed in 107 seconds. Log (`/workspace/tmp/hearth-qa/run81/chromium-smoke.log`) |
| `PYTHONPATH=. python tests/browser-smoke.py --disconnect` | Passed. Log (`/workspace/tmp/hearth-qa/run81/chromium-disconnect.log`) |
| `PYTHONPATH=. python tests/browser-smoke.py --chat-search` | Passed. Zero horizontal overflow across 390–1920 px. Log (`/workspace/tmp/hearth-qa/run81/chromium-chat-search.log`) |

The 85-second CI wrapper timed out on this host. The full suite passed with more time. The saved Run 80 snapshot also passed with more time, taking about 110 seconds here. The mobile thread menu check now waits for the drawer to finish sliding before measuring the 44 px hit target. Chromium could round its moving bounds down to 43.99998 px. Baseline timings (`/workspace/tmp/hearth-qa/run81/chromium-baseline-timed.log`) · Drawer measurement trace (`/workspace/tmp/hearth-qa/run81/chromium-mobile-thread-stress.log`)

An early search run missed focus after quickly reopening with `/` after Escape. The dedicated suite rerun and 40 subsequent rapid reopen checks across fresh light and dark pages passed. The cause of the first failure remains unconfirmed. Focus rerun log (`/workspace/tmp/hearth-qa/run81/chromium-search-stress.log`)

## Open risks

- The workspace startup depends on native import-map support and an exact match between the inline map and its CSP hash. Keep the asset allowlist and the hash in sync when changing vendor versions.
- Preact and existing controllers share the Chat view. The controllers own the native popover and dialog shells, draft and audio controls, and embedded message cards. Keep those boundaries explicit when changing effects, focus or scroll timing, and transcript reconciliation.
- The visual checks cover settled Chromium frames. The voice-input test uses mocked browser speech recognition. Live transcription, call providers, microphone permission flows, and other browser engines remain outside this verification.

## Phase 2 · Settings

Move the Settings navigation, persistent disclosures, and forms out of `app.js` one group at a time. Preserve section links and browser history, draft and pending-save state, validation and live feedback, connector tabs and test results, polling, and focus on entry and exit. Route changes to appearance and voice through the shared Chat state. Keep the existing API and form contracts while exercising the Settings and Chat integration in Chromium.

## Phase 3 · Remaining views

Mount each page in its existing container and retain its navigation, loading state, and focus behavior. Verify each migration against the equivalent Run 80 view before removing its legacy renderer.

| View | Behavior to carry over |
| --- | --- |
| Artifacts | Format filters, file and page previews, drawers, downloads, and file Q&A links into Chat |
| Automation and Reminders | Editors, task scopes, approval and delivery flows, pending operations, and searchable lists |
| Home | Panel layout persistence, reordering and animations, Add panel, and handoff to Chat |
| Timeline | Searchable thread filter, pagination, live updates, and undo, redo, and restore actions |
| Memory | Search, recall and review, source links, and thread selection |
| Skills | Search and deep links, editor and version history, preview, and Try in Chat |
| Inbox | Search and history, polling, message actions, and empty and stale states |
