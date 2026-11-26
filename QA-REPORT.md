# Hearth QA

## Round 5

Run 65, November 26, 2026 UTC. The deployed Sprite runtime matched the `925150b` checkout by SHA-256 across all 131 shipped files. The docs pass landed in that commit and the deployment bundle contains runtime files only. The round covered the integrated D02–D17 changes at the scope recorded in the [design review](DESIGN-REVIEW.md#run-63-status).

The page matrix used the live workspace through an authenticated Sprites CLI HTTP relay after the TCP tunnel reset. The relay served verified static assets and forwarded API reads to the running service. It blocked the Inbox poll POST, which caused one expected 405 per profile. Stateful browser checks used a disposable fictional workspace on the same Sprite, running the deployed code with live Hugging Face and Exa, mocked Box and Pinecone, and no mail connection. Playwright Chromium supplied the browser and touch-emulated mobile profiles because the Browser plugin was unavailable. The WebKit build could not start with the available system libraries.

### Page matrix

Each result covers light and dark, loaded page content, and horizontal overflow in the document and sampled app panes.

| Page | 375 × 667 | 390 × 844 | 1440 × 1000 |
| --- | --- | --- | --- |
| Home | Pass | Pass | Pass |
| Chat | Pass | Pass | Pass |
| Timeline | Pass | Pass | Pass |
| Artifacts | Pass | Pass | Pass |
| Reminders | Pass | Pass | Pass |
| Inbox | Pass | Pass | Pass |
| Memory | Pass | Pass | Pass |
| Skills | Pass | Pass | Pass |
| Settings | Pass | Pass | Pass |

### Results

| Check | Result | Evidence |
| --- | --- | --- |
| Horizontal overflow | Pass | Zero overflowing documents or sampled panes across the 54 production page combinations and four mobile drawer combinations. |
| Sampled WCAG AA contrast | Pass | Zero failures in 30,928 production samples and 5,621 fictional-workspace samples, including normal text at 4.5:1 and large text and sampled control indicators at 3:1. |
| Mobile touch targets | Pass | All 4,040 production and 876 fictional-workspace measurements met 44 × 44 CSS px. The sample covered enabled controls, drawer controls and checkable labels. Inline prose links were excluded. Stop also measured 44 × 44 px during a reply. |
| Keyboard Send and Stop | Pass | Both buttons showed visible Tab focus and accepted Enter. Focus returned to the composer after Send and Stop. Stop returned a successful receipt and the transcript showed **Reply stopped.** |
| Keyboard thread switch | Pass | Tab reached the side chat, Enter opened it, and focus remained visible on the selected thread control. |
| Live-region announcement | Pass | The polite live region updated exactly once after a completed reply and stayed unchanged after a refresh. Verified through DOM mutations. Actual screen-reader speech was outside the sample. |
| Chat reply | Pass | The live model returned 75 for 47 + 28 and one finished reply persisted in the test thread. |
| Exa sourced reply | Pass | The live Exa search received a pathlib query. The finished answer linked to the official Python documentation. |
| Worker task | Pass | The delegated packing calculation reached **Done**, persisted its result, and the parent reply reported 18 labels. |
| Always ask approval | Pass | Settings displayed **Always ask** for goal creation. The requested goal displayed **Needs approval** and the decline returned `declined`. |
| Reminder create and cancel | Pass | Scheduled an in-app reminder for two days later. **Undo** canceled it, the UI confirmed cancellation, and the saved job reached `canceled`. Zero real emails sent. |
| Quiet hours | Pass | Production reminder settings returned **22:00–07:00 PT** (`America/Los_Angeles`). |
| Ask my files | Pass | Selected one mocked Box DOCX. The answer identified the blue gate, 4:15 p.m., and seven lanterns, with one citation to that file. |
| Memory recall | Pass | The live model recalled the fictional orchard gate’s periwinkle color in a side chat. The saved reply referenced the fixture note. |
| Artifacts listing freshness | Pass | The production listing went from `refreshing` to `fresh` with 21 rows and no Box error. A controlled refresh on the fixture kept the old row visible while loading, then showed the new file and an advanced refresh timestamp. |
| Home stale indicator | Pass | Two injected HTTP 500 responses on the live Home page showed **Stale · Server error** while keeping existing cards visible. A live 304 cleared the indicator. The fixture also recovered on 200. |
| Paged transcript load-older | Pass | The side chat initially rendered 50 of 90 entries. Scrolling to the top fetched an older page with HTTP 200 and rendered all 90 entries. |
| Unchanged polls | Pass | Production `/api/state` and `/api/home` each returned 200 with an ETag, then 304 with the same ETag and an empty body. |
| Signed-out edge | Pass | Cookie-free GETs to `/`, `/api/state`, and `/health` each returned 302 with a Location header. Redirects stayed unfollowed. |
| Deployment health | Pass | The running Sprite returned `/health` 200 with Sprite checkpoints before testing and after cleanup. |
| Regression suite | Pass | 315 Python tests, 16 Node tests, syntax checks for 27 web JavaScript files, and both offline Chromium smoke runs passed. |

### Defects and cleanup

- Zero product regressions reproduced. The existing deployment remained in service, so the round needed no corrective deploy.
- Larger follow-ups already recorded in the design review include D02 provenance and connector scopes, D04 off-Sprite delivery recovery, D05 multi-file consistency, D11 credential lifetime and retention, and D15 rollback. [Design review](DESIGN-REVIEW.md#run-63-status)
- The disposable Hearth workspace and its test data were removed, and its server was stopped. The relay forwarded zero production workspace write requests. Box operations were read-only throughout the round.

### Screenshots

The 65 images include the full fictional page matrix, four mobile drawer states, and seven functional states. Captures use the app viewport with fictional data, and an OCR check found no private Sprite or relay origin. [Round 5 screenshots](docs/screenshots/qa5/)

| Evidence | Image |
| --- | --- |
| 375 px light and 390 px dark | [Home at 375 px](docs/screenshots/qa5/home-375-light.png), [drawer at 390 px](docs/screenshots/qa5/drawer-390-dark.png) |
| Live model reply, worker and approval | [Reply](docs/screenshots/qa5/chat-reply-1440-light.png), [worker](docs/screenshots/qa5/chat-worker-1440-light.png), [approval](docs/screenshots/qa5/chat-approval-1440-light.png) |
| Reminder and file answer | [Scheduled reminder](docs/screenshots/qa5/reminder-scheduled-390-dark.png), [Ask my files](docs/screenshots/qa5/ask-my-files-390-dark.png) |
| Background refresh | [Home stale](docs/screenshots/qa5/home-stale-390-dark.png), [Artifacts refreshing](docs/screenshots/qa5/artifacts-refresh-390-dark.png) |

## Run 48

Run 48 covered rolling chat summaries, Feed and Ideas, nightly Memory review, event automations, Ask my files, Goals, and the Apify watcher status. The Sprite production checks used the deployed service, and write tests ran in a disposable fictional workspace on the same Sprite. Playwright WebKit and Chromium ran locally because the Browser plugin was unavailable.

### Results

| Check | Result |
| --- | --- |
| Unit tests and syntax | 239 Python tests and nine Node tests passed. Every `web/*.js` file passed `node --check`. |
| Browser regression | The fixtures passed navigation, Home layout, Pages, Skills, workers, structured Memory, Feed, Memory review, event automations, Ask my files, Ideas, and Goals. They exercised disconnected, loading, error, retry, and empty states. |
| Browser matrix | All nine navigation pages and the new panels passed in WebKit at 375×667, 390×844, and 1440×1000 in light and dark. The fictional workspace sweep checked pane overflow, 44 px touch targets, and drawer and Settings scrolling. |
| Sampled WCAG AA contrast | Zero failures in 34,478 local WebKit samples, 17,589 local Chromium samples, and 15,750 samples in the fictional Sprite browser matrix. |
| Deployment | `scripts/deploy.sh` completed and the production `/health` returned HTTP 200 with Sprite checkpoints. All 42 served assets matched the checkout by SHA-256. |
| Feed and Ideas | The Feed steering prompt reached the fixture model, and Refresh, Like, Saved, and Less like this updated the UI. An Idea’s one-tap reminder stayed pending until approval. |
| Memory review | **Run now** used the connected brain and returned three proposals from fictional notes. No review decisions were applied. |
| Event automations | Chat created a pending rule. Confirm enabled it, a reminder fired it, and the run created an in-app reminder and Feed card. Timeline Undo canceled the reminder and removed the card. Approved deletion removed the rule from Settings. |
| Workers | A worker’s fictional skill waited for Inbox approval. After approval, the skill appeared once, the worker completed, and Chat returned one consolidated reply. |
| Ask my files | Real Box reads, existing Pinecone file vectors, and the connected brain returned the fictional lighthouse tour’s 4:15 p.m. Saturday start, blue-gate meeting point, and seven lanterns, with two matching Box citations. |
| Goals and summaries | Goal creation and deletion waited for approval. Timeline Undo restored progress after a check-in. A connected brain folded a long side chat, and a later turn recovered a fact from the opening message. |

The authenticated Sprite TCP proxy reset connections in this environment. Browser checks used a loopback HTTP relay via `sprite exec` and locally served copies of the verified release assets. The relay buffered Chat responses. Production streaming latency was outside the live check. The 126 screenshots use fictional data. See `/workspace/tmp/hearth-qa/run48/screenshots/` and `/workspace/tmp/hearth-qa/run48/live-check.txt`.

The disposable Sprite workspace was removed after verification. Both existing production Memory review proposals remained pending. Box access was read-only. Browserbase sessions, Apify Actor runs, and email sends each totaled zero.

### Fixes

- Added **Settings → Watchers** with the Apify blocker and directions to manage approved public-page watchers.
- Moved file-answer attribution from the empty Ask my files form to the result returned by Hearth.
- Increased contrast on the Ask my files question and file-search fields. Enlarged the **Open Connections** link in an unconnected Inbox to a 44 px mobile target.
- Fixed the misleading **Interrupted** label on successful Timeline approval decisions, including existing history. Execution outcomes remain on their own entries.
- Updated browser regression fixtures for the current navigation, Home layout, Feed cards, and Settings disclosures.

### Known issues

- The Apify gateway passed Actor listing during the Run 45 probe. Account, usage, Actor-run, and dataset reads returned HTTP 403. Hearth’s page and price watchers use its public-page reader. [Apify probe](docs/watchers.md)
- The Box gateway returned HTTP 403 for Box AI single-file and multi-file questions and structured extraction in Run 46. Ask my files uses Hearth file extraction, Pinecone, and a connected brain. Structured Inbox receipt and bill extraction through Box AI remains unavailable. [Box probe](docs/box.md)

### 90-second demo

Use a fictional workspace. Stage a Feed card, an Idea for an in-app reminder, a Memory review digest, a Goal with a check-in, an automation run, and two synced Box artifacts. Prepare the file answer in advance so provider latency does not consume the demo.

| Time | Action |
| --- | --- |
| 0–18 s | Open **Home → Feed**. Show the steering prompt and use **Like** on a seed library card. Tap **Review reminder** on an Idea and show its pending approval. |
| 18–32 s | Open **Goals**, show the seed library progress, then open the check-in entry in **Timeline** and show **Undo**. |
| 32–48 s | Open **Memory → Review** and compare two fictional excerpts. Show **Run now** and the nightly schedule under **Settings → Memory**. |
| 48–66 s | Show the staged automation approval in Chat. Open its completed reminder-triggered run in **Settings → Automations** and show its reversible effects in Timeline. |
| 66–84 s | Switch to a tab with the prepared **Artifacts → Ask my files** result for the fictional lighthouse tour and point out both **Open in Box** citations. |
| 84–90 s | Open **Settings → Watchers** and show the Apify blocker and directions to public-page watchers. |

## Run 39

See the [UI/UX audit](UX-AUDIT.md) for findings, screenshot pairs, and verification.

## Run 38

- **Mobile drawer.** Playwright WebKit 27.2 passed at 375×667 and 390×844 in light and dark. From a fresh Home load with 12 seeded side chats, all seven navigation links fit before scrolling. Thread titles ellipsized, the drawer had no horizontal overflow, and Settings stayed pinned while the list scrolled to the last chat.
- **Settings.** The same 12 grouped disclosures passed at both phone sizes and at 1440×1000 in both themes. The fixture opened and closed each section with the keyboard and exercised the legacy Connections and Skills links and the mobile Ember view control.
- **Regression and contrast.** 195 Python tests and 8 Node tests passed. The Chromium browser regressions passed, and the sampled WCAG AA contrast sweep found zero failures in 16,956 measurements. [Development commands](docs/development.md)
- **Sprite.** `scripts/deploy.sh` completed and `/health` returned HTTP 200 with Sprite checkpoints. The deployed HTML, CSS, and JavaScript checked against the local release matched. On the deployed service, WebKit rendered Settings, Connections, and Skills at 390 and 1440 px in both themes.

Fixture screenshots are in `/workspace/tmp/hearth-qa/run38/`. That run used fictional workspace data. [Screenshots](README.md#screenshots)

## Run 34

Run 34 covered the Sprite build after Skills, parallel workers, structured Memory, and Proactivity shipped. Verification ran on November 26, 2026 UTC. The standard deployment passed `/health` with Sprite checkpoints. Write tests used synthetic data in an isolated workspace on the same Sprite, running the deployed release with the real Hugging Face, Exa, and Box connectors. The isolated workspace used local checkpoints and a separate Box QA folder.

### Results

| Check | Result |
| --- | --- |
| Python and Node | 192 Python tests and 8 Node tests passed. App and vendor JavaScript, Node test modules, and deployment shell scripts passed syntax checks. |
| Browser regression and contrast | Seven Chromium fixtures passed at 390 and 1440 px in light and dark. The final broad contrast sweep took 12,020 measurements with zero sampled failures. Separate Skills, Workers, Memory, and For you fixtures also checked text contrast. |
| Live navigation | Home and For you, Chat, Timeline, Artifacts and Pages, Reminders and Recurring tasks, Inbox, Connections tabs, all five Memory tabs, Skills, and Settings passed on the deployed service at both widths and in both themes. The sweep checked page titles, rendered content, JavaScript exceptions, HTTP errors, and horizontal overflow. |
| Skills and approvals | A chat loaded Weekly family brief and recorded its use. A separate chat proposed a new skill, which appeared in the library after approval. Recurring task setup stayed pending until Confirm. |
| Parallel workers | Three live workers each used Exa once and returned one combined reply with source links. Their starts were 61 ms apart, and they overlapped for 7.85 seconds. In a second chat, Stop cancelled a worker waiting for approval and withdrew its pending send. |
| Structured Memory | Chat saved English and Chinese notes and recalled both in a new chat. Local search found a Chinese phrase inside a longer sentence. A permanent forget request removed the English detail, blocked resaving it, and preserved the unrelated Chinese note. |
| Proactivity | A live Hugging Face pass published three offers. Snooze and Dismiss removed their cards, and Do it opened a side chat that completed. Permanent forget retired the remaining cached offers. A separate live planner diagnostic found the detail absent from both the source collection and the fresh offers. The fixture suite also checked approval policy for proactive handoffs and removal of offers tied to a deleted skill. |
| Recurring tasks | Confirm and Run now completed a weekday reminder task. The production Sprite listed one Morning brief, and a live QA run of that task included the current For you offer. |
| Artifacts and Box | Chat generated and downloaded one DOCX, PDF, XLSX, PPTX, and private HTML Page. Chromium rendered all five previews, and the workbook contained a SUM formula. A synthetic PDF synced to Box and showed an Open in Box link. |
| Voice | Chromium recorded from a synthetic microphone at 390 px, uploaded the WebM to connected Whisper, and filled the chat composer with the transcript. |
| Connections | Browserbase passed the read-only connection test and showed OK on live Home. Box and Exa passed their connector checks. Apify discovery succeeded, and its provider test returned denied. |

Local Chromium reached the deployed service through the authenticated Sprites CLI. Run 34 opened zero Browserbase sessions. Live captures and QA logs are in `/workspace/tmp/hearth-qa/run34/`. The README Home image shows a fresh workspace on the deployed Sprite with Browserbase connected. [Development commands](docs/development.md), [Connector setup](docs/connectors.md), [Screenshots](README.md#screenshots)

### Fixes verified after redeploy

- Raised the dark-mode border contrast of Memory tabs and note buttons. The broad sweep found five failing control styles before the fix and zero afterward.
- Matched Chinese phrases inside saved notes by applying the same tokenization to local queries and indexed text. English and Chinese recall both passed on the deployed release.
- Hid proactive offers that point to a deleted skill. The regression covers both the Home list and the handoff endpoint.
- Accepted “permanently forget” as a direct forget request in chat. The regression checks removal and blocks saving the matching detail again.

### Known issues and limits

- Sprite discovery found Apify, and its provider check was denied. Connections and Home reported the failure.
- Two follow-up scheduler calls returned `brain-unavailable`. The separate planner diagnostic completed against the connected brain using the same workspace after forget.
- Box version history uses locally recorded receipts when the gateway’s versions GET is unavailable. The synthetic PDF remains in the dedicated QA folder after verification of its upload and synced link.
- Native Sprite restore, delivery to a real email recipient, anonymous Page publishing, an external scheduler wake, and physical-device Safari were outside Run 34. Local fixtures exercised the corresponding app flows where available. [Deployment](docs/deploy.md), [Voice](docs/voice.md)
