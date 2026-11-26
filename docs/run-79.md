# Run 79 · Search Reminders, Inbox, and Skills

Use the search field under the page heading or press `/` while focus is outside an editing control. Results update after 150 ms of idle typing. Matches are case- and accent-insensitive. The toolbar shows a result count, and both the field and the empty state offer a **Clear search** action. The browser hash stores the query for reload, Back, and Forward.

- Reminders cover titles, notes, delivery channels, and due text across Upcoming, Snoozed, Delivered, and Outbox. Due dates use a consistent English format in the workspace time zone so the text on screen can be searched directly. The Recurring tasks tab keeps its own list.
- Inbox searches email cards in Review and Processed by sender or original sender, subject, summary, body preview, and labels or proposal category. Ingestion now retains display names, original subjects, previews, and labels when AgentMail supplies them. Older cards are searchable by their retained fields.
- Skills search the current versions of built-in and custom playbooks by name, description, `when_to_use`, optional YAML `tags`, and Markdown body. Body and metadata matches include a highlighted excerpt.

The existing `GET /api/reminders`, `GET /api/inbox`, and `GET /api/skills` endpoints accept an optional trimmed `q` of 1–200 characters. Each endpoint searches the complete stored collection and retains its existing authentication rules. The browser builds highlights from text fragments and `mark` elements.

## Verification

- Python endpoint and workspace tests, Node tests, and JavaScript syntax checks. [Python](/workspace/tmp/hearth-qa/run79/python.log) · [Node](/workspace/tmp/hearth-qa/run79/node.log) · [JavaScript syntax](/workspace/tmp/hearth-qa/run79/js-syntax.log)
- Chromium verifies typing, debounce, clear, browser history, reload, task-tab scope, literal markup, and contrast in both themes. The responsive sweep checks every integer width from 390 to 1920 px. Browser tests use a temporary fixture workspace with gateway requests blocked. [List search](/workspace/tmp/hearth-qa/run79/chromium-list-search.log) · [Workspace smoke](/workspace/tmp/hearth-qa/run79/chromium-smoke.log) · [Chat search](/workspace/tmp/hearth-qa/run79/chromium-chat-search.log) · [Stream disconnect](/workspace/tmp/hearth-qa/run79/chromium-disconnect.log)
- The release check verifies the deployed SHA in `GET /health`, runs read-only search requests using a fixture probe, and checks the signed-out Sprite edge. [Deploy](/workspace/tmp/hearth-qa/run79/deploy.log) · [Release smoke](/workspace/tmp/hearth-qa/run79/live-smoke.log)

## Screenshots

- [Reminders, 1440 px light](/workspace/tmp/hearth-qa/run79/reminders-search-1440-light.png)
- [Reminders, 1440 px dark](/workspace/tmp/hearth-qa/run79/reminders-search-1440-dark.png)
- [Inbox, 1440 px light](/workspace/tmp/hearth-qa/run79/inbox-search-1440-light.png)
- [Inbox empty state, 1440 px light](/workspace/tmp/hearth-qa/run79/inbox-search-empty-1440-light.png)
- [Inbox, 390 px light](/workspace/tmp/hearth-qa/run79/inbox-search-390-light.png)
- [Skills, 1440 px light](/workspace/tmp/hearth-qa/run79/skills-search-1440-light.png)
- [Skills, 390 px light](/workspace/tmp/hearth-qa/run79/skills-search-390-light.png)
