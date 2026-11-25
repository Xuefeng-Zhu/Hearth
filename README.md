# Hearth

Hearth is a private personal assistant that lives on a Fly.io Sprite. It keeps its memory in Markdown and takes a filesystem checkpoint before replacing notes or executing an approved email.

## Run locally

Use Python 3.10 or later on Linux or macOS. The server uses the standard library, and the browser app serves its SDK locally. Use Node.js 22 or later for the browser module tests.

```sh
python3 -m unittest discover -s tests -v
node --test tests/*.test.mjs
python3 -m hearth.server
```

Open `http://127.0.0.1:8080`. The web server starts the reminder worker. It uses `.hearth/` by default. Set `HEARTH_DATA_DIR` to run a separate workspace. The first startup copies the sample files from `memory/` to `live/memory/` within the data directory.

## Chat threads

**Main** is the pinned conversation. Click **New side chat** or send `/side <message>` or `/btw <message>` from Main to start a separate thread. The first message supplies its title. Use **Rename** or **Delete** in the thread header. On mobile, choose a thread from the dropdown.

Each thread streams independently. A miniature avatar shows its current activity. When the avatar is off, a dot marks threads with work in progress. You can switch threads and send immediately, or send a follow-up in a busy thread. Follow-ups run in order after the current reply. Pending turns are held in memory until they start, so a server restart clears the queue.

All threads share Hearth's Markdown memory, reminders, and approval queue. Timeline and approval cards show the source thread. Side chats can read recent Main excerpts. Main sees each side chat's title and short summary. **Share to Main** copies a short quote from a side-chat message into Main. It leaves the original in place and starts no model turn.

Deleting a side chat requires confirmation and saves a checkpoint first. Timeline offers **Undo** on the deletion entry. The restore rolls back the entire workspace to the checkpoint. Shared actions and approvals stay in Timeline after a thread is deleted.

### Ember avatar

Use the menu next to the thread title to choose **Off**, **Beside chat**, or **Full screen**. Full screen shows a large avatar with live reply captions and expandable action cards. Press **Esc** to return to chat. The avatar listens while you type or dictate, shows the current tool action, moves its mouth as the reply streams, and reacts to memory citations, completed turns, warnings, and reminders. It rests after two minutes of inactivity.

In **Settings → Appearance**, choose Ember, Kettle, Moss sprite, Cloud, or Paper lantern, and use the preset color or pick your own. All five share the same poses. Motion follows your system’s reduced-motion preference, and the avatar announces state changes through a polite status region. The view, preset, and color are saved in this browser.

### Voice input

Use the mic button in Main or any side chat. Click it again to finish, or hold **Space** in an empty composer and release to finish. **Esc** cancels the recording or pending transcription. The composer shows the live microphone level and, with Browser selected, interim words where the browser supplies them.

In **Settings → Voice**, **Auto** selects Hugging Face Whisper when the connector is authorized and Browser otherwise. Whisper can detect the spoken language automatically. Browser uses its default speech language in Auto, or you can select a language such as English or 中文. The default limit is 60 seconds. The transcript goes into the composer for editing by default. Enable **Send automatically after transcription** to submit the result while preserving any existing draft. Voice settings are saved in this browser.

Microphone access requires HTTPS or localhost and browser permission. Browser uses the browser’s speech service. Whisper sends audio through the Sprites gateway to Hugging Face. Hearth processes the upload in memory and runs both engines’ final transcripts through the same credential redactor used for typed prompts.

### Voice calls

Press **Call** in the header of Main or a side chat. A live call uses your microphone and plays the voice agent’s audio. The sheet shows a timer, live captions when Vocal Bridge publishes them, mute and end controls, and **Asked Hearth…** while Hearth handles a query. You can minimize the sheet and return to the same call. When the connector is missing, **Call** opens a labeled demo with scripted captions and controls.

Each query from the voice agent runs in the chat where the call started, with Hearth’s routing, recall, tools, approvals, and checkpoint Undo. Timeline shows **Voice call** on the associated routing and action entries. When you end the call, Hearth adds a duration card and saves the redacted captions by default. **Settings → Voice → Voice calls** has Auto, English, and 中文, a 10-minute default limit, and a transcript toggle. With auto-save off, Hearth still keeps the duration card and any normal Hearth turns. The live agent also receives the language preference as a context hint. Its deployed voice configuration determines how it applies the hint.

1. Create and deploy an agent at [Vocal Bridge](https://vocalbridgeai.com). Set **AI Agent Integration** to the **client data channel** so voice requests can reach Hearth.
2. Create an agent-scoped API key. In the Fly dashboard, add **Vocal Bridge**, turn off **Allow all sprites**, and set **Name Prefix** to `hearth`. Enter the key in Fly’s connector form. [Fly dashboard connectors](https://fly.io/dashboard/xuefeng-zhu/sprites/connectors)
3. Refresh **Connections** and check **Settings → Voice**. The Vocal Bridge card’s **Test** confirms this Sprite’s gateway access. Starting a call checks the deployed agent by minting its short-lived room credential.

Hearth mints room credentials through the Fly gateway. The browser uses them for LiveKit WebRTC, and Hearth serves the pinned SDK locally from `web/vendor/vocalbridge.mjs`. The bundle contains `@vocalbridgeai/sdk@0.1.1` and `livekit-client@2.25.0`, bundled for browser ESM with esbuild 0.28.1. It loads on demand and requires no app build step or CDN. [Vocal Bridge developer docs](https://vocalbridgeai.com/docs/overview), [SDK integration guide](https://github.com/vocalbridgeai/sdk/blob/main/INTEGRATION.md)

## Artifacts

Ask Hearth to “save this as a doc,” “make me a shopping list file,” or “export my memory.” You can also choose **Save as artifact** under a reply or call transcript. Each saved file has a chat chip and a card in **Artifacts**. Markdown is the default. Hearth also supports plain text, CSV, and JSON.

Switch between grid and list on desktop, filter by kind, or sort by name or most recent update. Open any card to see which chat it came from, view the preview, edit, copy, or download the text, and open the original file in Box. Saving an edit to a synced file creates a new Box version. Hearth shows its saved version receipts when the connector cannot list Box versions. **Move to Trash** hides the artifact in Hearth and keeps the file in Box. Timeline offers item-level **Undo** for creation, edits, and Trash. Undoing a synced edit saves the previous content as a new version. [Box version history](https://developer.box.com/reference/get-files-id-versions)

Add or refresh Box in **Connections**. **Settings → Artifacts** controls auto-save, the default file format, and the folder name. The first upload finds or creates **Hearth** in your Box root, along with **Plans**, **Lists**, **Notes**, **Transcripts**, and **Exports**. Hearth saves the folder IDs in `connectors.local.json` and lists files you add anywhere under the selected folder. Text previews and saves are limited to 128 KiB. Hearth redacts recognized credentials before saving and uses the Sprites gateway for Box access. [Box folder items API](https://developer.box.com/reference/get-folders-id-items), [Fly Sprites connectors](https://docs.fly.io/sprites/concepts/connectors)

Hearth sends multipart uploads through the Sprites connector at `upload/files/content` and `upload/files/{id}/content`. If the gateway rejects an upload as unsupported, Hearth shows **Saved locally — Box upload unavailable**. You can open, edit, download, or retry the local copy. [Live verification](STATUS.md)

For the demo, open the seeded **Thanksgiving artifacts** side chat on the Sprite. With Mock selected, “Make Thanksgiving demo artifacts” creates a Thanksgiving plan, a shopping list CSV, and a seating chart in the current chat.

## Reminders and email

Open **Reminders** to schedule a reminder with a title, date, note, and **In app**, **Email**, or **Both**. In chat, try “Remind me by email to check the oven in 15 minutes.” With no channel in the request, Hearth uses **Settings → Reminders → Default channel**, initially **In app**. Email needs a recipient saved in those settings. Quiet hours default to 22:00–07:00 in America/Los_Angeles. Email waits until quiet hours end unless the reminder is urgent. The in-app channel fires independently.

Hearth shows upcoming, delivered, and snoozed reminders with status and failure details. **Undo** cancels unsent reminders. Temporary AgentMail failures retry with backoff and the same delivery key. Each email has a text and HTML body, a link to the chat on the private Sprite, and **Done**, **Snooze 10 min**, and **Snooze 1 h** links. Open a link and confirm the change on Hearth. The links are signed, expire after seven days, and share one action per delivery. If you are on the sender allowlist, replying directly to a reminder with `done` or `snooze 30` also works when the sender is authenticated.

For email, add **AgentMail** in Fly connectors with **Name Prefix** `hearth` and refresh Connections. Hearth reuses the configured **Inbox ID** or provisions a dedicated inbox on first use. Fly holds the provider credentials. In disconnected mode, Hearth records an email preview in **Reminders → Outbox**. In **Settings → Reminders**, use **Send test in app** or **Send test email** to verify the saved settings. [Fly AgentMail connector](https://fly.io/sprites/ecosystem/), [AgentMail send API](https://docs.agentmail.to/api-reference/inboxes/messages/send)

### Forward anything to Hearth

Copy your inbox address from **Connections → Email Hearth**, **Inbox**, or **Settings → Reminders**. Forward a booking, receipt, school email, fact, or list to this address. Hearth polls on wake and on scheduler ticks. The visible app asks for updates about once a minute, and **Check mail** refreshes the Inbox. Hearth records each mail once, even when it appears in overlapping polls.

Inbox shows the sender, forwarded sender and date when available, a summary, and a proposal. **Accept** applies it, **Edit** lets you change its fields before accepting, and **Dismiss** archives the proposal in the processed section. Bookings become Timeline events with in-app reminders, receipts and facts become Memory notes, lists become local Artifacts, and other mail becomes a note. Calendar attachments yield events. Attachment metadata stays on the card, along with redacted text from CSV, TXT, ICS, and PDF when AgentMail provides an accessible text extraction. **Undo** is available on accepted items in Inbox and Timeline.

Anyone can forward mail for review. Add the exact addresses you forward from under **Allowed senders**. Automatic acceptance also requires successful sender authentication and an enabled proposal type. Automatic actions are local; forwarded content cannot direct a tool or an outgoing email. Optional acknowledgments go to the authenticated forwarder after acceptance. Both automatic acceptance and acknowledgment start off. [AgentMail polling](https://docs.agentmail.to/api-reference/inboxes/messages/list), [AgentMail attachments](https://docs.agentmail.to/attachments)

## Timeline

Open **Timeline** for a live history of chat turns, memory, approvals, reminders, connectors, model routing, voice, and checkpoints. Entries are grouped by day in your browser’s time zone. Today’s totals sit above the filters. Filter by activity type or thread, or search for a prompt, note, model, or provider. The activity type is saved in this browser. Expand a card for its redacted details, then open **Raw** for the saved fields. The time on each card has the exact timestamp in its tooltip.

New memory edits and Forget actions have item-level **Undo** and **Redo**. Hearth queues a Pinecone sync after either action. Other checkpoint-backed actions offer **Restore checkpoint**, which can roll back newer chats, notes, reminders, and deployed files on the Sprite. Delivered email persists. Hearth reconciles Pinecone with the restored memory on startup. Timeline shows **Undone** and records **Last undo** after the change.

The activity feed uses the same server-sent event transport as Chat. It updates for completed background work, including delivered reminders. Connector reads record request metadata, while provider responses still follow their original preview and chat behavior. Dictation activity records the transcription engine without saving an unsent transcript.

The Harvest Hearth icon appears in Chat and the sidebar. The browser tab uses the flame-only icon, and the web manifest and touch icon supply larger versions for browsers that install Hearth.

## Demo

1. Click **Plan Thanksgiving dinner**. Hearth streams a plan based on the sample notes, drafts an invitation, and sets an in-app reminder for two minutes later.
2. Click **Approve** to record the simulated send. The invitation card shows its checkpoint.
3. Send `Wipe topics/thanksgiving.md`. Open **Memory** and select the Thanksgiving note to see that it is empty.
4. In **Timeline**, find the **Memory updated** action and click **Undo**, then **Restore checkpoint**. When Hearth reconnects, the card is marked **Undone** and the note contains its original Markdown.

Use `Remind me to check the oven in 15 seconds` for a quick reminder demo. Use `Schedule check the oven | 0 17 * * 4` for a weekly Thursday reminder at 17:00 UTC. Reminders and Timeline show upcoming occurrences and delivery by channel.

Choose **Mock** under **Settings → Brain** before running the Thanksgiving demo to see the full avatar sequence. The listening and warning previews are labeled as part of the demo. The notes, draft, reminder, streamed reply, and memory citations use the normal Hearth workflow.

## Connect providers

Open **Connections** to browse the 61-entry Fly catalog and any additional providers returned by discovery. **Configured** lists connections authorized for this Sprite. **Not configured** shows the rest of the catalog with setup steps. The badges show each tab’s total. Search and filter by category within a tab, or follow the other-tab match link to carry your filters across. Hearth opens **Configured** by default when it finds a connection and remembers your selection. Use the left and right arrow keys to switch tabs. [Fly ecosystem](https://fly.io/sprites/ecosystem/), [Sprites connector docs](https://docs.fly.io/sprites/concepts/connectors)

Choose **Add in Fly**, add the connector, turn off **Allow all sprites**, and set **Name Prefix** to `hearth`. Check **Authorized Sprites** before saving. Enter any provider credentials in Fly’s connector form. [Fly dashboard connectors](https://fly.io/dashboard/xuefeng-zhu/sprites/connectors)

In Hearth, click **Refresh**. A newly authorized connector moves to **Configured** and is briefly highlighted there. Discovery also runs at server startup and when you open Hearth or Connections. **Found but not authorized** means the gateway denied or stopped listing a previously seen connection. **Not set up** means no connection is visible. With multiple authorized connections for a provider, Hearth keeps the previously selected connection while it remains available.

Each configured card shows the access rule, the Hearth features that can use the connector, and the last check result. **Test** runs a read-only provider check when available and checks Sprites gateway authorization for other connectors. Save the **Index name** for Pinecone or an optional **Inbox ID** for AgentMail on the same page. See [STATUS.md](STATUS.md) for settings for the four pinned connectors.

### Choose the brain

Open **Settings → Brain**. Hearth defaults to **Smart routing** when two or more connected models are in the pool. With fewer models it defaults to **Auto (priority)**, which tries Muse Spark first, followed by other connected chat providers and then Mock. You can select either mode explicitly, give a specific provider and model priority, or choose **Mock** for the offline demo. The menu marks connected integrations that lack a chat adapter.

Smart routing starts with the connected provider defaults. Use **Add model** to choose from a provider's live chat list and add several models from the same provider. Expand a pool row to edit its speed, cost tier, tool reliability, context size, and multilingual tags. Defaults for known model IDs are in `config/connectors.json`. For a specific provider, choose from its live list or enter a model ID. **Test model** sends a short prompt and shows its reply and latency. **Save** checkpoints and applies the settings in `~/hearth/config/connectors.local.json` on the Sprite. [Hugging Face model discovery](https://huggingface.co/docs/inference-providers/en/hub-api#list-openai-compatible-models)

The router uses prompt text and thread type to recognize quick chat, tools or actions, long reasoning or planning, code, multilingual prompts, and side chat. **Routing preview** shows the first pick for each type. **Test routing** shows the class and full order for your prompt and current draft settings without contacting a model. The router uses up to 24 attempts per model from the past seven days, including median successful latency, error rate, and the time of the last failure. A failure in the last five minutes moves that model behind eligible models without recent failures. The Sprite saves these stats to `~/hearth/data/brain_stats.json`.

New replies show the model that answered and the routing reason. Timeline shows the planned order and records any fallback. After a workspace action has started, the next model continues with a text-only reply and the existing action cards. Hugging Face uses native streaming tool calls and can switch to JSON instructions when the model rejects the tool request.

### Configure memory recall

Open **Settings → Memory** and choose **Auto**, **Pinecone**, or **Local** under **Recall store**. Auto prefers Pinecone when connected. Both Auto and Pinecone fall back to the offline workspace search when the provider is unavailable or exceeds the chat budget. The Pinecone request has a 550 ms budget per chat turn. **Test recall** allows up to 10 seconds for diagnosis. It shows the store that answered, hit scores, and latency, with optional kind and thread filters. The **Remembered** chip shows scores and links to cited Markdown, chat messages, or artifacts. Ember reacts when Pinecone returns hits.

Pinecone uses the `hearth-memory` index and defaults to the `frank` namespace. Keep a distinct namespace in the `pinecone.namespace` field of `connectors.local.json` for each Hearth profile that shares the index. Hearth discovers and saves the index host there. It first requests a serverless index in AWS `us-east-1` with integrated `multilingual-e5-large` embeddings mapped to `text`. If integrated creation is unavailable, it requests a 384-dimension cosine index and uses Hugging Face `intfloat/multilingual-e5-small` for English and Chinese. Reranking uses `bge-reranker-v2-m3` when time and connector access permit. [Pinecone integrated index API](https://docs.pinecone.io/reference/api/2025-10/control-plane/create_for_model), [Pinecone integrated search API](https://docs.pinecone.io/reference/api/2025-10/data-plane/search_records), [Fly Pinecone connector](https://fly.io/sprites/ecosystem/)

The Pinecone card shows the model, dimension, namespace record count, and last sync. The store selector controls recall. Sync uses the saved scope whenever Pinecone is authorized. Hearth backfills an empty namespace at startup and syncs edits, deletes, and reversals in batches. **Sync memories to Pinecone** reconciles stored notes and text artifacts now. **Rebuild index** asks for confirmation before re-upserting the saved scope and pruning stale Hearth records in the profile namespace. Both show progress and counts. Text Box files added outside Hearth are refreshed during startup and manual sync.

Set **Top-k** and minimum cosine similarity. Markdown folders can be included or excluded, and chat and voice transcript recall is opt-in. Hearth redacts recognized credentials before embedding or sending snippets and metadata. **Auto-remember** defaults to **Off**. **Ask first** shows an approval card, and **Automatic** saves durable facts to the current UTC daily note. **Forget** checkpoints and removes the selected note or excerpt, or excludes a chat message while keeping the transcript visible.

If the Fly gateway rejects index creation, open the Pinecone project connected to the Sprite and create a serverless `hearth-memory` index with 384 dimensions and cosine similarity in AWS `us-east-1`. Then select **Sync memories to Pinecone**. The Sprite's existing connector supplies credentials for all requests. [Pinecone index setup](https://docs.pinecone.io/guides/legacy/vectors-api/create-a-vector-index), [Sprite verification](STATUS.md)

### Configure web search

Open **Settings → Search** and choose **Auto**, **Off**, or a connected provider. Auto tries Tavily, Exa, Linkup, Kagi, Keenable, and Firecrawl in order. It moves to the next connected provider on error and records the failure in Timeline. Disconnected providers link to **Connections**. Hearth offers the brain its web search tool when the selection has an active provider.

Choose **Max results** (1–10), recency, Safe search, and comma-separated include or exclude domains. Safe search uses provider filtering where available. With Exa and Linkup it uses a basic local filter. **Test search** shows results and latency for the current choices. **Save** checkpoints and applies the selection immediately.

### Use a connected provider in chat

Ask Hearth to use a connected provider. On the Mock brain, use `Gateway github GET /user`. To supply JSON, use `Gateway github POST /repos/OWNER/REPO/issues | {"title":"Example"}` with a repository where you intend to open an issue.

The generic gateway tool sends a provider-relative request through Sprites. GET executes immediately. Other methods show the method, path, and JSON body for review. **Approve** saves a checkpoint first, then sends one request. The card can show the response in the current browser session. A checkpoint restores Hearth’s workspace. Provider changes persist independently. Small JSON and text responses can be previewed in Hearth.

## How it works

- `hearth.server` serves the browser app and JSON API. Chat uses server-sent events for reply text and action cards. The agent uses tools for memory, search, email proposals, reminders, and checkpoints. The generic gateway tool handles authorized providers. Vocal Bridge room credentials are available only through the call token route.
- Memory lives in `USER.md`, `people/*.md`, `topics/*.md`, and `daily/YYYY-MM-DD.md`. Each transcript is a JSONL file under `live/threads/` in the data directory. The thread index sits beside them. The first write to Main migrates any existing chat history from `live/state.json`. Actions and reminders share the lock-protected state file. The web and scheduler run as separate Sprite services.
- The offline mock uses the same tool interface as the model adapters. The header shows the active brain while Settings shows the saved preference.
- Provider calls go through the Sprites gateway without an Authorization header. Hearth stores connector IDs and supported settings. Fly holds the credentials. The chosen search and recall providers run through that gateway. Pinecone stores vectors in a profile namespace. Chat email drafts send after approval. Reminder emails send through AgentMail when their selected channel is due, using the saved recipient. [Provider setup details](STATUS.md)
- Checkpoint Undo restores the entire Sprite filesystem, including later chat, memory, reminders, and deployed files. The local backend restores the `live/` workspace directory. Delivered email stays with the provider. Hearth reconciles the selected Pinecone namespace after a workspace restore.

## Deploy privately

```sh
scripts/deploy.sh
sprite exec --http-post --no-stdin --no-port-forward -o xuefeng-zhu -s hearth -- curl -fsS http://localhost:8080/health
sprite exec --http-post --no-stdin --no-port-forward -o xuefeng-zhu -s hearth -- curl -fsS http://localhost:8080/api/connections
```

The deploy script installs a versioned release on `hearth` in `xuefeng-zhu`, registers or restarts the `web` and `scheduler` services, and checks port 8080. Hearth saves discovered IDs and provider settings to `~/hearth/config/connectors.local.json` and keeps workspace data under `~/hearth/data`. Open the Sprite from the Fly dashboard and sign in as an organization member.

### Wake the scheduler

Hearth persists the next fire time, catches up on wake, and marks overdue deliveries in minutes. A recurring reminder that missed multiple occurrences records one catch-up and resumes at the next future occurrence. With the browser closed, an external timer must wake a hibernating Sprite. Five-minute polling can add up to a polling interval plus any delay on the scheduling host. For tighter timing, run the same command more frequently on an authenticated scheduler host. [Fly Sprites lifecycle](https://docs.sprites.dev/working-with-sprites/)

```sh
scripts/wake.sh
```

The script defaults to the authenticated `sprite` CLI and calls `POST /api/scheduler/tick` inside the Sprite. The endpoint requires `X-Hearth-Tick-Token` and returns `last_tick` and `next_due`, which also appear in **Settings → Reminders**. It also polls the Inbox. The Sprite generates the tick token and a separate reminder signing key under `~/hearth/data/` with owner-only permissions.

For HTTP, supply `HEARTH_SPRITE_URL`, `HEARTH_TICK_TOKEN`, and `SPRITE_API_TOKEN` in the script's environment. The URL uses Sprite authentication and accepts an organization token. The Hearth token is in `~/hearth/data/scheduler-tick.token` inside the Sprite. Transfer it privately to your scheduler's secret store. `.github/workflows/wake.yml.example` is an inactive template. To opt in later, set the three repository secrets and rename the template to `wake.yml` on the default branch. Its schedule is every five minutes.
