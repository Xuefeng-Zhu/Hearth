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

## Migrating and undoing notes

On first startup with legacy memory, Hearth adds front matter, preserves the old Markdown, moves matching legacy topic files into the standard paths when available, and adds the new topic and approvals files. It retains the original notes in `memory-backups/before-structured-memory.json` within the data directory. The **Memory moved to the new layout** Timeline entry offers item-level Undo and Redo. Later edits, renames, and ordinary note deletions can also be undone from Timeline. If a touched note has changed again, reverse the newer edit first.

## Pinecone

Under **Settings → Memory**, choose **Auto**, **Pinecone**, **Local**, **Hugging Face embeddings**, or **Keyword**. Set the result limit, similarity threshold, and library scope. Auto uses Pinecone when connected. Pinecone matches are supplemented by keyword hits, which can surface recent edits while sync is pending. If Pinecone is unavailable or exceeds the chat time budget, Hearth uses local keyword matching. The Hugging Face backend keeps a local vector cache. Text artifacts can appear in search. Chat and voice transcript recall is opt-in.

The existing Hearth Sprite uses the `frank` namespace and a **384-dimension cosine** index with Hugging Face’s `intfloat/multilingual-e5-small` embeddings. Fresh generic installations still default to the `hearth` namespace. For installations that share an index, configure a distinct namespace in each workspace’s private connector settings. [Connector setup](connectors.md), [Pinecone adapter](../hearth/pinecone.py)

Startup, edits, Undo, and Redo trigger reconciliation. Structured notes use heading sections as recall chunks, with additional splits for long sections. Pinecone records include the note ID, type, related IDs, and update time. Sync compares record fingerprints and upserts new or changed records and prunes stale Hearth records in the configured namespace. **Rebuild index** reconciles records within that namespace. The index itself stays in place. [Sync worker](../hearth/memory_sync.py)

## Permanent forget from chat

Ask Hearth to forget a specific fact or subject. The connected brain identifies matching phrases and known variants. Hearth removes matching note passages, chat and voice transcript entries, recall activity, and copies in its local migration and Undo data. It adds a standing rule, using phrase hashes, to block matching details from being saved or recalled again. Pinecone record cleanup runs through sync. Timeline records the action without an Undo.

Matching depends on the phrases and variants identified for the request. Independent source documents, provider logs, and native Sprite snapshots are outside Hearth’s writable memory stores. Hearth excludes matches from artifact recall and blocks in-app restoration of native snapshots that predate a permanent forget request. Use **Delete** in the Memory page for ordinary note removal with Undo. [Permanent forget implementation](../hearth/memory_purge.py)
