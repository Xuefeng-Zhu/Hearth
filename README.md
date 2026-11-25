# Hearth

Hearth is a private personal assistant that lives on a Fly.io Sprite. It keeps its memory in Markdown and takes a filesystem checkpoint before replacing notes or executing an approved email.

## Run locally

Use Python 3.10 or later on Linux or macOS. The server, browser app, and tests use the standard library and browser APIs.

```sh
python3 -m unittest discover -s tests -v
python3 -m hearth.server
```

Open `http://127.0.0.1:8080`. Run `python3 -m hearth.scheduler` in a second terminal to process reminders. Both processes use `.hearth/` by default. Set `HEARTH_DATA_DIR` to the same directory for both processes to run a separate workspace. The first startup copies the sample files from `memory/` to `live/memory/` within the data directory.

## Demo

1. Click **Plan Thanksgiving dinner**. Hearth streams a plan based on the sample notes, drafts an invitation, and sets an in-app reminder for two minutes later.
2. Click **Approve** to record the simulated send. The invitation card shows its checkpoint.
3. Send `Wipe topics/thanksgiving.md`. Open **Memory** and select the Thanksgiving note to see that it is empty.
4. In **Timeline**, find the **Memory updated** action and click **Undo**. Confirm the checkpoint restore. When Hearth reconnects, reopen the note to see its original content.

Use `Remind me to check the oven in 15 seconds` for a quick reminder demo. Use `Schedule check the oven | 0 17 * * 4` for a weekly Thursday reminder at 17:00 UTC. Timeline shows upcoming and delivered reminders.

## Connect providers

Open **Connections** in Hearth and use the guide on each provider’s card. Create the connector in Fly, then turn off **Allow all sprites**, set **Name Prefix** to `hearth`, and check **Authorized Sprites** before saving. Enter provider keys only in Fly’s connector form. [Fly dashboard connectors](https://fly.io/dashboard/xuefeng-zhu/sprites/connectors)

Back in Hearth, click **Re-scan**. Hearth also scans during server startup, when the browser loads, and when you open Connections. It discovers the connection IDs, checkpoints before any settings change, and applies the new configuration immediately. Save the **Index name** for Pinecone or **Inbox ID** for AgentMail on the same page. **Test** runs one read-only check through the gateway for that provider. The checks for Muse Spark and Tavily use a short completion and a basic search, respectively, and can count toward provider usage.

**Connected** means the gateway listed the connector and its read-only check succeeded. **Found but not authorized** means access was denied or a previously discovered ID is no longer listed. Fly’s Sprite-scoped discovery can hide connectors that have never granted access, so **Not set up** can also mean Hearth cannot see a connector yet. **Unreachable** means Hearth found a connector but the check failed. The header shows the active brain. A successful Muse Spark check enables it for the next chat.

## How it works

- `hearth.server` serves the browser app and JSON API. Chat uses server-sent events for reply text and action cards. The agent calls a fixed set of tools for memory, search, email proposals, reminders, and checkpoint requests.
- Memory lives in `USER.md`, `people/*.md`, `topics/*.md`, and `daily/YYYY-MM-DD.md`. Chat, actions, and reminders share a lock-protected JSON state file. The web and scheduler run as separate Sprite services.
- The offline mock uses the same tool interface as the model adapters. Hearth tries Muse Spark first with the default order, followed by any configured Ollama Cloud or OpenRouter fallbacks, then the mock. An interrupted model turn stops after any executed tool to avoid replaying actions.
- Provider calls go through the Sprites gateway without an Authorization header. Tavily supplies web search. Pinecone embeds and indexes note excerpts using a namespace tied to the current memory revision. Local keyword recall works offline and when Pinecone is unavailable. AgentMail sends only after approval. Without AgentMail, approval records a simulated send locally. [Provider setup details](STATUS.md)
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
