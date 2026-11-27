# Architecture

Hearth uses Python’s standard-library `http.server` for HTTP and serves the browser assets directly. The server streams chat replies, tool results, and Timeline updates using server-sent events. Main and side chats keep separate transcripts and queues. They share memory, reminders, and approvals. Queued turns live in process memory until execution starts. [Server](../hearth/server.py), [Threads](../hearth/threads.py), [Timeline](../hearth/timeline.py)

## Frontend

`web/index.html` defines the shell, desktop and mobile navigation, and mount points. It loads `web/app.js` as a native ES module. The inline import map resolves `preact`, `preact/hooks`, and `htm` to the vendored Preact 10.29.8 core and hooks and htm 3.1.1 files under `web/vendor/`. Preact components use htm tagged templates, and the browser loads the shipped files directly with no build step. The workspace Content Security Policy authorizes the exact inline import-map text with a SHA-256 hash. [HTML shell](../web/index.html), [Static asset allowlist and CSP](../hearth/server.py), [Updating dependencies](development.md#update-vendored-frontend-dependencies)

`web/app.js` wires controllers together, switches views, and coordinates polling and workspace routes. Controllers own fetching and actions for their views. Preact renders into stable mount points so controllers can manage native dialogs and restore focus and scroll after updates. The shared `web/store.js` provides `createStore`, `useAppState`, and `mountStore`. Each mount can subscribe to selected keys and render synchronously before a controller reads the updated DOM. The Chat composer and Settings Appearance panel share avatar state through the Chat store. [App shell](../web/app.js), [Store](../web/store.js), [Chat controller](../web/chat/workspace.js), [Settings Appearance](../web/settings/persona.js)

| Directory | Responsibility |
| --- | --- |
| [web/chat/](../web/chat/) | Threads, streamed conversation, composer, and message search |
| [web/settings/](../web/settings/) | Settings sections, connector forms, brain and model configuration, preferences, and workspace status |
| [web/artifacts/](../web/artifacts/) | File and Page library, previews, and Ask my files |
| [web/automation/](../web/automation/) | Recurring tasks, event rules, and approval cards |
| [web/reminders/](../web/reminders/) | Reminder delivery settings and scheduled reminder lists |
| [web/home/](../web/home/) | Dashboard panels, layout editor, and Feed |
| [web/timeline/](../web/timeline/) | Activity stream, filters, details, and Undo |
| [web/memory/](../web/memory/) | Notes, profile, recall results, and nightly review |
| [web/skills/](../web/skills/) | Skill library, editor, and version history |
| [web/inbox/](../web/inbox/) | Mail review, processed items, and proposal editing |

The thread row reserves space for its **⋯** action. It shows the action on desktop hover, keyboard focus, and while the menu is open. The mobile drawer keeps the action visible. The menu uses the Popover API and CSS anchor positioning where supported, with a JavaScript fallback that keeps it within the viewport. [Thread rows](../web/chat/threads.js), [Popover controller](../web/thread-menu.js), [Placement tests](../tests/thread-menu.test.mjs)

Searchable single-choice selects keep the native select as the source of the value and form events. Controls with nine or more options or the `data-searchable` attribute get a picker that matches labels and values without regard to case or accents. Shared list search on Reminders, Inbox, and Skills sends `q` to each existing list endpoint and stores the query in the URL hash. The browser renders highlights from text fragments. [Combobox](../web/combobox.js), [List search](../web/list-search.js), [List search tests](../tests/test_list_search.py)

Motion uses shared 120, 200, and 320 ms duration tokens. Navigation uses the View Transitions API when available. Popovers and sheets animate from their trigger or screen edge, and Home reorders animate from measured panel positions. With `prefers-reduced-motion: reduce`, view and position animations are skipped, scaling is disabled, and surfaces can still fade. [Theme tokens](../web/theme.css), [Motion styles](../web/motion.css), [Motion controller](../web/motion.js), [Adding a view](development.md#add-a-workspace-view)

## HTTP and workspace access

The route registry declares allowed method and path pairs, including full-match patterns for private Page and screenshot paths. Unknown paths return `404`. A known path with the wrong method returns `405` with an `Allow` header. Registered writes declare their body format, schema, and byte limit. JSON routes require a UTF-8 object and reject duplicate keys and undeclared fields. Invalid framing or fields return `400`, and oversized bodies return `413` before the body is read. Audio and multipart uploads have their own limits. Domain services still check object membership and business rules. [Route registry](../hearth/http_routes.py), [Request parsing](../hearth/http_requests.py), [Validation rules](run-55.md#request-policy)

Sprite URL authentication protects the production workspace. The app also checks browser origin and Fetch Metadata on POSTs and selected GETs, including the Timeline event stream and Chat search. Scheduler and proactivity tick routes require a separate tick token. During filesystem restore, static assets, `/health`, `/api/status`, `/api/state`, and `/api/home` stay available. Other registered routes return `503` with `Retry-After: 2` after applicable authorization checks. [Server](../hearth/server.py), [Route registry](../hearth/http_routes.py), [Deployment](deploy.md)

## A chat turn

1. The server puts the prompt in its thread queue. The agent gathers available attachment context and memory excerpts.
2. The brain uses Mock, a fixed model, or a Smart routing pool. The router uses the kind of request and recent model performance to order the pool. Before acting, the agent can load a matching playbook from the prompt's compact skills index. A side chat created through **Try it** loads its selected skill automatically. The agent can try another model on failure and avoids replay after a tool has changed state.
3. Local tools read and write workspace files. Outbound provider requests go through Fly's gateway, which supplies credentials for the selected connection. Sensitive tool actions follow the approval rules before execution.
4. The browser receives reply deltas and tool cards. Hearth persists the final reply with its prompt ID in `reply_to` and emits `done` before running summary model work. Timeline records activity. The parent and worker tool loops share argument checks and result size caps. Parent chat also budgets total model context.

[Agent loop](../hearth/agent.py), [Shared tool handling](../hearth/tool_calls.py), [Routing](../hearth/router.py), [Approvals](approvals-and-tasks.md), [Summary executor](memory.md#long-chats)

## Polling and chat history

`GET /api/state` and `GET /api/home` cache snapshots keyed by workspace revisions and other inputs that affect the response. State also accounts for active turns, connector capabilities, and approval expiry. With a matching `If-None-Match`, an unchanged cached snapshot returns `304` without acquiring the workspace lock or serializing the body. Home builds its bounded activity preview from recent storage records. [Server](../hearth/server.py), [Home](../hearth/home.py), [Polling benchmark](run-51.md)

State starts with the latest 50 chat messages and up to 100 sidebar entries, plus the selected thread if it falls outside that page. The browser loads additional sidebar entries through `/api/threads?offset=…` and older messages through `/api/transcript?thread=…&before=…`. A transcript page includes its linked approval, worker, and attachment data. Prepending it preserves the visible scroll position. Foreground Chat and Home poll about every three seconds during active work and every 12 seconds while idle. Polling pauses in hidden tabs and refreshes on return or focus. [Thread storage](../hearth/threads.py), [Browser app](../web/app.js)

The browser reconciles streamed events, snapshots, and transcript pages in a per-thread model. After a stream disconnect, polling finds the saved reply by `reply_to` and replaces the partial bubble without resending the prompt. A polite live region announces completed replies once in the open thread. Streamed tokens leave it quiet. Send and completed Stop return focus to the composer. Desktop thread switches keep focus on the thread button, and mobile drawer switches move focus to the destination heading. [Chat state](../web/chat-state.js), [SSE parser](../web/sse.js), [Browser checks](testing.md#offline-chromium-smoke)

### Chat search

In Chat, the header button, Cmd/Ctrl+K, or `/` outside an editing control opens **Search chats**. **All chats** groups matching messages by thread. Selecting a result with the pointer or keyboard focuses the matched message. **This chat** opens a find bar with previous and next controls and a count across the entire thread. If a hit is outside the loaded transcript, `GET /api/state?thread=…&around=…` loads a window around it. **Back to latest** returns to the live end of the thread. [Search controller](../web/chat/search.js), [Browser regression](../tests/chat_search_smoke.py)

`GET /api/chat/search` takes a trimmed `q` from 2 to 200 characters and optional `thread`, `limit`, and `before` parameters. It returns newest-first results with a cursor and a page size capped at 50. A thread filter also returns a total match count. The backend uses a disposable SQLite index over workspace transcripts and legacy Main history. It matches literal text without regard to case or accents, excludes private roles and tool markup, and returns text fragments for highlights. [Search implementation](../hearth/chat_search.py), [Search API tests](../tests/test_chat_search.py)

## Parallel workers

`spawn_workers` gives the current model one batch of up to six independent assignments per turn. A shared thread pool starts jobs from all chats and recurring tasks in queue order. **Settings → Brain → Parallel workers** controls how many can run at once, from one to six with a default of four. Each worker has a separate model conversation and tool state. Its tools come from the parent turn, including the active skill's allowlist, with an optional narrower list per assignment. The parent receives structured findings in assignment order and writes the final reply.

A worker has 75 seconds from queuing, at most four tool calls and five model rounds, and an output budget of 2,048 tokens per round. Chat workers pause on the normal approval card, which names the worker. Recurring workers can hand the approval off to the task's Inbox notification. Stopping a worker withdraws its pending proposals and prevents subsequent steps. An in-flight connector call can take time to drain and retains its pool slot during cleanup. Connector actions already in execution can still finish.

Chat streams worker snapshots as `worker` events. The saved snapshots restore the Workers card after reload, supply the active list on Home, and produce one Timeline entry per worker. A server restart marks interrupted workers as failed. Browserbase sessions share a separate two-session limit across chat, workers, and approvals in the web process. Hearth requests release in cleanup and retains the slot until the provider's session deadline if release is unconfirmed. Fetch and Search use no live session.

Queue and start persist status before registering a worker or reserving its slot. A storage failure ends the affected assignment with a sanitized error. Finish releases the slot and wakes waiting turns even if the terminal write fails. Hearth reloads the last durable snapshot to reconcile the failure and withdraw pending worker approvals. Later dispatches or **Stop all** retry a failed reconciliation. Restore requests can proceed after in-flight worker tools finish. [Worker pool](../hearth/workers.py), [Worker fault tests](../tests/test_worker_faults.py), [Browserbase](../hearth/browserbase.py)

## Workspace and background work

| State | Where it lives |
| --- | --- |
| Markdown notes, state, and JSONL conversations | `live/memory/`, `live/state.json`, and `live/threads/` under the data directory |
| Skill Markdown and versions | `live/skills/` and `live/skills/.versions/` under the data directory |
| Generated files, page versions, and attachments | Workspace disk, with optional artifact copies in Box |
| Recall | Markdown and enabled sources on disk, with derived indexes and an optional Pinecone namespace |
| Reminder email delivery journal | `reminder-delivery.json` in the data directory, outside `live/` |
| Deployment | `~/hearth/current` points to a release. `~/hearth/data` and `~/hearth/config` persist separately from releases. |

The Sprite installer registers web and scheduler services. Both can claim due reminder occurrences under the workspace lock. The web process starts delivery and other background work separately from the claim, so the authenticated tick can return before providers respond. An external tick can wake the Sprite while browsers are closed. Home can call Open-Meteo directly. Browser voice calls join a LiveKit room after the Hearth server requests a session credential through Vocal Bridge. [Delivery and restore](approvals-and-tasks.md#scheduler-delivery-and-restore), [Deploy and wake](deploy.md#wake-the-scheduler), [Voice](voice.md)

## Status and stale data

`/health` reports process liveness and checkpoint mode. `/api/status` reports fixed subsystem names (`http`, `scheduler`, and `box_recall`), last success and failure times, sanitized failure codes, and process-local failure counts. Box recall retains cached sources on refresh failure and saves the last full success with its snapshot. Its status is separate from the Artifacts listing cache. [Status registry](../hearth/subsystem_status.py), [Box recall and listings](box.md)

Affected views keep their contents after a failed background refresh. After two consecutive failures, the heading shows **Stale** with **Offline**, **Disconnected**, or **Server error**. The next successful refresh clears it, including a `304` on a conditional poll. [Status and UI checks](run-57.md)

## Checkpoints and Undo

Hearth uses local snapshots of `live/` during development and `sprite-env checkpoints` for native Sprite snapshots. Snapshot-backed actions include side-chat deletion and approved sends. Note edits also keep before and after text so Timeline can undo or redo those edits in place. Reminders, recurring-task deletions, page edits, artifact changes, and skill versions have their own reversal paths. Box artifact restoration can write a new Box version when the previous bytes are available.

A local restore replaces `live/`, advances workspace and thread revisions, and reconciles reminder email from the journal. A native restore can rewind the whole Sprite filesystem. Hearth blocks native restores that could erase journaled delivery evidence or have a reminder delivery pending reconciliation. The restore barrier pauses scheduler claims across processes. Provider sends and writes persist outside the filesystem snapshot. [Checkpoint code](../hearth/checkpoints.py), [Delivery and restore](approvals-and-tasks.md#scheduler-delivery-and-restore), [Artifact reversal](../hearth/artifacts.py), [Memory edits](../hearth/memory_edits.py)

## Published Pages

Private previews use a sandbox and a restrictive content security policy. Approved sharing copies one sanitized version to an optional share-only Sprite. Anyone with the link can read the snapshot until it is revoked. The share-only process serves token-addressed HTML and accepts authenticated publish and revoke requests. Workspace APIs run on the private Sprite. [Pages code](../hearth/pages.py), [Public handler](../hearth/page_public.py), [Publisher deployment](deploy.md#publish-html-snapshots)

## Automation events

Inbox polling and reminder firing persist matching run claims in workspace state. The web runner also checks due schedules and eligible new Feed cards. Runs store ordered action progress and reuse the existing approval receipts for outbound actions. A run interrupted during an action shows an unconfirmed outcome. Timeline reads persisted run states and can undo individual local changes. [Automations](approvals-and-tasks.md#event-triggered-automations)
