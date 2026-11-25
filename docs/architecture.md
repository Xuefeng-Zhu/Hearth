# Architecture

The browser loads HTML, CSS, and JavaScript from [the Python server](../hearth/server.py). The server streams chat replies, tool results, and Timeline updates using server-sent events. Main and side chats keep separate transcripts and queues. They share memory, reminders, and approvals. Queued turns live in process memory until execution starts. [Threads](../hearth/threads.py), [Timeline](../hearth/timeline.py)

## A chat turn

1. The server puts the prompt in its thread queue. The agent gathers available attachment context and memory excerpts.
2. The brain uses Mock, a fixed model, or a Smart routing pool. The router uses the kind of request and recent model performance to order the pool. Before acting, the agent can load a matching playbook from the prompt's compact skills index. A side chat created through **Try it** loads its selected skill automatically. The agent can try another model on failure and avoids replay after a tool has changed state.
3. Local tools read and write workspace files. Outbound provider requests go through Fly's gateway, which supplies credentials for the selected connection. Sensitive tool actions follow the approval rules before execution.
4. The browser receives reply deltas and tool cards. The final message is stored in the thread and activity is recorded in Timeline.

[Agent loop](../hearth/agent.py), [Routing](../hearth/router.py), [Gateway client](../hearth/connectors.py), [Approvals](approvals-and-tasks.md)

## Workspace and background work

| State | Where it lives |
| --- | --- |
| Markdown notes, state, and JSONL conversations | `live/memory/`, `live/state.json`, and `live/threads/` under the data directory |
| Skill Markdown and versions | `live/skills/` and `live/skills/.versions/` under the data directory |
| Generated files, page versions, and attachments | Workspace disk, with optional artifact copies in Box |
| Recall | Markdown and enabled sources on disk, with derived indexes and an optional Pinecone namespace |
| Deployment | `~/hearth/current` points to a release. `~/hearth/data` and `~/hearth/config` persist separately from releases. |

The Sprite installer registers web and scheduler services. The web service also runs a background loop for delivery, tasks, and Home refresh. The authenticated scheduler tick checks due reminders and tasks, polls Inbox, and refreshes due Home panels. An external tick can wake the Sprite while browsers are closed. Home can call Open-Meteo directly. Browser voice calls join a LiveKit room after the Hearth server requests a session credential through Vocal Bridge. [Deploy and wake](deploy.md), [Voice](voice.md)

## Checkpoints and Undo

Hearth uses local snapshots of `live/` during development and `sprite-env checkpoints` for native Sprite snapshots. Snapshot-backed actions include side-chat deletion and approved sends. Note edits also keep before and after text so Timeline can undo or redo those edits in place. Reminders, recurring-task deletions, page edits, artifact changes, and skill versions have their own reversal paths. Box artifact restoration can write a new Box version when the previous bytes are available.

A native restore rolls the whole Sprite filesystem back to that checkpoint and can discard later workspace changes. A local restore replaces the `live/` subtree. Provider sends and writes live outside those snapshots. [Checkpoint code](../hearth/checkpoints.py), [Artifact reversal](../hearth/artifacts.py), [Memory edits](../hearth/memory_edits.py)

## Published Pages

Private previews use a sandbox and a restrictive content security policy. Approved sharing copies one sanitized version to an optional share-only Sprite. Anyone with the link can read the snapshot until it is revoked. The share-only process serves token-addressed HTML and accepts authenticated publish and revoke requests. Workspace APIs run on the private Sprite. [Pages code](../hearth/pages.py), [Public handler](../hearth/page_public.py), [Publisher deployment](deploy.md#publish-html-snapshots)
