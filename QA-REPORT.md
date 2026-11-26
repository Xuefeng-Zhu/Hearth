# Hearth QA

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
