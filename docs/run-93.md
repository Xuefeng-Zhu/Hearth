# Run 93 · Preact modulepreload

The startup document now preloads 61 same-origin ES modules, including the `/app.js` entry, Preact, hooks, and htm. The inline import map appears before the links and retains its existing CSP hash. The generated list follows static imports and re-exports. The VocalBridge SDK still loads on demand. Hearth still serves native ES modules directly. [Startup document](../web/index.html)

After changing the module graph, run `python scripts/gen_modulepreload.py` with Node 22 available. The Python test suite checks that the block matches the graph. [Generator](../scripts/gen_modulepreload.py) · [Test](../tests/test_modulepreload.py)

## Findings

- Preloading narrowed the median cold interval between the first and last JavaScript resource start from 288.1 to 12.9 ms on desktop and from 427.0 to 59.7 ms on mobile. Both Preact revisions transferred 61 JavaScript resources and 648,020 JavaScript bytes on cold and native-warm loads. The preload links and block markers added 3,355 bytes to the HTML.
- Cold desktop Home ready fell from 495.8 to 438.5 ms (−11.6%) and LCP fell from 524 to 472 ms (−9.9%). Median Home ready was 1.3% slower on native warm and 2.9% faster on HTTP-cached warm. Cold Home ready ranged from 419 to 736 ms before preloading and 382 to 1,127 ms with preloading.
- Cold mobile Home ready rose from 963.3 to 986.8 ms (+2.4%) and LCP rose from 1,216 to 1,236 ms (+1.6%). Mobile Home ready rose 24.5% on native warm and 38.6% on HTTP-cached warm. The respective before and after ranges were 664–1,044 and 663–1,091 ms for native warm, and 499–986 and 516–986 ms for HTTP-cached warm. Median FCP rose in all six desktop and mobile scenarios.
- Vanilla's cold Home-ready median was still lower on both profiles. The HTTP-cached warm runs showed zero JavaScript requests with a positive transfer size on every revision. All scenarios recorded 32 JavaScript resources and 539,448 decoded bytes for vanilla, and 61 resources and 629,720 decoded bytes for both Preact revisions.

## Method

- Vanilla was `f58a3fe`, Preact before preloading was `4b93c21`, and Preact with preloading was `fb39202`. The Preact pair isolates the preload change. The vanilla comparison spans the intervening application changes. Run 92's saved Preact measurements used `e171bf3`. This run measured all three checkouts again.
- The load-only copy of Run 92's harness kept its seeded offline fixture, real loopback Python server, browser instrumentation, and host monitor. Each worker ran against a clean detached checkout. Revisions ran sequentially in two blocks per viewport with reversed revision order. Each revision had five fresh browser contexts per viewport and one sample of each scenario per context.
- Cold disabled the browser HTTP cache. Native warm re-enabled it and repeated navigation with Hearth's `Cache-Control: no-store` policy. For HTTP-cached warm, the fixture gave JavaScript responses a one-hour max-age, primed the cache, and measured another navigation.
- Headless Chromium 159.0.8154.6 with Playwright 1.65.2 used a 1440 × 900 desktop viewport at 1× CPU and a 390 × 844 touch viewport at 4× CDP CPU throttling, both at DPR 1. The Linux ARM64 host had two Neoverse-V2 vCPUs and 7.8 GiB of RAM. The harness required three consecutive one-second checks below 40% of one core in external process CPU and at least 768 MiB available RAM before a sample. It discarded samples if a one-second check during the run reached 50% CPU or available RAM fell below 768 MiB. The monitor recorded filesystem, container, and kernel reclaim activity separately, as in Run 92.
- Home ready is the first animation-frame callback after the Home loader is hidden and all nine fixture panels exist. After document load, the harness waits for Home ready, FCP, and an LCP candidate, then observes LCP for another 350 ms. JS requests count resource timing entries whose transfer size exceeds zero. Transfer includes the headers estimated by Resource Timing and covers JavaScript only.
- The browser and server communicated over loopback with no added network latency. CPU throttling approximates a slower renderer, and the HTTP-cache case uses a fixture policy. Five samples per cell show local direction and variance. Production latency, physical phones, and other browser engines can produce different results.

The raw samples, load-only harness, run order, and logs are in `/workspace/tmp/hearth-qa/run93/`. Three attempts were retried for host contention. The three detached worktrees were removed after the run.

## Medians

Each cell summarizes five accepted samples. FCP is First Contentful Paint, LCP is Largest Contentful Paint, and DCL is the end of the `DOMContentLoaded` event.

### Desktop

| Scenario | Revision | Home ready (ms) | LCP (ms) | FCP (ms) | DCL (ms) | JS requests | JS transfer (B) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Cold | `f58a3fe` | 374.0 | 408.0 | 164.0 | 319.7 | 32 | 549,048 |
| Cold | `4b93c21` | 495.8 | 524.0 | 112.0 | 394.9 | 61 | 648,020 |
| Cold | `fb39202` | 438.5 | 472.0 | 172.0 | 382.5 | 61 | 648,020 |
| Native warm | `f58a3fe` | 257.6 | 284.0 | 116.0 | 223.1 | 32 | 549,048 |
| Native warm | `4b93c21` | 377.6 | 396.0 | 112.0 | 322.0 | 61 | 648,020 |
| Native warm | `fb39202` | 382.4 | 408.0 | 160.0 | 334.8 | 61 | 648,020 |
| HTTP-cached warm | `f58a3fe` | 245.8 | 296.0 | 140.0 | 150.6 | 0 | 0 |
| HTTP-cached warm | `4b93c21` | 226.5 | 256.0 | 148.0 | 183.9 | 0 | 0 |
| HTTP-cached warm | `fb39202` | 220.0 | 252.0 | 176.0 | 166.6 | 0 | 0 |

### Mobile

| Scenario | Revision | Home ready (ms) | LCP (ms) | FCP (ms) | DCL (ms) | JS requests | JS transfer (B) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Cold | `f58a3fe` | 781.5 | 1040.0 | 228.0 | 592.8 | 32 | 549,048 |
| Cold | `4b93c21` | 963.3 | 1216.0 | 196.0 | 788.7 | 61 | 648,020 |
| Cold | `fb39202` | 986.8 | 1236.0 | 412.0 | 786.2 | 61 | 648,020 |
| Native warm | `f58a3fe` | 546.9 | 808.0 | 188.0 | 418.1 | 32 | 549,048 |
| Native warm | `4b93c21` | 758.1 | 1016.0 | 164.0 | 605.3 | 61 | 648,020 |
| Native warm | `fb39202` | 943.7 | 1208.0 | 408.0 | 748.6 | 61 | 648,020 |
| HTTP-cached warm | `f58a3fe` | 418.1 | 680.0 | 180.0 | 290.9 | 0 | 0 |
| HTTP-cached warm | `4b93c21` | 611.5 | 860.0 | 216.0 | 426.0 | 0 | 0 |
| HTTP-cached warm | `fb39202` | 847.4 | 1100.0 | 380.0 | 584.1 | 0 | 0 |

## Verification

- The Python suite with `HEARTH_CJK_FONT` passed 344 tests on the unmodified runner. `test_run_time_email_approval_and_always_allow` failed there and on `4b93c21` because its fixed November 26 fixture had crossed the approval's 24-hour expiry against the host clock. All 345 tests passed on a second run that used the fixture clock for that test's approval code. The clock override lived in the temporary runner.
- All 37 Node tests passed, and `node --check` passed for 63 frontend JavaScript files.
- Chromium passed the default smoke, stream disconnect, Chat search and list search width sweeps, motion, and Feed Ideas. A separate cold-load check verified that Chromium reached Home without console or CSP errors, fetched each preloaded URL once, and made no VocalBridge request.
- The import-map bytes matched `4b93c21`, and their SHA-256 matched the workspace CSP header. The stale-block check rejected a copy of the graph with a newly added static import.
