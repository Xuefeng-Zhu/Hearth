# Hearth status

## Verified

- Deployed to the private `hearth` Sprite in `xuefeng-zhu`. Inside the Sprite, `localhost:8080/health` returned `{"ok": true, "checkpoints": "sprite"}`. A repeat deploy reused the same release. The service manager showed `web` and `scheduler` running. URL authentication is `sprite`.
- The native `sprite-env checkpoints` commands created and listed a checkpoint, then restored a test file to its original contents. The app independently verified its own Undo flow: the cleared Thanksgiving note appeared blank, its checkpoint appeared in Timeline, and the original Markdown returned after the Sprite restarted.
- The Sprite streamed the Thanksgiving turn, staged an invitation for approval, recorded a simulated send after approval, and delivered an in-app reminder. The verification restored the pre-demo state afterward. The sample notes are ready for the next run.
- Chromium verified Chat, approval, Memory, Timeline, and Undo at mobile and desktop widths. Sixteen offline tests cover the agent loop, streaming, memory, approval, recall, reminders, HTTP Undo, and the new connector flows.
- The private Sprite served `/health` and `/api/connections` on port 8080. Startup discovery and an explicit re-scan both completed successfully and reported all four providers as **Not set up**. Chromium verified the Connections tab, both settings forms, a single-call provider test, and the Mock-to-Muse Spark switch with a simulated gateway at desktop and mobile widths.

## Mocked and pending

- The gateway discovery response contained zero authorized connections. The deployed model is the deterministic mock, memory recall uses local keyword search, Tavily is disabled, and approved email goes to a local simulated outbox. The Hacksgiving connector requirement is pending until an authorized connector is configured and exercised. A dashboard connector that has never authorized this Sprite may remain invisible to discovery until you grant access. [Sprites gateway discovery](https://docs.fly.io/sprites/concepts/connectors#using-connectors-with-a-coding-agent)
- The live Meta, Pinecone, Tavily, and AgentMail paths require provider connections for verification. The mock uses sample recipients under `example.invalid`. Use an address you control when verifying live mail.
- Reminders are delivered in Hearth's Timeline when the scheduler can run. An authenticated external timer is needed to wake a hibernating Sprite with the browser closed. See the wake command in [README.md](README.md).

## Add the four Fly connectors

1. Open **Add connection** in the Fly dashboard and choose the provider. Create provider credentials in the provider console and enter them only in Fly’s connector form. [Fly dashboard connectors](https://fly.io/dashboard/xuefeng-zhu/sprites/connectors)

   | Fly provider | Provider setup | Hearth setting |
   | --- | --- | --- |
   | **Meta (Muse Spark)** | Select a Meta Model API team with access to `muse-spark-1.3` and create a key under **API keys**. [Meta authentication](https://dev.meta.ai/docs/authentication) | Hearth finds the connection and switches from the mock after a successful check. |
   | **Pinecone** | Create a serverless dense vector index using your own vectors, 1024 dimensions, and cosine similarity. Give the project key index read, vector write/query, and inference access. [Vector index setup](https://docs.pinecone.io/guides/legacy/vectors-api/create-a-vector-index), [Embedding model](https://docs.pinecone.io/models/multilingual-e5-large) | Enter the **Index name** if it differs from `hearth-memory`. |
   | **Tavily (Community)** | Create a key under **API Keys** on the Tavily dashboard home page. [Tavily connector](https://fly.io/changelog/another-batch-of-sprites-connectors/) | Hearth finds the connection automatically. |
   | **AgentMail** | Create or select a sending inbox and use a key with permission to read that inbox and send messages. [AgentMail permissions](https://docs.agentmail.to/permissions) | Enter the **Inbox ID**, usually the inbox address. |

2. Open the saved connector in Fly. In **Access Configuration**, turn off **Allow all sprites** and set **Name Prefix** to `hearth`. Check **Authorized Sprites** and save. If multiple Sprites share that prefix, add a unique label to the intended Sprite and require it under **Sprite Labels**. [Fly access configuration](https://docs.fly.io/sprites/concepts/connectors#configuring-access)
3. Open Hearth’s **Connections** tab, save any index or inbox setting, and click **Re-scan**. Click **Test** on each discovered connector to check it. Hearth writes the IDs to `~/hearth/config/connectors.local.json` after taking a checkpoint and updates the running agent.
4. To exercise the full integrations, send a chat message, ask for a memory search, and then ask for a web search. For AgentMail, draft an email to an address you control and approve it only if you want it sent. Real email and Pinecone data stay with the providers after a Sprite checkpoint restore.
