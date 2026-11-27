# Benchmark: vanilla JS vs Preact frontend

Vanilla is `backup/pre-preact` (`f58a3fe`). Preact is `e171bf3`. The comparison spans every change between those commits, so it compares the shipped frontends as a whole.

## Results (median)

Desktop is 1440 × 900 at 1× CPU. Mobile is 390 × 844 with 4× CDP CPU throttling.

| Metric | Desktop vanilla → Preact | Mobile vanilla → Preact | Verdict |
| --- | --- | --- | --- |
| Streaming total blocking time | 2665 → 13 ms | 24389 → 713 ms | Preact much better |
| Per-token update latency | 122 → 3 ms | 12.2 s → 14 ms | Preact much better |
| Cold load to Home ready | 333 → 458 ms | 883 → 1463 ms | Preact slower |
| LCP (cold) | 368 → 484 ms | 1146 → 1720 ms | Preact slower |
| JS requests (cold) | 32 → 61 | 32 → 61 | About twice as many |
| JS transfer (cold) | 549,048 → 647,994 B | same | +18% |
| Open a 500-message thread | 175 → 242 ms | 313 → 831 ms | Preact slower |
| View switch (mean of 9 views) | 290 → 275 ms | 482 → 483 ms | Even |
| Cmd+K search, list search, drag reorder, Feed refresh | about the same | about the same or slightly faster | Even |
| JS heap after 5 navigation loops | 4.3 → 7.6 MB | 4.7 → 7.9 MB | About 3 MB more |

## Why (inferred from the code, not profiled)

- **Streaming:** vanilla wrote each token with `textContent` and then read `scrollHeight` to follow the bottom. With 500 messages rendered, that forced a synchronous layout per token. Preact updates the bubble through component state and batches renders, so 300 tokens produced 290 DOM changes with few forced layouts.
- **Load:** the migration split one `app.js` into about 60 native modules. The browser discovers them through the import chain, so requests form a waterfall.
- **Chat open and heap:** building 50 message components through the virtual DOM and hooks costs more than direct DOM writes, and the component tree and state stay in memory. Throttled CPU magnifies both.

## Method and limits

- Each checkout ran its real loopback Python server on the same offline fixture (fictional data, mock model output, no provider or production calls). Headless Chromium 159.0.8154.6, Playwright 1.65.2, Linux ARM64, 2 vCPUs, 7.8 GiB RAM. Cold loads disabled the HTTP cache.
- **5 samples per build and profile** (vanilla mobile had 6). The run planned 10, but hit its 90-minute limit because host `sqlite3` activity forced many samples to be discarded and retried. The medians show direction; treat small differences as noise.
- No network latency was injected. Real networks would likely widen the request-count gap. Physical phones and other browser engines were not tested.
- Raw samples and the harness were kept in the build workspace, not in the repo.

## Follow-ups

- Run 93 added `modulepreload` for the whole static graph. Desktop cold Home ready improved 11.6%, but mobile got slower (native warm +24.5%, HTTP-cached warm +38.6%) and FCP rose in all six scenarios, so it was reverted. See [Run 93](run-93.md).
- Run 94 loads views other than Home on first navigation and prefetches Chat when idle. Cold Home JS requests fell from 61 to 40 (29 before Home is ready), transfer from 648,020 to 364,471 bytes, and cold Home ready from 457.9 to 287.6 ms on desktop and 979.9 to 738.1 ms on mobile, now faster than vanilla (328.0 and 812.2 ms in the same run). Opening the 500-message thread is still slower than vanilla (243 vs 76 ms desktop, 612 vs 268 ms mobile). See [Run 94](run-94.md).
