# Run 86 · Chat search pointer jump

Clicking a desktop Chat search result could focus the native dialog on mouse-down. The document focus handler treated the dialog as outside the inner search section and dismissed it before the click reached the result. Both outside-interaction handlers now use the entire dialog and the search trigger as their boundary. [Run 85 D1](run-85.md#d1--medium--clicking-a-desktop-chat-search-result-closes-the-popover-without-jumping) · [Chat search controller](../web/chat/search.js)

The regression uses a real browser click on the highlighted term in a result. It checks that Hearth requests `GET /api/state` with the side chat ID and `around=greenhouse-hit`, switches from Main to Weekend greenhouse, and scrolls the highlighted message into view and focuses it. It also checks that both scope buttons work, the search input takes focus, Escape returns focus to the trigger, and an outside click dismisses the popover and focuses the clicked composer. Before the fix, Chromium timed out waiting for the message-location request. [Regression](../tests/chat_search_smoke.py) · [Before-fix log](/workspace/tmp/hearth-qa/run86/chromium-before.log)

| Browser | Desktop pointer regression |
| --- | --- |
| Chromium 159.0.8154.6 | Passed with normal motion. [Log](/workspace/tmp/hearth-qa/run86/pointer-chromium.log) |
| WebKitGTK 27.2 | Passed with reduced motion. [Log](/workspace/tmp/hearth-qa/run86/pointer-webkit.log) |
| Firefox 159.0 | Passed with normal motion. [Log](/workspace/tmp/hearth-qa/run86/pointer-firefox.log) |

Chromium captured the highlighted message after the click in the local offline fixture at 1440 × 900 in light mode. [Screenshot](/workspace/tmp/hearth-qa/run86/chat-search-click-jump-1440-light.png)

## Suites

| Suite | Result |
| --- | --- |
| Python unittest discovery | 342 passed. [Log](/workspace/tmp/hearth-qa/run86/python.log) |
| Node tests | 37 passed. [Log](/workspace/tmp/hearth-qa/run86/node.log) |
| JavaScript syntax | 63 frontend modules passed. [Log](/workspace/tmp/hearth-qa/run86/syntax.log) |
| Chromium smoke and stream disconnect | Passed. The smoke includes Settings and searchable combobox coverage. [Smoke](/workspace/tmp/hearth-qa/run86/suite-default.log) · [Disconnect](/workspace/tmp/hearth-qa/run86/suite-disconnect.log) |
| Chromium Chat search, list search, and motion | Passed, with Chat and list search overflow sweeps at every integer width from 390 to 1920 px. [Chat search](/workspace/tmp/hearth-qa/run86/suite-chat-search.log) · [List search](/workspace/tmp/hearth-qa/run86/suite-list-search.log) · [Motion](/workspace/tmp/hearth-qa/run86/suite-motion.log) |
| Chromium contrast sweep | 16,701 measurements with zero failures. [Log](/workspace/tmp/hearth-qa/run86/contrast.log) |

The first dedicated Chat search run sampled the selected option’s background during its color transition. The contrast assertion now waits for that transition to settle. The dedicated suite passed on rerun. [Initial failure](/workspace/tmp/hearth-qa/run86/suite-chat-search-before-contrast-wait.log)

## Release

The first commit was `3e5e598` (`Document Run 85 full-flow QA`). `scripts/deploy.sh` deployed `95e93f049d686a20baaa3b2f5100ae53d5050da9` to the `hearth` Sprite. The Sprite’s `/health` returned HTTP 200 with the new SHA, and the served `/chat/search.js` matched the deployed commit byte for byte. No commits were pushed. [Deploy](/workspace/tmp/hearth-qa/run86/deploy.log) · [Health](/workspace/tmp/hearth-qa/run86/health.log) · [Served asset verification](/workspace/tmp/hearth-qa/run86/live-asset.log)
