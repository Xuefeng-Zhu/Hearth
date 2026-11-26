# Run 51 · Chat and Home polling

D06 is complete on `d06-polling`.

## Benchmark

Run `python scripts/bench_state.py` with Hearth's Python dependencies installed. The script creates a temporary workspace with 200 chats, 500 Main messages, 16 messages per side chat, 1,200 actions, and 400 reminder jobs. It uses the Mock brain and an offline gateway. Both measurements used this same fixture and the loopback HTTP server. The baseline was commit `3e5f446`.

First requests are single samples. The other rows are medians over 20 requests. Server time covers the GET handler. Lock time is the time that handler held the workspace state lock, excluding time spent waiting for it. Payload sizes exclude HTTP headers.

| Request | Before status | After status | Before bytes | After bytes | Before server ms | After server ms | Before locked ms | After locked ms |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| State, first GET | 200 | 200 | 1,601,602 | 118,711 | 125.783 | 18.908 | 115.352 | 17.373 |
| State, regular GET | 200 | 200 | 1,601,602 | 118,711 | 112.447 | 0.715 | 102.481 | 0.000 |
| State, unchanged conditional GET | 304 | 304 | 0 | 0 | 125.402 | 0.136 | 114.496 | 0.000 |
| Home, first GET | 200 | 200 | 2,593 | 2,615 | 1,554.215 | 36.394 | 801.533 | 3.358 |
| Home, regular GET | 200 | 200 | 2,593 | 2,615 | 1,522.368 | 0.261 | 773.169 | 0.000 |
| Home, unchanged conditional GET | — | 304 | — | 0 | — | 0.189 | — | 0.000 |

State's response body fell by 92.6%. Both unchanged paths skip storage locking, snapshot construction, and JSON serialization.

## Behavior

- State and Home validators use a persistent workspace counter advanced under the storage lock. Filesystem fingerprints also cover checkpoint restores and out-of-band replacements. State accounts for live turn activity and connector capabilities. Approval deadlines invalidate the cache independently of writes.
- State returns up to 100 sidebar entries plus the selected chat if needed. The browser loads additional metadata pages so older chats remain selectable. The selected chat starts with 50 messages. Scrolling up loads older pages without shifting the visible message. Each page carries its linked cards, worker information, and attachment metadata.
- Home builds its five Activity previews and today's event and error counts from recent storage records. It reuses unchanged thread projections between writes and caches the snapshot by revision. The first build reads a recent slice of each thread. It also caches the checkpoint listing separately. The benchmark used local checkpoints and mocked connectors.
- The foreground refresh timer runs every three seconds during active chat, worker, or approval work and every 12 seconds while idle. It pauses in hidden tabs and resumes on visibility or focus. Home's existing panel refresh also uses the conditional GET path.

## Verification

- `python -m unittest discover -s tests` passed all 248 tests with the repository's Chinese PDF font configured. New coverage checks cross-instance write invalidation, the lock-free 304 path, approval expiry without a write, cursor stability, legacy transcripts, sidebar overflow, attachment references across page boundaries, and Home parity with Timeline.
- `node --test tests/*.test.mjs` passed all nine tests. `node --check` passed for every JavaScript file in `web/`.
- Playwright exercised mobile WebKit at 390×844 and desktop Chromium at 1280×800. Both loaded older chat pages and kept the scroll anchor. Desktop also verified idle and active polling, hidden-tab pause, immediate focus refresh, sidebar overflow, live streaming and Stop, and a Home 304. The existing desktop WebKit regression also passed its chat, worker, attachment, and workspace checks.
