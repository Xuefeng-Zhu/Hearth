# Hearth status

## Verified

- Deployed to the private `hearth` Sprite in `xuefeng-zhu`. Inside the Sprite, `localhost:8080/health` returned `{"ok": true, "checkpoints": "sprite"}`. A repeat deploy reused the same release. The service manager showed `web` and `scheduler` running. URL authentication is `sprite`.
- The native `sprite-env checkpoints` commands created and listed a checkpoint, then restored a test file to its original contents. The app independently verified its own Undo flow: the cleared Thanksgiving note appeared blank, its checkpoint appeared in Timeline, and the original Markdown returned after the Sprite restarted.
- The Sprite streamed the Thanksgiving turn, staged an invitation for approval, recorded a simulated send after approval, and delivered an in-app reminder. The verification restored the pre-demo state afterward. The sample notes are ready for the next run.
- Chromium verified Chat, approval, Memory, Timeline, and Undo at mobile and desktop widths. Eleven offline tests cover the agent loop, streaming, memory, approval, recall, reminders, and HTTP Undo.

## Mocked and pending

- The gateway discovery response contained zero authorized connections. The deployed model is the deterministic mock, memory recall uses local keyword search, Tavily is disabled, and approved email goes to a local simulated outbox. The Hacksgiving connector requirement is pending until an authorized connector is configured and exercised.
- The live Meta, Pinecone, Tavily, and AgentMail paths require provider connections for verification. The mock uses sample recipients under `example.invalid`. Use an address you control when verifying live mail.
- Reminders are delivered in Hearth's Timeline when the scheduler can run. An authenticated external timer is needed to wake a hibernating Sprite with the browser closed. See the wake command in [README.md](README.md).

## Add the four Fly connectors

1. Open the [Fly dashboard](https://fly.io/dashboard), select **xuefeng-zhu**, then open **Sprites → Connectors → Add connector** (also labeled **Add connection**). Choose one of the providers below, enter its key in the Fly form, and save. Repeat for each provider you want to enable. Provider keys belong in the Fly form. [Fly connector setup](https://docs.fly.io/sprites/concepts/connectors)

   | Dashboard provider | Provider setup | Hearth config fields |
   | --- | --- | --- |
   | **Meta (Muse Spark)** | In Meta Model API, select your team and use **API keys → Create API key**. Ensure the team has access to `muse-spark-1.3`. [Meta authentication](https://dev.meta.ai/docs/authentication) | Set `connection_id` on the `llm` entry with `provider: "meta"`. Keep `model` set to `muse-spark-1.3` or enter the Muse Spark model ID available to your team. |
   | **Pinecone** | In the Pinecone console, create a serverless **vector index** named `hearth-memory` with dense vectors, dimension `1024`, and metric `cosine`. Use the bring-your-own-vectors option. Create a project API key with index list/describe, vector write/query, and inference access. [Vector index setup](https://docs.pinecone.io/guides/legacy/vectors-api/create-a-vector-index), [Embedding model](https://docs.pinecone.io/models/multilingual-e5-large) | Set `pinecone.connection_id`. Set `pinecone.index` if you used a different index name. |
   | **Tavily** | In the Tavily dashboard, open **API Keys** on the home page and create a key. Select **Tavily**, marked **Community**, in Fly. [Tavily connector](https://fly.io/changelog/another-batch-of-sprites-connectors/) | Set `tavily.connection_id`. |
   | **AgentMail** | In the AgentMail console, create or select a sending inbox under **Inboxes** and copy its Inbox ID. Under **API Keys**, create a key with access to that inbox and permission to send messages. [AgentMail console fields](https://docs.agentmail.to/imap-smtp#finding-your-credentials), [Send permissions](https://docs.agentmail.to/permissions) | Set `agentmail.connection_id` and `agentmail.inbox_id`. The inbox ID is usually its email address. |

2. Open each saved connector. In **Access Configuration**, turn **Allow all sprites** off and set **Name Prefix** to `hearth`. Check that **Authorized Sprites** shows only the intended Sprite, then save. If another Sprite shares that prefix, add a label unique to `hearth` and require it in **Sprite Labels**. Click **Test reachability** for `hearth` if shown, or select `hearth` in **Gateway Playground** and run a read-only example from **API Usage**. [Fly access configuration](https://docs.fly.io/sprites/concepts/connectors#configuring-access)
3. On each connector's detail page, take the ID from the **API Usage** gateway URL. It is the segment immediately after the provider in `https://api.sprites.dev/v1/gateway/<provider>/<connection_id>/<path>`. Copy the identifier into the corresponding config field above. [Fly gateway URL format](https://docs.fly.io/sprites/concepts/connectors#calling-a-connector-from-a-sprite)
4. From the repo, make an override and edit the fields above. The tracked template contains empty identifiers. Leave the mock model entry at the end of `llm` for offline fallback.

   ```sh
   cp config/connectors.json config/connectors.local.json
   ${EDITOR:-vi} config/connectors.local.json
   ```

5. Upload the override to `~/hearth/config/connectors.local.json` inside the Sprite, validate it, and restart the web service. The deploy script preserves that path. Keep the local override so you can reapply it after restoring a checkpoint created before connector setup.

   ```sh
   sprite exec --http-post --stdin --no-port-forward -o xuefeng-zhu -s hearth -- sh -c '
     set -eu
     umask 077
     dir="$HOME/hearth/config"
     mkdir -p "$dir"
     tmp=$(mktemp "$dir/connectors.XXXXXXXX")
     cat > "$tmp"
     python3 -m json.tool "$tmp" >/dev/null 2>&1
     mv "$tmp" "$dir/connectors.local.json"
     sprite-env services restart web >/dev/null 2>&1
   ' < config/connectors.local.json

   sprite exec --http-post -s hearth -- curl -fsS http://localhost:8080/health
   ```

6. In Hearth, send a chat message to exercise Muse Spark. Ask it to use memory search on a family topic to exercise Pinecone, then ask it to search the web to exercise Tavily. For AgentMail, ask it to draft an email to an address you control, inspect the draft card, and approve it only if you want it sent. Real email stays delivered after a checkpoint restore. Pinecone sync sends note excerpts to the configured index and older revision namespaces remain at Pinecone.

You can also configure Ollama Cloud and OpenRouter connections in the corresponding `llm` entries using the same access and ID steps. [Fly connector catalog](https://fly.io/sprites/ecosystem/)
