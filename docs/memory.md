# Memory and recall

The **Memory** page shows what Hearth knows across **Profile**, **People**, **Places**, **Topics**, and **Daily**. Edit the profile in its form or open a note to edit its Markdown, follow related notes, rename it, or delete it. Renames update links in other notes. The search box uses the workspace’s recall settings and opens the source at the matching lines. **Settings → Approvals** updates the approval rules shown in `APPROVAL_PREFERENCES.md`.

## Files and agent tools

Hearth stores Markdown under `live/memory/` in the data directory. A fresh workspace copies the [fictional demo notes](../memory/).

| Area | Path | Front matter |
| --- | --- | --- |
| Profile | `USER.md` | `profile`, `id: user`, `type: user`, `related` |
| People and organizations | `people/<name>.md` | `id`, `type: contact` or `organization`, `relation`, `related` |
| Places | `locations/<place>.md` | `id`, `type: place`, `related` |
| Topics | `food.md`, `travel.md`, `shopping-and-money.md`, `home-and-health.md`, `leisure.md`, and `topics/<subject>.md` | `id`, `type`, `related` |
| Projects | `projects/<project>.md` | `id`, `type: project`, `related` |
| Daily | `daily/YYYY-MM-DD.md` | `id`, `type: event`, `related` |
| Approvals | `APPROVAL_PREFERENCES.md` | `id: approval-preferences`, `type: misc`, `related` |

The profile begins with a YAML `profile:` mapping. It contains `name`, `preferred_name`, `pronouns`, `phone`, `addresses` (entries with `id`, `label`, `address`, and `notes`), `work` (with `employer` and `role`), and lists for `pets`, `interests`, and `communication`. Short Markdown notes follow. Apart from the fixed profile and approvals IDs, each note ID is its path without `.md`. Put note IDs in `related`. The full type set is `user`, `contact`, `organization`, `project`, `place`, `event`, `interest`, and `misc`.

Hearth regenerates `live/memory/.index.json` after memory changes and refreshes it when it reads the library. The system prompt receives the in-scope note IDs, types, relationships, sizes, and update times, plus the full `USER.md`. Recall supplies a short list of relevant excerpts separately. The agent can use `memory_search`, `memory_read` by ID or path with inclusive line numbers, `memory_write`, `memory_edit` for a passage or append, and `memory_move`.

New workspaces default to **Automatic** in **Settings → Memory → Auto-remember**. Existing settings carry forward. **Ask first** queues unsolicited memory writes for approval. **Off** requires a direct request to edit a note. Connected brains are instructed to save durable details during the turn, keep one note per subject, mark inferences, and use the latest user statement when facts conflict. Hearth screens writes for recognized secrets, identity-document IDs, and payment card numbers. [Agent tools](../hearth/agent.py)

## Nightly Memory review

Hearth checks memory at **03:00 America/Los_Angeles** by default. Turn off nightly checks, set a different Pacific time, or select **Run now** in **Settings → Memory → Memory review**. Run now is available with the schedule off. A sleeping Sprite catches up on wake. [Scheduler wake](deploy.md#wake-the-scheduler)

One pass reads the profile, people files, and saved Markdown notes. With Pinecone connected, it checks a batch of Hearth-managed records against the current sources in the configured namespace. Large libraries rotate through batches. The fast brain receives the excerpts as reference data and returns source IDs in a strict schema, validated locally. Mock mode uses local matching and date checks. Each pass can propose up to 20 items. A failed pass leaves the notes alone and records a diagnostic in Timeline.

Open **Memory → Review** to see proposed edits and their sources. **Home → Feed** shows a card for a digest with pending items after Action suggestions quiet hours end. A pass with no new proposals updates its status in Settings.

- **Merge duplicate** keeps one copy of a repeated line and removes the copy shown in the proposal.
- **Contradiction** shows both versions and their sources. Accept acknowledges the disagreement. Edit the source in Memory to resolve it.
- **Add to profile** appends a fact found in at least three matching note occurrences to the profile notes. Pinecone mirrors share their original source.
- **Mark stale** labels the line in place so the original text stays available.

Use **Accept** or **Reject** on each proposal, or **Accept all** for the pending edits in the selected digest. Review contradictions individually. Hearth rechecks the cited lines at approval time. If an edit made a proposal outdated, reject it and run another pass. Accepted edits create a Timeline checkpoint with item-level Undo and Redo and trigger Pinecone sync through the normal memory write path. Permanent forget clears derived digests and continues to block matching information. [Run 43 verification](run-43.md)

## Long chats

Hearth sends the latest 16 dialogue messages to the brain. With **Settings → Memory → Summarize long chats** enabled by default, Hearth folds older messages into a per-thread summary in the background after a reply is saved. Each update starts when at least eight messages have moved outside the window since the last fold. The summary uses the chat’s language and keeps decisions, facts, preferences, filenames, and open tasks in about 400 words. The summary goes into the brain’s context before the recent messages. Main can also use a short excerpt from each side chat’s summary.

Hearth uses DeepSeek V4.1 Flash through the Hugging Face connector when available, with the default connected brain as a fallback. Folding sends older dialogue and the previous summary to the model. Hearth screens the input and output for recognized credentials and tool markup. Mock mode skips folding.

A shared two-worker executor runs summaries off the reply path. Rolling updates coalesce by workspace and thread, with at most one follow-up for a running thread. A `summary.pending` marker lets startup requeue unfinished rolling work when summaries are enabled and a connected model is available. A failed model fold keeps the previous summary and cursor, records a sanitized Timeline diagnostic, and can retry on startup or after another reply. A corrupt summary can be rebuilt from the transcript. Before saving, Hearth rechecks the active agent, thread membership, forget rules, and previous summary so in-flight work cannot overwrite a reset. The shorter side-chat recap shares the executor and starts after the reply is persisted and `done` is emitted. [Summary implementation](../hearth/thread_summary.py), [Summary verification](run-56.md), [Reply ordering](run-58.md)

Choose **Summary** from the thread row’s **⋯** menu. The button appears on desktop hover or keyboard focus and stays visible in the mobile drawer. **Reset summary** clears the saved summary and starts the next fold from the current 16-message window. Reset saves a checkpoint and appears in Timeline. Turning the setting off pauses updates and stops Hearth from supplying saved summaries to the brain. Deleting a side chat removes its live summary. Checkpoints include summaries and their cursors alongside the transcript. [Thread menu](../web/chat/threads.js), [Thread storage](../hearth/threads.py)

## Migrating and undoing notes

On first startup with legacy memory, Hearth adds front matter, preserves the old Markdown, moves matching legacy topic files into the standard paths when available, and adds the new topic and approvals files. It retains the original notes in `memory-backups/before-structured-memory.json` within the data directory. The **Memory moved to the new layout** Timeline entry offers item-level Undo and Redo. Later edits, renames, and ordinary note deletions can also be undone from Timeline. If a touched note has changed again, reverse the newer edit first.

## Pinecone

Set up or test Pinecone in **Settings → Connections**. The Pinecone index card under **Settings → Memory** links to Connections when the provider is disconnected or reports an error.

Under **Settings → Memory**, choose **Auto**, **Pinecone**, **Local**, **Hugging Face embeddings**, or **Keyword**. Set the result limit, similarity threshold, and library scope. Auto uses Pinecone when connected. Pinecone matches are supplemented by keyword hits, which can surface recent edits while sync is pending. If Pinecone is unavailable or exceeds the chat time budget, Hearth uses local keyword matching. Local and Keyword can find Chinese phrases inside longer saved sentences as well as English words. The Hugging Face backend keeps a local vector cache. Text artifacts can appear in search. Chat and voice transcript recall is opt-in.

The demo Sprite uses a dedicated namespace and a **384-dimension cosine** index with Hugging Face’s `intfloat/multilingual-e5-small` embeddings. Fresh installations default to the `hearth` namespace. For installations that share an index, configure a distinct namespace in each workspace’s private connector settings. [Connector setup](connectors.md), [Pinecone adapter](../hearth/pinecone.py)

Startup, edits, Undo, and Redo trigger reconciliation. Structured notes use heading sections as recall chunks, with additional splits for long sections. Hearth builds chunks outside the workspace lock and caches them by source revision. Attachment extraction is cached by file content. Restore and permanent forget invalidate these in-process caches. Pinecone records include the note ID, type, related IDs, and update time. Sync compares record fingerprints and upserts new or changed records and prunes stale Hearth records in the configured namespace. **Rebuild index** reconciles records within that namespace. The index itself stays in place. [Recall](../hearth/recall.py), [Attachment extraction](../hearth/uploads.py), [Sync worker](../hearth/memory_sync.py)

## Permanent forget from chat

Ask Hearth to forget a specific fact or subject. The connected brain identifies matching phrases and known variants. Hearth removes matching note passages, chat and voice transcript entries, thread summaries, recall activity, and copies in its local migration and Undo data. It adds a standing rule, using phrase hashes, to block matching details from being saved or recalled again. Pinecone record cleanup runs through sync. Timeline records the action without an Undo.

Matching depends on the phrases and variants identified for the request. Independent source documents, provider logs, and native Sprite snapshots are outside Hearth’s writable memory stores. Hearth excludes matches from artifact recall and blocks in-app restoration of native snapshots that predate a permanent forget request. Use **Delete** in the Memory page for ordinary note removal with Undo. [Permanent forget implementation](../hearth/memory_purge.py)
