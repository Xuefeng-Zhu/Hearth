# Hearth QA

## Run 38

- **Mobile drawer.** Playwright WebKit 27.2 passed at 375×667 and 390×844 in light and dark. From a fresh Home load with 12 seeded side chats, all seven navigation links fit before scrolling. Thread titles ellipsized, the drawer had no horizontal overflow, and Settings stayed pinned while the list scrolled to the last chat.
- **Settings.** The same 12 grouped disclosures passed at both phone sizes and at 1440×1000 in both themes. The fixture opened and closed each section with the keyboard and exercised the legacy Connections and Skills links and the mobile Ember view control.
- **Regression and contrast.** 195 Python tests and 8 Node tests passed. The Chromium browser regressions passed, and the sampled WCAG AA contrast sweep found zero failures in 16,956 measurements. [Development commands](docs/development.md)
- **Sprite.** `scripts/deploy.sh` completed and `/health` returned HTTP 200 with Sprite checkpoints. The deployed HTML, CSS, and JavaScript checked against the local release matched. On the deployed service, WebKit rendered Settings, Connections, and Skills at 390 and 1440 px in both themes.

Fixture screenshots are in `/workspace/tmp/hearth-qa/run38/`. The README images of Connections, Skills, and the mobile drawer use the same synthetic workspace. [Screenshots](README.md#screenshots)

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

### 90-second demo

Use a test workspace with a connected brain and Exa. Stage a For you offer, English and Chinese notes, a skill run, a pending skill proposal, a completed worker comparison, a workbook, and a private Page. Keep reminder delivery in-app and leave any demo send unapproved.

| Time | Action |
| --- | --- |
| 0–12 s | Open **Home → For you**. Read the reason for one offer, then choose **Do it** and show the side chat. |
| 12–28 s | Open **Memory → Topics**. Search for the Chinese phrase in the staged note, open its source, then point out the English note beside it. |
| 28–43 s | Open **Skills** and point out **Try it** on **Weekly family brief**. Switch to the staged chat to show **Using skill**, then open the pending skill approval and unfold the proposed Markdown. |
| 43–62 s | Open the worker comparison. Expand a worker’s Exa step, point out the separate worker timings, and show the combined answer and its sources. |
| 62–78 s | Open **Artifacts**, preview the workbook, then open the private Page and switch from **Phone** to **Desktop**. |
| 78–90 s | Open **Reminders → Recurring tasks → Morning brief** and show its run history. Finish on **Timeline** with the worker and approval activity. |

For the local Mock walkthrough, select **Plan Thanksgiving dinner** in Chat to show cited memory, an invitation approval, a PDF, and an Excel shopping list. [Skills](docs/skills.md), [Proactivity](docs/proactivity.md), [Approvals and tasks](docs/approvals-and-tasks.md)
