# Run 94 · Lazy-loaded workspace views

Run 94 reverted the modulepreload experiment because mobile Home became slower and First Contentful Paint (FCP) got worse across both profiles. Home and the workspace shell use static imports. Other workspaces load on navigation and keep their controller for subsequent visits. An idle callback caches the Chat module after Home is ready. Chat search and the mobile drawer stay available in the shell. Hearth serves native ES modules under the existing CSP and import map. [Run 93](run-93.md)

## Findings

- Cold Home started 29 JavaScript requests before it was ready on desktop and mobile, down from 61 on the Preact baseline. Those requests transferred 233,057 bytes, down 64.0% from 648,020 bytes. Eleven more JavaScript resources arrived during the idle Chat prefetch, bringing both profiles to 40 requests and 364,471 bytes in the Run 93 observation window. The HTTP-cached warm loads had zero JavaScript transfers on all three revisions.
- Cold Home ready improved from 457.9 to 287.6 ms on desktop (37.2%) and from 979.9 to 738.1 ms on mobile (24.7%). The baseline and lazy Home-ready ranges overlapped on desktop (394.5–835.8 and 257.6–460.6 ms) and mobile (965.7–1,089.5 and 650.8–1,022.7 ms). Cold LCP improved by 156 ms on desktop and 252 ms on mobile. Desktop median FCP matched the Preact baseline in all three load scenarios. Mobile cold FCP rose from 196 to 208 ms, and both warm FCP medians fell.
- With idle prefetch held, first Chat navigation took 300.1 ms on desktop, up from 271.5 ms, and 360.7 ms on mobile, down from 404.9 ms. The Chat workspace request began 0.6–0.7 ms after the desktop click and 2.5–3.1 ms after the mobile click. Opening the seeded thread after Chat loaded took 243.3 ms on desktop and 612.1 ms on mobile. Vanilla opened the same thread in 76.2 and 267.8 ms.

## Method

- The clean checkouts were vanilla `f58a3fe`, the Preact baseline `4b93c21`, and the lazy Preact implementation at `3bb31d7`. The Preact pair measures Run 94 against the pre-modulepreload baseline. The vanilla comparison also includes the application changes between vanilla and Preact.
- The worker reused the Run 93 load harness with natural idle scheduling and a seeded, offline loopback Python server. Cold disabled HTTP caching. Native warm repeated navigation with the app’s `no-store` policy. HTTP-cached warm enabled a one-hour lifetime for JavaScript responses, primed the cache, and measured another navigation. The three revisions ran sequentially in two blocks per profile with reversed order. Each revision and profile had five independently seeded samples.
- Headless Chromium 159.0.8154.6 and Playwright 1.65.2 used a 1440 × 900 desktop viewport at 1× CPU and a 390 × 844 mobile touch viewport at 4× CDP CPU throttling, both at DPR 1, on the same two-vCPU Linux ARM64 host. The harness required three consecutive one-second intervals below 40% of one core in external CPU and at least 768 MiB available RAM. It discarded samples if an interval reached 50% or available RAM fell below 768 MiB.
- Home ready is the first animation-frame callback after the loading indicator clears and all nine fixture panels exist. The Run 93 measurement window ends 350 ms after the Home ready, FCP, and LCP checks. JS requests count JavaScript Resource Timing entries with a nonzero transfer size, and transfer includes the estimated response headers. That window can include idle Chat prefetch. The startup-only counts use requests that start before the Home-ready mark.
- The Run 92 navigation and thread-open steps ran in a separate fresh context with the HTTP cache disabled. The harness held the idle callback for all three revisions in this context and checked that the lazy Chat module request started after the navigation click. The timer starts at the nav button click, after opening the drawer on mobile, and ends when the view, expected content, fetch, and finite animations have settled. Thread open starts at the saved thread’s button click and ends once the newest 50 messages of its 500-message transcript are rendered and settled. Other workspace navigation pairs are available in the raw samples.
- The browser and server communicated over loopback without added latency. CPU throttling approximates a slower renderer. Five local samples per cell show direction and variance under these conditions.

The harness, 30 accepted samples, host audits, and logs are in `/workspace/tmp/hearth-qa/run94/`. The monitor rejected eight attempts for host contention.

## Medians

Each cell summarizes five accepted samples. LCP is Largest Contentful Paint.

### Desktop Home loads

| Scenario | Revision | Home ready (ms) | LCP (ms) | FCP (ms) | JS requests | JS transfer (B) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Cold | `f58a3fe` | 328.0 | 356.0 | 176.0 | 32 | 549,048 |
| Cold | `4b93c21` | 457.9 | 484.0 | 116.0 | 61 | 648,020 |
| Cold | `3bb31d7` | 287.6 | 328.0 | 116.0 | 40 | 364,471 |
| Native warm | `f58a3fe` | 277.5 | 304.0 | 124.0 | 32 | 549,048 |
| Native warm | `4b93c21` | 399.5 | 424.0 | 108.0 | 61 | 648,020 |
| Native warm | `3bb31d7` | 241.8 | 264.0 | 108.0 | 40 | 364,471 |
| HTTP-cached warm | `f58a3fe` | 162.7 | 184.0 | 144.0 | 0 | 0 |
| HTTP-cached warm | `4b93c21` | 216.5 | 240.0 | 128.0 | 0 | 0 |
| HTTP-cached warm | `3bb31d7` | 154.1 | 188.0 | 128.0 | 0 | 0 |

### Mobile Home loads

| Scenario | Revision | Home ready (ms) | LCP (ms) | FCP (ms) | JS requests | JS transfer (B) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Cold | `f58a3fe` | 812.2 | 1068.0 | 244.0 | 32 | 549,048 |
| Cold | `4b93c21` | 979.9 | 1240.0 | 196.0 | 61 | 648,020 |
| Cold | `3bb31d7` | 738.1 | 988.0 | 208.0 | 40 | 364,471 |
| Native warm | `f58a3fe` | 555.2 | 820.0 | 180.0 | 32 | 549,048 |
| Native warm | `4b93c21` | 797.3 | 1064.0 | 180.0 | 61 | 648,020 |
| Native warm | `3bb31d7` | 543.2 | 792.0 | 160.0 | 40 | 364,471 |
| HTTP-cached warm | `f58a3fe` | 436.4 | 692.0 | 196.0 | 0 | 0 |
| HTTP-cached warm | `4b93c21` | 603.5 | 872.0 | 176.0 | 0 | 0 |
| HTTP-cached warm | `3bb31d7` | 367.1 | 624.0 | 172.0 | 0 | 0 |

### Cold Home → Chat and saved thread open

| Profile | Revision | First Chat navigation (ms) | Open 500-message thread (ms) |
| --- | --- | ---: | ---: |
| Desktop | `f58a3fe` | 288.3 | 76.2 |
| Desktop | `4b93c21` | 271.5 | 243.0 |
| Desktop | `3bb31d7` | 300.1 | 243.3 |
| Mobile | `f58a3fe` | 385.6 | 267.8 |
| Mobile | `4b93c21` | 404.9 | 676.8 |
| Mobile | `3bb31d7` | 360.7 | 612.1 |

## Verification

- Chromium passed default smoke, stream disconnect, Chat search, list search, motion, and Feed Ideas. The cold-load regression holds the idle callback, checks the request log at Home ready, then releases the callback and checks that only the Chat graph loads. It also covers a delayed Timeline import, navigation away while the import is pending, reuse on a second visit, CSP, and the direct `/chat` entry.
- Additional Chromium checks opened Automations and Voice from direct links, switched between Reminders and Recurring tasks, and loaded the mobile drawer’s threads before opening Chat.
- Python passed all 343 tests with `HEARTH_CJK_FONT` on a rerun with temporary test data in tmpfs after the initial run timed out on scheduler subprocesses. The email approval regression uses the fixture clock for both explicit and automatic approval. The other fixed 2026 dates either use injected clocks where expiry applies or serve as historical fixture data.
- Node passed all 37 tests. `node --check` passed for all 69 frontend JavaScript files.
