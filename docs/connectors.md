# Sprites connectors

1. In the Fly.io dashboard, select your organization and open **Sprites → Connectors → Add connector**.
2. Complete the provider's authorization or enter its credential in Fly. In access settings, turn off **Allow all sprites** and set **Name Prefix** to `hearth` for the standard deployment. When you also deploy a Pages publisher, require a label assigned only to the private workspace Sprite. Fly requires both matches when a policy uses a prefix and a label.
3. In Hearth, open **Connections** and select **Refresh**. Check the **Configured** tab and use **Test** where available. Apply any feature settings below.

Fly attaches provider credentials when it forwards requests. Hearth stores connector selections and feature settings. A successful check confirms the probe or gateway authorization for that entry. Feature endpoints may require additional permissions or gateway support. [Fly dashboard](https://fly.io/dashboard), [Fly connector setup](https://fly.io/sprites/ecosystem/)

| Connector | In the Fly dashboard | In Hearth |
| --- | --- | --- |
| Hugging Face | Add a fine-grained user token with **Make calls to Inference Providers** permission. | Choose a chat model under **Settings → Brain**. Whisper and dense memory embeddings use the same connection. The attachment path uses its configured vision models. |
| Pinecone | Add a project key that can describe the target index, query it, and write or delete vectors. | Set the index name in **Connections** if you changed it from `hearth-memory`. Select **Sync memories to Pinecone** under **Settings → Memory**. [Index setup](memory.md#pinecone-index-setup) |
| Box | Choose **Continue with Box** and authorize file access. | Under **Settings → Artifacts**, choose the Box folder name and decide whether to auto-save. Retry failed syncs from the artifact. Hearth keeps local copies when upload fails. |
| Exa | Add an Exa API key. | Choose **Exa** or **Auto** under **Settings → Search**, then use **Test search**. |
| AgentMail | Add an AgentMail API key with inbox and mail access. | Save an existing inbox ID in **Connections** or use **Create inbox** from the Email Hearth panel when offered. Set a recipient in **Settings → Reminders** to enable reminder or task email. |
| Vocal Bridge | Add a deployed voice agent's agent-scoped API key. | Refresh **Connections** and check access. Open **Call** in Chat to start a real session. [Voice agent configuration](voice.md#live-calls-with-vocal-bridge) |
| Browserbase | Optionally add a project API key and grant the Sprite access. | Refresh **Connections**, then enable browsing under **Settings → Search**. Search and fetch read public pages. Live sessions and interactive steps go through approval policy. The demo deployment has Browserbase connected. |
| Ollama Cloud | Optionally add an Ollama Cloud API key. | Select **Ollama Cloud** and a model under **Settings → Brain**, or add a model to the Smart routing pool. |

[Connector and access-policy reference](https://fly.io/sprites/ecosystem/), [Ollama Cloud setup](https://docs.ollama.com/cloud)

## Box versions

Hearth can create a file or upload a new version through the gateway's Box upload routes. It first tries `GET /2.0/files/{file_id}/versions` for remote version history. When that route is unavailable, Hearth builds the history from Box versions it has observed and recorded locally. Revisions created elsewhere may be missing from that list. [Box adapter](../hearth/box.py), [Artifacts](../hearth/artifacts.py)

## Other providers

**Not configured** lists providers from the bundled catalog. An authorized connector can be available through Hearth's generic gateway tool even when it has no dedicated feature adapter. TypeSafeAI appears in the catalog and has no dedicated brain adapter. The generic tool validates the provider-relative path and applies approval policy to the request. [Connector catalog](../config/catalog.json), [Gateway request validation](../hearth/gateway_tools.py), [Model adapters](../hearth/connectors.py)
