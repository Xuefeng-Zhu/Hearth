# Run 85 · Full-flow QA after the Preact migration

Production Chromium passed the read-only walkthrough at 1440 × 900 and 390 × 844 in light and dark. The local workspace used the same `55e386f` checkout with the real Hearth HTTP server, temporary storage, and offline fixtures. Desktop mouse selection in Chat search failed on the migration and the pre-migration baseline.

## Production · Chromium

The Sprite served HTTP 200 from `/health` and reported `55e386f7905bfb401f076b376641943753523a65`. The browser used a local read-only relay backed by `sprite exec` and the Sprite's port 8080. The production HTML and API reads came from the live listener. The relay served 89 SHA-256-verified frontend assets from the matching local checkout. It verified Timeline's initial server-sent event and kept the browser connection open locally for the walkthrough. Live event delivery after the initial event was outside this check.

| Read-only flow | 1440 light | 1440 dark | 390 light | 390 dark |
| --- | --- | --- | --- | --- |
| Home navigation, Edit layout, Add panel, close, Done | Pass | Pass | Pass | Pass |
| Chat navigation, Cmd+K, search and scope toggle, thread actions menu | Pass | Pass | Pass | Pass |
| Timeline search, detail and Raw, searchable comboboxes or mobile filter sheet | Pass | Pass | Pass | Pass |
| Artifacts search, sort, grid/list, preview and Ask my files sheet | Pass | Pass | Pass | Pass |
| Reminders search, new reminder disclosure and channel, Recurring tasks tab | Pass | Pass | Pass | Pass |
| Inbox search and email source disclosure | Pass | Pass | Pass | Pass |
| Memory tabs and search field | Pass | Pass | Pass | Pass |
| Skills search, editor open and close, Markdown preview | Pass | Pass | Pass | Pass |
| Settings disclosures and configured/unconfigured Connections search | Pass | Pass | Pass | Pass |
| Desktop navigation or mobile workspace drawer, including dismissal | Pass | Pass | Pass | Pass |

Settings covered Brain, Memory, Search, Voice, Connections, Artifacts, Reminders, Feed, Action suggestions, Automations, Watchers, Approvals, Home, Appearance, and About. The Home editor calls its exit button **Done**. Layout changes persist as they happen, so the walkthrough entered edit mode, opened and closed Add panel, and exited before making any layout changes.

The guard intercepted automatic Inbox polls and Connections rescans. For Connections, it returned the result of the live read-only GET. Memory recall submission records a Timeline entry, so the live run stopped at the search field and used the local fixture for submission. No create, edit, send, deletion, merge, or execution request reached production. The final walkthrough logged zero console errors, page exceptions, or unhandled rejections. Timeline's event request was canceled on navigation in each configuration after HTTP 200.

1440 light log (`/workspace/tmp/hearth-qa/run85/production-chromium-1440-light.log`) · 1440 dark log (`/workspace/tmp/hearth-qa/run85/production-chromium-1440-dark.log`) · 390 light log (`/workspace/tmp/hearth-qa/run85/production-chromium-390-light.log`) · 390 dark log (`/workspace/tmp/hearth-qa/run85/production-chromium-390-dark.log`)

## Local · Browser flow matrix

Chromium 159.0.8154.6, WebKitGTK 27.2, and Firefox 159.0 ran on Linux ARM64 through Playwright. The WebKit column uses the reduced-motion setting for the complete flow checks. Normal-motion WebKit navigation crashed in this host's graphics setup. The same crash occurred on a standalone View Transition example and on the pre-migration build with normal motion, while those checks passed with reduced motion.

| Flow | Chromium | WebKit | Firefox |
| --- | --- | --- | --- |
| Send Chat message, observe partial SSE reply, render completed reply | Pass | Pass | Pass |
| Stop an active Chat reply and verify stopped state | Pass | Pass | Pass |
| Upload and send a text attachment | Pass | Pass | Pass |
| Create, rename, reload and delete a side chat | Pass | Pass | Pass |
| Cmd+K and keyboard jump to a matching message | Pass | Pass | Pass |
| Desktop mouse click to jump to a Chat search result | Fail · D1 | Fail · D1 | Fail · D1 |
| Edit a reminder draft, schedule it, reload and cancel with Undo | Pass | Pass | Pass |
| Edit a saved one-off reminder in place | Unavailable | Unavailable | Unavailable |
| Create and edit a recurring task, persist schedule after reload | Pass | Pass | Pass |
| Inbox direct Accept, edit and accept, and Dismiss | Pass | Pass | Pass |
| Preview DOCX and saved HTML page, download and verify DOCX contents | Pass | Pass | Pass |
| Edit a skill, preview Markdown, inspect version history and reload | Pass | Pass | Pass |
| Submit recall search, reject a Memory proposal and accept another | Pass | Pass | Pass |
| Save Settings and verify reloaded values | Pass | Pass | Pass |
| Edit Home, reorder, add, hide and restore panels | Pass | Pass | Pass |
| Reduced-motion Home reorder and Chat search popover | Pass | Pass | Pass |
| Dictation with fake media and mocked recognition | Pass | Pass | Pass |
| Call UI with fake media and mocked Vocal Bridge module | Pass | Pass | Pass |

Settings saves covered Brain, Memory, Search, Voice, call preferences, Appearance, Artifacts, Reminders, Feed, Action suggestions, Approvals, and the Home weather location. The call check exercised connect, captions, mute, minimize, reopen, end, and saving the call card. **A real microphone and a real Vocal Bridge call were outside this run.** The fixture supplied a fake stream and audio track, a simulated speech recognizer, and a locally mocked call SDK. Real provider connections, email sends, and live browser speech services were outside the local tests.

A saved one-off reminder offers Undo to cancel. The UI and API at both revisions have no edit action for a saved one-off reminder. The draft edit and saved recurring-task edit were exercised separately. Saved reminder actions (`/workspace/tmp/hearth-qa/run85/one-off-reminder-actions.png`)

The task update and settings persistence checks were repeated after refining the QA steps to preview the schedule before saving and assert reloaded field values. Firefox attachments and Home mutations passed in a targeted reduced-motion pass. Firefox's additional 390 px emulated-touch geometry check crashed after opening Home's Add panel sheet on both revisions. The focused Home test covered the requested data changes at desktop width. WebKit dictation and call passed with a fake media object and keyboard activation. Firefox baseline touch check (`/workspace/tmp/hearth-qa/run85/baseline-firefox-home.log`)

Playwright screenshot capture triggered WebKit's inline stylesheet CSP warning. A separate probe recorded no CSP events before capture and one `style-src-elem` event after it. The raw console log also includes the initial production relay setup errors. Screenshot CSP probe (`/workspace/tmp/hearth-qa/run85/webkit-csp-probe.log`)

Chromium log (`/workspace/tmp/hearth-qa/run85/local-chromium.log`) · WebKit log (`/workspace/tmp/hearth-qa/run85/local-webkit.log`) · Firefox log (`/workspace/tmp/hearth-qa/run85/local-firefox.log`) · Console errors and unhandled rejections (`/workspace/tmp/hearth-qa/run85/console-error.log`) · WebKit motion isolation (`/workspace/tmp/hearth-qa/run85/webkit-transition.log`)

Chromium task and settings rerun (`/workspace/tmp/hearth-qa/run85/local-chromium-rechecked.log`) · WebKit task and settings rerun (`/workspace/tmp/hearth-qa/run85/local-webkit-rechecked.log`) · Firefox targeted rerun (`/workspace/tmp/hearth-qa/run85/local-firefox-focused.log`) · WebKit voice rerun (`/workspace/tmp/hearth-qa/run85/local-webkit-media.log`)

## Defects

### D1 · Medium · Clicking a desktop Chat search result closes the popover without jumping

At a desktop width, open Chat, press Cmd+K, and search across all chats for a phrase with results. In the offline fixture, search for `orchid`. Click the first result. The search popover closes and the current thread stays open. The browser focuses the enclosing popover dialog on mouse-down, and the document's focus handler closes it before the result receives the click. The expected `/api/state` request with the matched message location never fires. Arrow Down followed by Enter opens the message in its thread.

Chromium reproduced the same event sequence at `55e386f` and `f58a3fe`. This issue predates the Preact migration. Before clicking (`/workspace/tmp/hearth-qa/run85/local-chromium-chat-search-before-click.png`) · After clicking (`/workspace/tmp/hearth-qa/run85/local-chromium-chat-search-pointer-1.png`) · Baseline repro (`/workspace/tmp/hearth-qa/run85/chat-pointer-baseline.log`) · Migration repro (`/workspace/tmp/hearth-qa/run85/chat-pointer-current.log`)

## Suites and release

| Suite | Result |
| --- | --- |
| Python unittest discovery | 342 passed on an exact checkout archive on local disk. The earlier runs hit three-second scheduler subprocess timeouts while browser checks were running. Passing run (`/workspace/tmp/hearth-qa/run85/python-isolated.log`) · Earlier run (`/workspace/tmp/hearth-qa/run85/python-rerun.log`) |
| Node unit tests | 37 passed. Log (`/workspace/tmp/hearth-qa/run85/node.log`) |
| JavaScript syntax | 63 modules passed, including 59 first-party files. Log (`/workspace/tmp/hearth-qa/run85/syntax-all.log`) |
| Chromium offline smoke and stream disconnect | Pass. Smoke (`/workspace/tmp/hearth-qa/run85/suite-default.log`) · Disconnect (`/workspace/tmp/hearth-qa/run85/suite-disconnect.log`) |
| Chromium Chat search, list search, and motion | Pass. The pre-existing Chat-search suite covers keyboard selection. Chat search (`/workspace/tmp/hearth-qa/run85/suite-chat-search.log`) · List search (`/workspace/tmp/hearth-qa/run85/suite-list-search.log`) · Motion (`/workspace/tmp/hearth-qa/run85/suite-motion.log`) |

No migration regression was confirmed. Production remains on `55e386f`. There was no deploy or push. Final health check (`/workspace/tmp/hearth-qa/run85/health-final.log`)
