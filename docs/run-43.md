# Run 43 — Nightly Memory review

The nightly schedule defaults to 03:00 Pacific. Settings → Memory offers the schedule toggle, time, and Run now. Memory → Review shows the proposed changes and source excerpts. Pending proposals surface in Feed after quiet hours. [Memory guide](memory.md#nightly-memory-review)

## Sprite verification

On November 26, 2026, at 03:42 UTC, `scripts/deploy.sh` completed and the deployed `/health` returned HTTP 200 with Sprite checkpoints enabled. The app reported its next run at 03:00 Pacific.

A manual pass on the running Sprite completed in live mode with the fast model. It reviewed 23 source excerpts, verified 24 Pinecone records in the existing namespace, and produced a two-proposal digest with a visible Feed card. The Markdown file hashes matched before and after the pass. The live check covered generation and publication. Approval, Pinecone sync triggering, and Undo were exercised using fictional data and fakes.

## Local verification

- `python -m unittest discover -s tests` passed 214 tests, including seven for Memory review.
- `node --test tests/*.test.mjs` passed eight tests. Every app JavaScript module passed `node --check`.
- WebKit passed the Settings, Run now, Feed, per-item and bulk decisions, and Timeline Undo flow on dark 390×844 and 375×667 viewports. The review surfaces met the 44 px target check, had no horizontal overflow, and passed the sampled WCAG AA contrast checks.
- Fictional WebKit screenshots and the count-only Sprite check are in `/workspace/tmp/hearth-qa/run43/`. [Browser fixture](../tests/run43-browser.py)
