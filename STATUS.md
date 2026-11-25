# Hearth status

## Verified

- Settings offers Auto, connected AI providers, and Mock. The private Sprite is saved on **Hugging Face · Qwen3-Coder-Next:fastest**. The live model menu listed 101 chat models, and the final Test returned “Hearth is ready.” in 965 ms. The saved choice survived redeployment.
- The Thanksgiving shortcut ran from inside the Sprite on Hugging Face. The final check streamed 116 text events, staged a pending invitation to the two sample addresses, and scheduled an in-app reminder. The invitation remains awaiting approval.
- Chromium verified the provider and model controls, Test, Save, the live header, and the approval card, including a 390px mobile layout check. The Settings capture is at `/workspace/tmp/hearth-qa/hearth-settings.png`.
- Deployed to the private `hearth` Sprite in `xuefeng-zhu`. Inside the Sprite, `localhost:8080/health` returned `{"ok": true, "checkpoints": "sprite"}`. A repeat deploy reused the same release. The service manager showed `web` and `scheduler` running. URL authentication is `sprite`.
- The native `sprite-env checkpoints` commands created and listed a checkpoint, then restored a test file to its original contents. The app independently verified its own Undo flow: the cleared Thanksgiving note appeared blank, its checkpoint appeared in Timeline, and the original Markdown returned after the Sprite restarted.
- The Sprite streamed the Thanksgiving turn, staged an invitation for approval, recorded a simulated send after approval, and delivered an in-app reminder. The verification restored the pre-demo state afterward. The sample notes are ready for the next run.
- The catalog contains 61 entries. Discovery includes providers encountered at runtime, and the four Hearth essentials appear first. Thirty-three entries have a read-only Test path, including Hugging Face at `v1/models`. [Fly ecosystem catalog](https://fly.io/sprites/ecosystem/), [Fly connector reference](https://docs.fly.io/sprites/concepts/connectors)
- Twenty-eight offline tests passed. Coverage includes checkpointed brain selection, live-list filtering, streamed Hugging Face tool calls and JSON fallback, Timeline notices, and approval replay protection.
- Chromium verified the pinned cards, search, category filter, empty results, and re-scan at desktop and mobile widths using the deployed Connections API and the deployed asset versions. The desktop capture is at `/workspace/tmp/hearth-qa/hearth-catalog.png`.

## Mocked and pending

- Hugging Face is authorized and exercised live. Memory recall uses local keyword search, Tavily is disabled, and approved email goes to a local simulated outbox. The sample recipients use `example.invalid`. Live mail verification needs an AgentMail connection and an address you control. [Sprites gateway discovery](https://docs.fly.io/sprites/concepts/connectors#using-connectors-with-a-coding-agent)
- Other chat providers and failover during a live provider outage are pending live verification. Offline tests exercise fallback and the Hugging Face JSON tool mode.
- Reminders are delivered in Hearth's Timeline when the scheduler can run. An authenticated external timer is needed to wake a hibernating Sprite with the browser closed. See the wake command in [README.md](README.md).

## Add the four Fly connectors

1. Open **Add connection** in the Fly dashboard and choose the provider. Create provider credentials in the provider console and enter them only in Fly’s connector form. [Fly dashboard connectors](https://fly.io/dashboard/xuefeng-zhu/sprites/connectors)

   | Fly provider | Provider setup | Hearth setting |
   | --- | --- | --- |
   | **Meta (Muse Spark)** | Select a Meta Model API team with access to `muse-spark-1.3` and create a key under **API keys**. [Meta authentication](https://dev.meta.ai/docs/authentication) | Hearth discovers the connection and tries Muse Spark first for chat. |
   | **Pinecone** | Create a serverless dense vector index using your own vectors, 1024 dimensions, and cosine similarity. Give the project key index read, vector write/query, and inference access. [Vector index setup](https://docs.pinecone.io/guides/legacy/vectors-api/create-a-vector-index), [Embedding model](https://docs.pinecone.io/models/multilingual-e5-large) | Enter the **Index name** if it differs from `hearth-memory`. |
   | **Tavily (Community)** | Create a key under **API Keys** on the Tavily dashboard home page. [Tavily connector](https://fly.io/changelog/another-batch-of-sprites-connectors/) | Hearth finds the connection automatically. |
   | **AgentMail** | Create or select a sending inbox and use a key with permission to read that inbox and send messages. [AgentMail permissions](https://docs.agentmail.to/permissions) | Enter the **Inbox ID**, usually the inbox address. |

2. Open the saved connector in Fly. In **Access Configuration**, turn off **Allow all sprites** and set **Name Prefix** to `hearth`. Check **Authorized Sprites** and save. If multiple Sprites share that prefix, add a unique label to the intended Sprite and require it under **Sprite Labels**. [Fly access configuration](https://docs.fly.io/sprites/concepts/connectors#configuring-access)
3. Open Hearth’s **Connections** tab, save any index or inbox setting, and click **Re-scan**. Click **Test** to make one read-only GET request where Hearth has a safe path. Hearth writes the IDs to `~/hearth/config/connectors.local.json` after taking a checkpoint and updates the running agent.
4. To exercise the full integrations, send a chat message, ask for a memory search, and then ask for a web search. For AgentMail, draft an email to an address you control and approve it only if you want it sent. Real email and Pinecone data stay with the providers after a Sprite checkpoint restore.
