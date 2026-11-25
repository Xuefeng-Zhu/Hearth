# Hearth status

## Verified

- Semantic recall and selectable web search are deployed on the private Sprite. An isolated workspace running the deployed release created a native checkpoint and reindexed seven excerpts with Hugging Face BGE Small. For “who can't eat nuts,” Keyword missed the synthetic allergy note. Hugging Face returned it at line 3 with cosine similarity 0.684 and keyword overlap 0. A live Hugging Face chat turn cited that line, and Chromium opened it from the **Remembered** chip.
- The Hugging Face gateway also returned vectors for BGE Base and Multilingual E5. Auto recall fell through to Hugging Face after Pinecone returned HTTP 404 for the configured index.
- Exa was the only connected search provider and returned live results for Python pathlib. Chromium showed its connected state, the other five providers’ **Connect in Connections** buttons, and the live Test results. Both Settings panels fit at 390px. Desktop captures are at `/workspace/tmp/hearth-qa/hearth-memory-settings.png` and `/workspace/tmp/hearth-qa/hearth-search-settings.png`.
- Forty-one tests pass. The new and updated tests cover semantic and keyword ranking, incremental edits and cache reuse, all-thread recall scope, source citations, reindex and Forget checkpoints, auto-remember approval, six gateway adapters, search tool availability, and Timeline failover.

- Side chats are deployed on the private Sprite. In an isolated workspace running the deployed code inside that Sprite, **Hugging Face · Qwen3-Coder-Next:fastest** answered a `/btw` prompt using a reference word from the active Main turn. The side reply finished at 3.15 seconds. Main finished at 51.42 seconds after 3,796 streamed text events, and its queued follow-up started at 51.43 seconds. The two transcripts stayed separate.
- Chromium with Mock verified the pinned Main thread, side creation through the button and `/side`, automatic titles, rename, the busy dot, queued follow-ups, sharing, Timeline source labels, and delete confirmation. At 390px, the thread picker worked without horizontal overflow. Captures are at `/workspace/tmp/hearth-qa/hearth-sidechats.png` and `/workspace/tmp/hearth-qa/hearth-sidechats-mobile.png`.
- Settings offers Auto, connected AI providers, and Mock. At the side-chat verification, the Sprite was on **Auto**, which selected **Hugging Face · Qwen3-Coder-Next:fastest**. In the earlier Settings verification, the live menu listed 101 chat models, Test returned “Hearth is ready.” in 965 ms, and an explicit model choice survived redeployment.
- The Thanksgiving shortcut ran from inside the Sprite on Hugging Face. The final check streamed 116 text events, staged a pending invitation to the two sample addresses, and scheduled an in-app reminder. The invitation remains awaiting approval.
- Chromium verified the provider and model controls, Test, Save, the live header, and the approval card, including a 390px mobile layout check. The Settings capture is at `/workspace/tmp/hearth-qa/hearth-settings.png`.
- Deployed to the private `hearth` Sprite in `xuefeng-zhu`. Inside the Sprite, `localhost:8080/health` returned `{"ok": true, "checkpoints": "sprite"}`. A repeat deploy reused the same release. The service manager showed `web` and `scheduler` running. URL authentication is `sprite`.
- The native `sprite-env checkpoints` commands created and listed a checkpoint, then restored a test file to its original contents. The app independently verified its own Undo flow: the cleared Thanksgiving note appeared blank, its checkpoint appeared in Timeline, and the original Markdown returned after the Sprite restarted.
- The Sprite streamed the Thanksgiving turn, staged an invitation for approval, recorded a simulated send after approval, and delivered an in-app reminder. The verification restored the pre-demo state afterward. The sample notes are ready for the next run.
- The catalog contains 61 entries. Discovery includes providers encountered at runtime, and the four Hearth essentials appear first. Thirty-three entries have a read-only Test path, including Hugging Face at `v1/models`. [Fly ecosystem catalog](https://fly.io/sprites/ecosystem/), [Fly connector reference](https://docs.fly.io/sprites/concepts/connectors)
- Chromium verified the pinned cards, search, category filter, empty results, and re-scan at desktop and mobile widths using the deployed Connections API and the deployed asset versions. The desktop capture is at `/workspace/tmp/hearth-qa/hearth-catalog.png`.

## Mocked and pending

- Pinecone is authorized and its index list is empty. Pinecone indexing and query were covered with mocks. Tavily, Linkup, Kagi, Keenable, and Firecrawl were also covered with mocked HTTP while disconnected. AgentMail remains simulated until connected, and the sample recipients use `example.invalid`. [Sprites gateway discovery](https://docs.fly.io/sprites/concepts/connectors#using-connectors-with-a-coding-agent)
- Other chat providers and failover during a live provider outage are pending live verification. Offline tests exercise fallback and the Hugging Face JSON tool mode.
- Reminders are delivered in Hearth's Timeline when the scheduler can run. An authenticated external timer is needed to wake a hibernating Sprite with the browser closed. See the wake command in [README.md](README.md).

## Add the four Fly connectors

1. Open **Add connection** in the Fly dashboard and choose the provider. Create provider credentials in the provider console and enter them only in Fly’s connector form. [Fly dashboard connectors](https://fly.io/dashboard/xuefeng-zhu/sprites/connectors)

   | Fly provider | Provider setup | Hearth setting |
   | --- | --- | --- |
   | **Meta (Muse Spark)** | Select a Meta Model API team with access to `muse-spark-1.3` and create a key under **API keys**. [Meta authentication](https://dev.meta.ai/docs/authentication) | Hearth discovers the connection and tries Muse Spark first for chat. |
   | **Pinecone** | Create a serverless dense vector index using your own vectors and cosine similarity. Use 1024 dimensions for the default Pinecone inference model, 384 for Hugging Face BGE Small, or 768 for Hugging Face BGE Base and Multilingual E5. Give the project key index read, vector write/query, and inference access. [Vector index setup](https://docs.pinecone.io/guides/legacy/vectors-api/create-a-vector-index), [Embedding model](https://docs.pinecone.io/models/multilingual-e5-large) | Enter the **Index name** if it differs from `hearth-memory`. |
   | **Tavily (Community)** | Create a key under **API Keys** on the Tavily dashboard home page. [Tavily connector](https://fly.io/changelog/another-batch-of-sprites-connectors/) | Hearth finds the connection automatically. |
   | **AgentMail** | Create or select a sending inbox and use a key with permission to read that inbox and send messages. [AgentMail permissions](https://docs.agentmail.to/permissions) | Enter the **Inbox ID**, usually the inbox address. |

2. Open the saved connector in Fly. In **Access Configuration**, turn off **Allow all sprites** and set **Name Prefix** to `hearth`. Check **Authorized Sprites** and save. If multiple Sprites share that prefix, add a unique label to the intended Sprite and require it under **Sprite Labels**. [Fly access configuration](https://docs.fly.io/sprites/concepts/connectors#configuring-access)
3. Open Hearth’s **Connections** tab, save any index or inbox setting, and click **Re-scan**. Click **Test** to make one read-only GET request where Hearth has a safe path. Hearth writes the IDs to `~/hearth/config/connectors.local.json` after taking a checkpoint and updates the running agent.
4. To exercise the full integrations, send a chat message, ask for a memory search, and then ask for a web search. For AgentMail, draft an email to an address you control and approve it only if you want it sent. Real email and Pinecone data stay with the providers after a Sprite checkpoint restore.
