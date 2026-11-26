# Run 78 · Search in Chat

Open **Search chats** from the Chat header, with Cmd/Ctrl+K, or with `/` while focus is outside an editing control. **All chats** groups matching messages by thread, ordered by each group’s newest match. Arrow keys select a result, Enter opens it, and Escape returns focus. The desktop panel is anchored to the header button. At 760 px and below, it opens as a full-screen sheet.

Choose **This chat** to open the find bar above the transcript. The arrow buttons, Up/Down keys, and Enter/Shift+Enter move between matching messages. The count covers the entire thread, including messages outside the loaded transcript. Older results load a 50-message window around the selected message. **Back to latest** restores the live end of the transcript. Search jumps scroll immediately and use a temporary outline and tint. The outline transition is disabled with reduced motion.

`GET /api/chat/search?q=&thread=&limit=&before=` accepts a trimmed query of 2–200 characters. The optional thread filter returns an exact count. Results use a newest-first cursor and a maximum page size of 50. Hearth’s JSONL files and legacy Main state remain the source of truth. The process builds a disposable SQLite index with indexes for workspace and per-thread ordering, then uses literal, case-folded and accent-folded substring matching. Searches refresh changed files and remove deleted threads from the index. Results contain sanitized user and assistant text, with the highlight represented as text fragments. The endpoint uses Sprite’s private workspace authentication in production and rejects cross-origin browser requests.

## Verification

- Python covered Unicode matching, thread filtering, pagination and limits, legacy data, index refresh, access boundaries, hidden content, and centered transcript windows. Node covered shortcuts, grouping, relative dates, and transcript state. [Python log](/workspace/tmp/hearth-qa/run78/python.log) · [Node log](/workspace/tmp/hearth-qa/run78/node.log) · [JavaScript syntax log](/workspace/tmp/hearth-qa/run78/js-syntax.log)
- Chromium verified opening a result outside the loaded page, keyboard and pointer stepping, search states, request cancellation, literal HTML rendering, and reduced-motion behavior. Search used temporary fixture workspaces. The 390–1920 px sweep checked every integer width for horizontal overflow. Search text met 4.5:1 contrast in both schemes, and the keyboard selection outline met 3:1. Mobile controls met the 44 px target size. [Chat search smoke](/workspace/tmp/hearth-qa/run78/chromium-search.log) · [Workspace smoke](/workspace/tmp/hearth-qa/run78/chromium-smoke.log) · [Stream disconnect smoke](/workspace/tmp/hearth-qa/run78/chromium-disconnect.log)
- The release smoke checks the deployed SHA in `GET /health`, validates the shape of a harmless `GET /api/chat/search` response without printing message text, and checks the anonymous Sprite edge. [Deploy log](/workspace/tmp/hearth-qa/run78/deploy.log) · [Release smoke](/workspace/tmp/hearth-qa/run78/live-smoke.log)

## Screenshots

- [Search, 1440 px light](/workspace/tmp/hearth-qa/run78/chat-search-1440-light.png)
- [Search, 1440 px dark](/workspace/tmp/hearth-qa/run78/chat-search-1440-dark.png)
- [Jump to a search result, 1440 px light](/workspace/tmp/hearth-qa/run78/chat-search-jump-1440-light.png)
- [Find in chat, 1440 px light](/workspace/tmp/hearth-qa/run78/chat-find-in-thread-1440-light.png)
- [Search, 390 px light](/workspace/tmp/hearth-qa/run78/chat-search-390-light.png)
