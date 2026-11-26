# Run 46 — Ask my files

**Artifacts → Ask my files** answers questions over selected Box files or up to 25 recent files. Chat uses the same retrieval through the `ask_files` tool. The Sprites Box gateway returned HTTP 403 for all three Box AI requests, so Hearth uses its text extractors, Pinecone’s `files` namespace, and its connected brain. The interface identifies the source as **Answered by Hearth from your Box files**. Structured receipt and bill fields remain unavailable in Inbox. [Box usage and probe results](box.md)

## Sprite verification

On November 26, 2026, at 04:26 UTC, the deployed Sprite returned HTTP 200 from `/health` with Sprite checkpoints enabled. A request to `POST /api/artifacts/ask` with two fictional test artifacts returned HTTP 200.

**Question**

When does the Fernwick Lighthouse tour start, where is the meeting point, and how many lanterns are listed?

**Answer**

> The Fernwick Lighthouse tour starts at 4:15 p.m. on Saturday. The meeting point is the blue gate. There are 7 lanterns listed.

**Citations**

- Run 46 Fictional Lighthouse Plan.docx
- Run 46 Fictional Lighthouse Supplies.xlsx

Both **Open in Box** destinations matched the artifacts. The live `ask_files` call in a side chat answered the same question and returned both citations. The fictional test artifacts remain in Box.

## Local verification

- `python -m unittest discover -s tests` passed 230 tests, including five for file questions with fake Box, Pinecone, and brain calls.
- `node --test tests/*.test.mjs` passed nine tests. The web JavaScript modules passed syntax checks.
- WebKit exercised selected files, all recent, editing a question, citation links, focus return, and Chat with fictional data at 390×844 and 375×667 in dark mode. The checked controls had 44 px targets, the contrast samples met AA, and the inspected surfaces showed no horizontal overflow.
- Eight screenshots and redacted checks are under `/workspace/tmp/hearth-qa/run46/`.
