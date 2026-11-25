# Hearth

Hearth is a private personal assistant that lives on a Fly.io Sprite. It keeps its memory in Markdown and takes a filesystem checkpoint before replacing notes or executing an approved email.

## Run locally

Use Python 3.10 or later on Linux or macOS. The server, browser app, and tests use the standard library and browser APIs.

```sh
python3 -m unittest discover -s tests -v
python3 -m hearth.server
```

Open `http://127.0.0.1:8080`. Run `python3 -m hearth.scheduler` in a second terminal to process reminders. Both processes use `.hearth/` by default. Set `HEARTH_DATA_DIR` to the same directory for both processes to run a separate workspace. The first startup copies the sample files from `memory/` to `live/memory/` within the data directory.

## Chat threads

**Main** is the pinned conversation. Click **New side chat** or send `/side <message>` or `/btw <message>` from Main to start a separate thread. The first message supplies its title. Use **Rename** or **Delete** in the thread header. On mobile, choose a thread from the dropdown.

Each thread streams independently. A dot marks a thread with work in progress. You can switch threads and send immediately, or send a follow-up in a busy thread. Follow-ups run in order after the current reply. Pending turns are held in memory until they start, so a server restart clears the queue.

All threads share Hearth's Markdown memory, reminders, and approval queue. Timeline and approval cards show the source thread. Side chats can read recent Main excerpts. Main sees each side chat's title and short summary. **Share to Main** copies a short quote from a side-chat message into Main. It leaves the original in place and starts no model turn.

Deleting a side chat requires confirmation and saves a checkpoint first. Timeline offers **Undo** on the deletion entry. The restore rolls back the entire workspace to the checkpoint. Shared actions and approvals stay in Timeline after a thread is deleted.

## Demo

1. Click **Plan Thanksgiving dinner**. Hearth streams a plan based on the sample notes, drafts an invitation, and sets an in-app reminder for two minutes later.
2. Click **Approve** to record the simulated send. The invitation card shows its checkpoint.
3. Send `Wipe topics/thanksgiving.md`. Open **Memory** and select the Thanksgiving note to see that it is empty.
4. In **Timeline**, find the **Memory updated** action and click **Undo**. Confirm the checkpoint restore. When Hearth reconnects, reopen the note to see its original content.

Use `Remind me to check the oven in 15 seconds` for a quick reminder demo. Use `Schedule check the oven | 0 17 * * 4` for a weekly Thursday reminder at 17:00 UTC. Timeline shows upcoming and delivered reminders.

## Connect providers

Open **Connections** to browse or filter the full 61-entry Fly catalog. Meta Muse Spark, Pinecone, Tavily, and AgentMail appear first. The catalog includes Fly.io Machines as a Custom API preset. Hearth also lists providers returned by discovery that are newer than the checked-in catalog. [Fly ecosystem](https://fly.io/sprites/ecosystem/), [Sprites connector docs](https://docs.fly.io/sprites/concepts/connectors)

For any provider, choose **Open in Fly**, add the connector, turn off **Allow all sprites**, and set **Name Prefix** to `hearth`. Check **Authorized Sprites** before saving. Enter any provider credentials in Fly’s connector form. [Fly dashboard connectors](https://fly.io/dashboard/xuefeng-zhu/sprites/connectors)

In Hearth, click **Re-scan**. Discovery also runs at server startup and when you open Hearth or its Connections tab. **Connected** means the gateway lists an authorized connection. **Found but not authorized** means the gateway denied or stopped listing a previously seen connection. **Not set up** means no connection is visible. A connector that has never granted access to this Sprite may be invisible to discovery. With multiple authorized connections for a provider, Hearth keeps the previously selected connection while it remains available.

**Test** appears where Hearth has a read-only GET path. It makes one request after the provider is connected and reports the outcome separately from discovery. Save the **Index name** for Pinecone or **Inbox ID** for AgentMail on the same page. See [STATUS.md](STATUS.md) for settings for the four pinned connectors.

### Choose the brain

Open **Settings → Brain**. **Auto** is the default and tries Muse Spark first, followed by other connected chat providers and then Mock. Pick a provider to give it priority, or choose **Mock** to run the offline demo. The menu marks connected integrations that lack a chat adapter.

Choose a model from the live list, or select **Enter a model ID…** to enter a provider-specific ID. Hugging Face lists text chat models and defaults to `Qwen/Qwen3-Coder-Next:fastest`. **Test** sends a short prompt and shows the reply and elapsed time. **Save** takes a checkpoint, writes the selection to `~/hearth/config/connectors.local.json` on the Sprite, and applies it immediately. [Hugging Face model discovery](https://huggingface.co/docs/inference-providers/en/hub-api#list-openai-compatible-models)

When a brain fails, chat names the provider and the next attempt, and Timeline records the fallback. After a workspace action has started, the next brain continues with a text-only reply and the existing action cards. Hugging Face uses native streaming tool calls and can switch to JSON instructions when the model rejects the tool request.

### Configure memory recall

Open **Settings → Memory**. **Auto** tries Pinecone, Hugging Face, and Keyword in that order. **Keyword** works offline. Hugging Face defaults to `BAAI/bge-small-en-v1.5`, with BGE Base for English and Multilingual E5 for Chinese and other languages. Pinecone uses its inference model first and can use the selected Hugging Face model if its vector dimension matches the index.

Set **Top-k** (1–20), minimum cosine similarity (0–1), and the Markdown folders to include or exclude. Exclusions take precedence. Chat history is opt-in and covers Main and every side chat. Vector backends send queries and in-scope excerpts to their embedding provider through Sprites. **Test recall** shows the backend used, scores, source lines, and latency. The hybrid score weights cosine similarity at 80% and keyword overlap at 20%. Keyword mode ranks by overlap alone.

**Reindex now** takes a checkpoint and rebuilds the saved scope with progress and counts. Hearth chunks notes by heading and paragraph and stores vectors under `~/hearth/data/live/index/` on the Sprite. During recall it reuses vectors for unchanged excerpts and embeds new or edited text. The **Memory** tab uses the same recall settings. A **Remembered** chip under a reply lists the sources it cited and opens the matching note lines or chat excerpt.

**Auto-remember** defaults to **Off**. **Ask first** shows an approval card, and **Automatic** saves durable facts to the current UTC daily note. Both checkpoint before a write. Direct requests to edit a note are available in every mode. **Forget** checkpoints and deletes a Markdown excerpt or entire note, or excludes a chat message from future recall while preserving its transcript. Use Timeline’s **Undo** to restore a checkpoint. Pinecone clears stale vectors when that index next syncs.

### Configure web search

Open **Settings → Search** and choose **Auto**, **Off**, or a connected provider. Auto tries Tavily, Exa, Linkup, Kagi, Keenable, and Firecrawl in order. It moves to the next connected provider on error and records the failure in Timeline. Disconnected providers link to **Connections**. Hearth offers the brain its web search tool when the selection has an active provider.

Choose **Max results** (1–10), recency, Safe search, and comma-separated include or exclude domains. Safe search uses provider filtering where available. With Exa and Linkup it uses a basic local filter. **Test search** shows results and latency for the current choices. **Save** checkpoints and applies the selection immediately.

### Use a connected provider in chat

Ask Hearth to use a connected provider. On the Mock brain, use `Gateway github GET /user`. To supply JSON, use `Gateway github POST /repos/OWNER/REPO/issues | {"title":"Example"}` with a repository where you intend to open an issue.

The generic gateway tool sends a provider-relative request through Sprites. GET executes immediately. Other methods show the method, path, and JSON body for review. **Approve** saves a checkpoint first, then sends one request. The card can show the response in the current browser session. A checkpoint restores Hearth’s workspace. Provider changes persist independently. Small JSON and text responses can be previewed in Hearth.

## How it works

- `hearth.server` serves the browser app and JSON API. Chat uses server-sent events for reply text and action cards. The agent uses tools for memory, search, email proposals, reminders, and checkpoints. Any provider authorized by discovery is available to the generic gateway tool.
- Memory lives in `USER.md`, `people/*.md`, `topics/*.md`, and `daily/YYYY-MM-DD.md`. Each transcript is a JSONL file under `live/threads/` in the data directory. The thread index sits beside them. The first write to Main migrates any existing chat history from `live/state.json`. Actions and reminders share the lock-protected state file. The web and scheduler run as separate Sprite services.
- The offline mock uses the same tool interface as the model adapters. The header shows the active brain while Settings shows the saved preference.
- Provider calls go through the Sprites gateway without an Authorization header. Hearth stores connector IDs and supported settings. Fly holds the credentials. The chosen search and recall providers run through that gateway. Pinecone stores vectors in a workspace-specific namespace. AgentMail sends only after approval. Without AgentMail, approval records a simulated send locally. [Provider setup details](STATUS.md)
- Undo restores the entire Sprite filesystem, including later chat, memory, reminders, and deployed files. The local backend restores the application data directory. Delivered email and remote Pinecone data stay with their providers.

## Deploy privately

```sh
scripts/deploy.sh
sprite exec --http-post --no-stdin --no-port-forward -o xuefeng-zhu -s hearth -- curl -fsS http://localhost:8080/health
sprite exec --http-post --no-stdin --no-port-forward -o xuefeng-zhu -s hearth -- curl -fsS http://localhost:8080/api/connections
```

The deploy script installs a versioned release on `hearth` in `xuefeng-zhu`, registers or restarts the `web` and `scheduler` services, and checks port 8080. Hearth saves discovered IDs and provider settings to `~/hearth/config/connectors.local.json` and keeps workspace data under `~/hearth/data`. Open the Sprite from the Fly dashboard and sign in as an organization member.

The scheduler records due reminders while the Sprite is awake and catches up on wake. If a recurring reminder missed multiple occurrences, it records one catch-up and resumes at the next future occurrence. A closed browser and hibernating Sprite need an authenticated external wake trigger for punctual delivery. Run this from an authenticated scheduler host if you want periodic wakes. [Fly Sprites lifecycle](https://fly.io/sprites/)

```sh
sprite exec --http-post --no-stdin --no-port-forward -o xuefeng-zhu -s hearth -- sh -c '
  cd "$HOME/hearth/current" &&
  HEARTH_DATA_DIR="$HOME/hearth/data" python3 -c "
from hearth.scheduler import run_due
from hearth.storage import Storage
run_due(Storage())
"
'
```
