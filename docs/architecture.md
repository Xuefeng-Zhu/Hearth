# Architecture

The browser loads HTML, CSS, and JavaScript from [the Python server](../hearth/server.py). The server streams chat replies, tool results, and Timeline updates using server-sent events. Main and side chats keep separate transcripts and queues. They share memory, reminders, and approvals. Queued turns live in process memory until execution starts. [Threads](../hearth/threads.py), [Timeline](../hearth/timeline.py)

## A chat turn

1. The server puts the prompt in its thread queue. The agent gathers available attachment context and memory excerpts.
2. The brain uses Mock, a fixed model, or a Smart routing pool. The router uses the kind of request and recent model performance to order the pool. Before acting, the agent can load a matching playbook from the prompt's compact skills index. A side chat created through **Try it** loads its selected skill automatically. The agent can try another model on failure and avoids replay after a tool has changed state.
3. Local tools read and write workspace files. Outbound provider requests go through Fly's gateway, which supplies credentials for the selected connection. Sensitive tool actions follow the approval rules before execution.
4. The browser receives reply deltas and tool cards. The final message is stored in the thread and activity is recorded in Timeline.

[Agent loop](../hearth/agent.py), [Routing](../hearth/router.py), [Gateway client](../hearth/connectors.py), [Approvals](approvals-and-tasks.md)

## Parallel workers

`spawn_workers` gives the current model one batch of up to six independent assignments per turn. A shared thread pool starts jobs from all chats and recurring tasks in queue order. **Settings → Brain → Parallel workers** controls how many can run at once, from one to six with a default of four. Each worker has a separate model conversation and tool state. Its tools come from the parent turn, including the active skill's allowlist, with an optional narrower list per assignment. The parent receives structured findings in assignment order and writes the final reply.

A worker has 75 seconds from queuing, at most four tool calls and five model rounds, and an output budget of 2,048 tokens per round. Chat workers pause on the normal approval card, which names the worker. Recurring workers can hand the approval off to the task's Inbox notification. Stopping a worker withdraws its pending proposals and prevents subsequent steps. An in-flight connector call can take time to drain and retains its pool slot during cleanup. Connector actions already in execution can still finish.

Chat streams worker snapshots as `worker` events. The saved snapshots restore the Workers card after reload, supply the active list on Home, and produce one Timeline entry per worker. A server restart marks interrupted workers as failed. Browserbase sessions share a separate two-session limit across chat, workers, and approvals in the web process. Hearth requests release in cleanup and retains the slot until the provider's session deadline if release is unconfirmed. Fetch and Search use no live session.

[Worker pool](../hearth/workers.py), [Browserbase](../hearth/browserbase.py), [Chat and worker API](../hearth/server.py)

## Workspace and background work

| State | Where it lives |
| --- | --- |
| Markdown notes, state, and JSONL conversations | `live/memory/`, `live/state.json`, and `live/threads/` under the data directory |
| Skill Markdown and versions | `live/skills/` and `live/skills/.versions/` under the data directory |
| Generated files, page versions, and attachments | Workspace disk, with optional artifact copies in Box |
| Recall | Markdown and enabled sources on disk, with derived indexes and an optional Pinecone namespace |
| Deployment | `~/hearth/current` points to a release. `~/hearth/data` and `~/hearth/config` persist separately from releases. |

The Sprite installer registers web and scheduler services. The web service also runs a background loop for delivery, tasks, event automations, and Home refresh. The authenticated scheduler tick checks due reminders and tasks, polls Inbox, starts automation processing, and refreshes due Home panels. An external tick can wake the Sprite while browsers are closed. Home can call Open-Meteo directly. Browser voice calls join a LiveKit room after the Hearth server requests a session credential through Vocal Bridge. [Deploy and wake](deploy.md), [Voice](voice.md)

## Checkpoints and Undo

Hearth uses local snapshots of `live/` during development and `sprite-env checkpoints` for native Sprite snapshots. Snapshot-backed actions include side-chat deletion and approved sends. Note edits also keep before and after text so Timeline can undo or redo those edits in place. Reminders, recurring-task deletions, page edits, artifact changes, and skill versions have their own reversal paths. Box artifact restoration can write a new Box version when the previous bytes are available.

A native restore rolls the whole Sprite filesystem back to that checkpoint and can discard later workspace changes. A local restore replaces the `live/` subtree. Provider sends and writes live outside those snapshots. [Checkpoint code](../hearth/checkpoints.py), [Artifact reversal](../hearth/artifacts.py), [Memory edits](../hearth/memory_edits.py)

## Published Pages

Private previews use a sandbox and a restrictive content security policy. Approved sharing copies one sanitized version to an optional share-only Sprite. Anyone with the link can read the snapshot until it is revoked. The share-only process serves token-addressed HTML and accepts authenticated publish and revoke requests. Workspace APIs run on the private Sprite. [Pages code](../hearth/pages.py), [Public handler](../hearth/page_public.py), [Publisher deployment](deploy.md#publish-html-snapshots)

## Automation events

Inbox polling and reminder firing persist matching run claims in workspace state. The web runner also checks due schedules and eligible new Feed cards. Runs store ordered action progress and reuse the existing approval receipts for outbound actions. A run interrupted during an action shows an unconfirmed outcome. Timeline reads persisted run states and can undo individual local changes. [Automations](approvals-and-tasks.md#event-triggered-automations)
