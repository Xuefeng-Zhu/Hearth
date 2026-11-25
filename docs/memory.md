# Memory and recall

Hearth keeps Markdown notes under `live/memory/` in its data directory. On first startup it copies the [sample memory](../memory/) there. The Memory view reads the workspace files. Chat can cite matching excerpts from `USER.md` and the `people/`, `topics/`, and `daily/` folders.

Under **Settings → Memory**, choose **Auto**, **Pinecone**, **Local**, **Hugging Face embeddings**, or **Keyword**, and set the result limit, minimum similarity, and folder scope. Auto tries Pinecone when available. Local recall uses text matching on the Sprite. The Hugging Face embeddings option stores a local vector cache and uses Hugging Face to compute embeddings. Text artifacts can be included in recall, and chat and voice transcripts are opt-in. [Recall implementation](../hearth/recall.py)

## Pinecone index setup

1. Add Pinecone and Hugging Face through the [Fly connector setup](connectors.md). Give the Pinecone connector access to the project where the index lives.
2. Create a dense serverless index named `hearth-memory` with **384 dimensions** and **cosine** similarity. Choose a bring-your-own-vectors index. Hearth uses `intfloat/multilingual-e5-small` through Hugging Face for this configuration. The shipped connector settings specify AWS `us-east-1` for gateway creation attempts.
3. Refresh **Connections** in Hearth, then select **Sync memories to Pinecone** in **Settings → Memory**. Check the status and chunk count, then run **Test recall**.

If the index is missing, Hearth tries integrated index creation first, followed by dense index creation when Hugging Face is available. Use the Pinecone console when the gateway rejects creation. Existing compatible integrated indexes can also work when their embedding input maps to the `text` field. [Pinecone index creation](https://docs.pinecone.io/guides/indexes/create-an-index), [Hearth index adapter](../hearth/pinecone.py)

## Namespaces and sync

The default namespace for a new workspace is `hearth`. For multiple workspaces sharing an index, set a distinct `pinecone.namespace` in each private connector settings file before syncing. Namespaces isolate each workspace's records within the index. Existing local namespace overrides are kept. Rebuild reconciles Hearth's records within the selected namespace. It can prune records that fall outside the current corpus, so give each workspace its own namespace.

Startup and manual sync backfill notes and text artifacts. Edits, deletions, and Undo or Redo can trigger reconciliation. Pinecone recall can rerank results with `bge-reranker-v2-m3` when the route is available. Unavailable or timed-out Pinecone queries fall back to Local. [Sync worker](../hearth/memory_sync.py), [Pinecone namespaces](https://docs.pinecone.io/guides/data/implement-multitenancy)

## Remember and forget

**Auto-remember** defaults to **Off**. **Ask first** creates an approval, and **Automatic** can add facts to a UTC daily note. Editing or forgetting a note records a checkpoint and can offer item-level Undo. Forgetting a chat excerpt excludes it from recall while preserving the transcript. Hearth redacts recognized credential patterns before indexing, but connected recall still sends selected text or vectors to the configured providers. [Memory edits](../hearth/memory_edits.py), [Approval settings](approvals-and-tasks.md)
