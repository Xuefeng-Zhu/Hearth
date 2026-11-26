# Run 58 — Blocking calls and model payloads

D12 started from merge commit `06fa496`, with Runs 50 and 52 already on `main`.

| Check | Pre-D12 | Post-D12 |
| --- | ---: | ---: |
| Python unit tests | 281 passed | 288 passed |
| Node tests | 9 passed | 9 passed |
| JavaScript files checked with `node --check` | 25 passed | 25 passed |
| Offline Chromium smoke | Passed | Passed |

The merged baseline required no repair commit. The new regressions reproduced the reply ordering, recall lock contention, repeat extraction, and oversized model context before the fixes.

- Side chat persists the reply with a fallback summary and emits `done` before submitting the summary model call. The background result updates the same reply if it is still present and unchanged. A failed call leaves the fallback in place.
- Recall builds corpus chunks outside the workspace file lock and reuses them by source revision. The regression test holds a cold chunk build open while an unrelated workspace write acquires the lock and completes within 250 ms.
- Attachment extraction and audio transcription use a bounded, in-memory SHA-256 cache. Revisions refresh the content digest and forget clears the cache. Image follow-ups reuse the prepared image, and a different question still gets a question-specific vision call.
- Parent chat and workers share the 12,000-character preview cap for individual results. Parent chat also budgets 128,000 characters of ASCII-safe serialized messages and tool definitions before provider formatting. When the budget fills, larger results lose their previews first, with older results first at equal sizes. Truncation preserves tool-call IDs and untrusted markers.

## Live verification

The same SSE client exercised the exact pre-D12 and deployed post-D12 runtime on the Sprite, using temporary workspaces and live Hugging Face and Exa connectors. Times are milliseconds from POST to first `token` and to `done`. Each side trial used a fresh thread and the same arithmetic prompt.

| Scenario | Before first token | Before done | After first token | After done |
| --- | ---: | ---: | ---: | ---: |
| Side reply, trial 1 | 651 | 1,210 | 529 | 532 |
| Side reply, trial 2 | 628 | 1,236 | 1,069 | 1,071 |
| Side reply, trial 3 | 731 | 1,770 | 591 | 593 |
| Attachment opening | 1,828 | 1,939 | 1,879 | 1,900 |
| Attachment follow-up | 1,768 | 1,800 | 1,557 | 1,625 |
| Exa tool reply | 10,373 | 10,375 | 5,887 | 5,890 |

Median side-reply latency to `done` fell from 1,236 ms to 593 ms. The median interval from first token to `done` fell from 608 ms to 2 ms while the three post-D12 summary model calls each took 644–1,528 ms. Attachment and Exa timings are single live observations and include provider latency.

`scripts/deploy.sh` succeeded. At 09:01 UTC on November 26, 2026, the deployed `/health` returned HTTP 200 with Sprite checkpoints enabled. The runtime source hashes matched the local files. Live smoke verified a persisted arithmetic reply, an attachment follow-up that recovered and cited the uploaded fixture, and a tool reply with live Exa results and a NASA citation.
