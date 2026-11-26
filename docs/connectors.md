# Sprites connectors

1. In the Fly.io dashboard, select your organization and open **Sprites → Connectors → Add connector**.
2. Complete the provider's authorization or enter its credential in Fly. In access settings, turn off **Allow all sprites** and set **Name Prefix** to `hearth` for the standard deployment. When you also deploy a Pages publisher, require a label assigned only to the private workspace Sprite. Fly requires both matches when a policy uses a prefix and a label.
3. In Hearth, open **Settings → Connections** and select **Refresh**. Check the **Configured** tab and use **Test** where available. Apply any feature settings below.

Fly attaches provider credentials when it forwards requests. Hearth stores connector selections and feature settings. A successful check confirms the probe or gateway authorization for that entry. Feature endpoints may require additional permissions or gateway support. [Fly dashboard](https://fly.io/dashboard), [Fly connector setup](https://fly.io/sprites/ecosystem/)

| Connector | In the Fly dashboard | In Hearth |
| --- | --- | --- |
| Hugging Face | Add a fine-grained user token with **Make calls to Inference Providers** permission. | Choose a chat model under **Settings → Brain**. Whisper and dense memory embeddings use the same connection. The attachment path uses its configured vision models. |
| Pinecone | Add a project key that can describe the target index, query it, and write or delete vectors. | Set the index name in **Settings → Connections** if you changed it from `hearth-memory`. Select **Sync memories to Pinecone** under **Settings → Memory**. [Index setup](memory.md#pinecone) |
| Box | Choose **Continue with Box** and authorize file access. | Under **Settings → Artifacts**, choose the Box folder name and decide whether to auto-save. Retry failed syncs from the artifact. Hearth keeps local copies when upload fails. [Ask my files and Box AI probe](box.md) |
| Exa | Add an Exa API key. | Choose **Exa** or **Auto** under **Settings → Search**, then use **Test search**. |
| AgentMail | Add an AgentMail API key with inbox and mail access. | Save an existing inbox ID in **Settings → Connections** or use **Create inbox** from the Email Hearth panel when offered. Set a recipient in **Settings → Reminders** to enable reminder or task email. |
| Vocal Bridge | Add a deployed voice agent's agent-scoped API key. | Refresh **Settings → Connections** and check access. Open **Call** in Chat to start a real session. [Voice agent configuration](voice.md#live-calls-with-vocal-bridge) |
| Browserbase | Optionally add a project API key and grant the Sprite access. | Refresh **Settings → Connections**, then enable browsing under **Settings → Search**. Search and fetch read public pages. Live sessions and interactive steps go through approval policy. |
| Ollama Cloud | Optionally add an Ollama Cloud API key. | Select **Ollama Cloud** and a model under **Settings → Brain**, or add a model to the Smart routing pool. |

[Connector and access-policy reference](https://fly.io/sprites/ecosystem/), [Ollama Cloud setup](https://docs.ollama.com/cloud)

## Verification and gateway limits

Run 34 verified Box upload, Whisper transcription, Exa search, and Browserbase's read-only connection probe. Run 44 verified an inbound AgentMail message triggering a local action. Runs 46 and 48 verified Ask my files with real Box reads, Pinecone, and a connected brain. Run 60 verified a live chat reply. These checks apply to the operations tested on those deployments. The setup table lists feature paths, and the Run 63 tests use offline fixtures for provider interactions. [Run 34 QA](../QA-REPORT.md#run-34), [Run 44](run-44.md), [Run 46](run-46.md), [Run 48 QA](../QA-REPORT.md#run-48), [Run 60](run-60.md)

- **Apify.** The gateway allowed the Actor-list probe and returned HTTP `403` for Actor details, account and usage, run, and dataset routes. Actor execution and result retrieval remain unverified. Hearth's approved page and price watchers use its public-page reader. [Apify probe](watchers.md)
- **Box AI.** The gateway returned HTTP `403` for single-file and multi-file Ask and for structured extraction. Ask my files uses Hearth's text extractors, Pinecone, and a connected brain. [Box AI probe](box.md#run-46-box-ai-probe)

## Box versions

Hearth can create a file or upload a new version through the gateway's Box upload routes. It first tries `GET /2.0/files/{file_id}/versions` for remote version history. When that route is unavailable, Hearth builds the history from Box versions it has observed and recorded locally. Revisions created elsewhere may be missing from that list. [Box adapter](../hearth/box.py), [Artifacts](../hearth/artifacts.py)

## Other providers

**Available, not used** groups providers without a dedicated Hearth feature, such as Apify and TypeSafeAI. Only connectors with a dedicated feature contribute to Home health and the sidebar connector warning. Authorized providers can still be called through Hearth's generic gateway tool, which validates the provider-relative path and applies the approval policy. [Connector catalog](../config/catalog.json), [Gateway request validation](../hearth/gateway_tools.py), [Model adapters](../hearth/connectors.py)
