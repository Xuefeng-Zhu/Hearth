# Box and Ask my files

In **Artifacts → Ask my files**, choose **All recent** to ask across the 25 most recently modified supported Box files, or choose **Select files** and pick up to 25. In Chat, start with “Ask my files” and include the exact filenames if you want to narrow the search. Answers show the file names they cite and an **Open in Box** link for each.

Hearth labels these answers **Answered by Hearth from your Box files**. The feature requires a Box connection, a Pinecone index, and a connected brain. Chat also needs a tool-capable brain. Dense Pinecone indexes use Hugging Face for embeddings. Choose the library folder in **Settings → Artifacts**. [Connector setup](connectors.md), [Pinecone setup](memory.md#pinecone)

Hearth reads the current Box versions in that folder using its attachment text extractors. Supported file types are DOCX, PDF, XLSX, PPTX, TXT, Markdown, and CSV, up to 20 MiB per file. Extraction reads up to 12,000 characters per file and up to 80 pages of a PDF. Image-only PDFs and encrypted PDFs may have no readable text. The question view reports files with missing or partial text.

Hearth sends the extracted chunks for embedding. Pinecone stores only vectors and revision identifiers in the `files` namespace. Keep the memory namespace separate. Each query filters by the selected files' current revisions. Older vectors can remain in Pinecone. The brain receives the question and only the retrieved passages as reference data. Box access for questions is read-only. Chat saves the resulting answer and citations in its thread. [File-question implementation](../hearth/file_questions.py)

## Artifact listings and transfers

Artifacts shows local files, Pages, and the last cached Box listing while a background worker walks the selected Box folder. `GET /api/artifacts` reports Box freshness as `fresh`, `stale`, or `refreshing`, with `box_refreshed_at` set to the last successful listing or null on a cold cache. A successful listing stays fresh for 30 seconds. A failed listing keeps the previous rows and becomes eligible for retry after five seconds on a later request. **Refresh** requests a new walk, and the visible view checks for its completion. Results from a previous connection, folder, or checkpoint are discarded. Ask my files and explicit Box recall refresh use scoped reads that can wait for Box. [Artifact listing](../hearth/artifacts.py), [Artifacts UI](../web/artifacts.js)

Generated-file writes, upload retries, and artifact undo release the workspace and artifact locks during rendering and Box I/O. The metadata commit rechecks the artifact revision and workspace checkpoint. Box version uploads use `If-Match` when a revision ETag is available. Multipart uploads read staged files in 64 KiB chunks. Remote artifact downloads spool in bounded chunks before Hearth sends the HTTP response, and local artifact downloads stream from disk. The 50 MiB Box download limit still applies. [Box adapter](../hearth/box.py), [Box I/O verification](run-59.md)

Box recall uses its own index snapshot. A failed listing keeps the old snapshot, and a partial download pass keeps available cached excerpts. `/api/status` reports `box_recall` freshness and the last full refresh time, which survives a restart once a full refresh has saved it. [Box recall refresh](../hearth/memory_sync.py), [Subsystem status](architecture.md#status-and-stale-data)

## Run 46 Box AI probe

On November 26, 2026, at 04:09 UTC, Hearth’s Sprite listed Artifacts with HTTP 200. The probe then used the same Sprites Box gateway connection as uploads and sent the following requests with Box IDs from Hearth’s own Artifacts folder.

| Request relative to the Box connection | Files | Result |
| --- | --- | --- |
| `POST 2.0/ai/ask` with `single_item_qa` | One artifact | HTTP 403 · endpoint unsupported by the connector |
| `POST 2.0/ai/ask` with `multiple_item_qa` | Two artifacts | HTTP 403 · endpoint unsupported by the connector |
| `POST 2.0/ai/extract_structured` with vendor, date, and total fields | One artifact | HTTP 403 · endpoint unsupported by the connector |

The gateway rejected all three routes. Box plan eligibility remains unverified. Structured vendor, date, and total extraction for forwarded Inbox receipts and bills remains unavailable through Box AI. [Box Ask API](https://developer.box.com/reference/post-ai-ask/), [Box structured extraction API](https://developer.box.com/reference/post-ai-extract-structured/), [Run 46 verification](run-46.md)
