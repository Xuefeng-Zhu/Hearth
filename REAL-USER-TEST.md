# Run 49 · Hearth production acceptance test

November 26, 2026 UTC. I used the live private Hearth Sprite as a bilingual parent in Redmond, WA. Playwright ran WebKit with iPhone emulation at 390 × 844 in dark mode and Chromium at 1440 × 1000 in light mode. The Browser plugin was unavailable. The Sprite TCP proxy reset connections, so an authenticated loopback relay forwarded requests and streamed replies from production. Browser times include relay overhead.

## Results

| Scenario | Result | Live evidence and latency |
| --- | --- | --- |
| 1. Main chat | **Pass after fixes** | The ordinary question took **11.95 s**. Exa returned the official Redmond Lights page in **6.34 s**, but the reply applied kickoff hours to the full installation run. After the fix, a side-chat recheck in **19.71 s** distinguished the kickoff hours from the installation dates and flagged a conflicting year farther down the city page. The Chinese reply took **16.36 s** and cited the barnyard’s published hours. The rain follow-up used the farm context in Chinese in **5.50 s**. The original long reply streamed for **13.91 s** with no Stop control. After deployment, Stop interrupted a fresh long Main reply mid-stream in **4.04 s** and appeared in Timeline. [Redmond Lights](https://www.redmond.gov/1139/Redmond-Lights), [Farrel-McWhirter Park](https://www.redmond.gov/288/Farrel-McWhirter-Park) |
| 2. Memory | **Pass after fix** | Save **8.85 s**, recall in a fresh English side chat **3.35 s**, recall in a separate Chinese side chat **6.14 s**, permanent forget **2.85 s**, and a fresh no-recall reply **3.88 s**. A live review scan returned no swim-class detail. The initial forget cleared two unrelated review proposals. After restoring them and deploying the fix, a second save and forget took **10.16 s** and **4.15 s**. Both original pending proposals retained their exact IDs and contents. No review decision was made. |
| 3. Reminders and recurring tasks | **Pass** | Chat confirmed the oven reminder in **7.45 s**. App delivery reached the scheduled timestamp exactly, with zero minutes late. Quiet hours held that reminder’s email. **Send test email** returned an AgentMail send receipt for the configured reminder address in **1.34 s**. The recurring-task proposal took **9.19 s** on the confirmed attempt. It showed three upcoming Pacific run times, waited for confirmation, and disappeared after approved deletion. |
| 4. Attachments and Artifacts | **Pass after fix** | The **14.97 s** attachment reply identified the blue diamond and extracted Cedar Gate and 3:40 p.m., but invented a second PDF summary with conflicting details. The **8.85 s** redeploy recheck described the image and used the actual PDF text. Word took **13.07 s**, Excel took **12.66 s**, and both previews opened normally. **Ask my files** combined the time and gate from Word with the seven lanterns from Excel in **7.57 s**, with two Box citations. The post-deploy repeat took **12.45 s** and produced two citations and a Timeline entry. |
| 5. Side chats and parallel workers | **Pass** | Three live Exa workers returned one combined answer with three links in **22.42 s**. In a separate side chat, **Stop all workers** was pressed at **6.49 s**. The **14.18 s** final reply reported that all three stopped without findings. |
| 6. Email approvals | **Pass** | The two draft replies took **10.77 s** and **9.29 s**. Each approval card showed exactly the configured recipient. Denial returned `declined` in **1.28 s** and produced no send receipt. Approval returned `sent` in **1.60 s** and produced an AgentMail receipt. |
| 7. Email automation | **Pass** | Chat proposed the rule in **9.87 s**. It was absent before confirmation and enabled after the **1.50 s** approval. A single AgentMail message into Hearth matched the subject filter. One run completed **11.50 s** after send and another inbox check produced no duplicate run. Timeline Undo canceled the scheduled follow-up. Approved deletion removed the rule from Settings. [AgentMail send endpoint](https://docs.agentmail.to/api-reference/inboxes/messages/send) |
| 8. Feed and Ideas | **Partial** | Steering saved and was restored. Like, Dismiss and Less like this each returned HTTP 200 and updated the UI. Refresh returned the quiet-hours status in **0.96 s** with no new cards. Ideas also observed quiet hours. No eligible one-tap Idea was available, so its approval flow remains unverified on production. |
| 8. Goals | **Pass** | Created **Run 3 times a week** with approval, checked in at 33%, used Timeline Undo to return to 0%, and deleted the goal with approval. On the first attempt, the new row failed to appear during the five-second assertion window. A reload showed the saved goal, and the remainder of the flow passed. |
| 9. Timeline | **Pass for exercised actions after fixes** | Chat, Exa, memory, uploads, generated files, reminders, email approvals, automation, workers and Goals produced activity. Automation and goal Undo were verified. Feed steering, refresh and feedback, Home layout changes, Box file questions and call token mint gained entries. The final browser recheck confirmed nine audit entries, including Stop and voice transcription. |
| 10. Voice and Call | **Pass for transcription and token mint** | The desktop microphone UI recorded a 3.7 s synthesized clip. Connected Whisper filled the composer with the expected words in **3.59 s** after the recording interval. A short Call attempt obtained a Vocal Bridge token in **6.27 s**. The call closed during setup. This check covered token mint only. |
| 11. Home and accessibility | **Pass for sampled states** | Nine live panels rendered and mobile **Edit layout** removed and restored a panel. Home’s provider checks showed OK for Pinecone, AgentMail, Hugging Face, Vocal Bridge, Box, Browserbase and Exa. Across nine loaded views on each device profile, no horizontal overflow appeared. Mobile controls sampled at least 44 px, including the new 44 × 44 Stop button. The dark-mode sweep found zero WCAG AA failures in **5,099** sampled contrast pairs. |

No measured completed reply or worker summary exceeded **30 s**. No tool markup appeared in the inspected replies or the visible partial stream. The sampled action claims matched tool results, including scheduled reminders, produced artifacts, and gated email sends. Browserbase sessions, Apify Actor runs, public shares and payment prompts each totaled zero.

## Fixes and verification

- `ec5a2f9` adds Stop for replies in progress and leaves queued follow-ups intact. The regression stops a model stream and proves a queued follow-up still completes.
- `7805e1b` filters only matching Memory review proposals during permanent forget. Tests cover unrelated pending items and removal of matching evidence from live state and checkpoints.
- `b093ddc` adds Timeline records for Feed activity, layout edits, successful Box file questions and call token mint. The records omit steering text and call credentials.
- `859590b` fixes a read failure exposed by the new detail-free Timeline entries. Home and Timeline briefly failed during the first deployment. The corrective release passed direct Sprite reads and the loaded-view browser matrix.
- `e49c968` makes the model treat image observations and extracted file text as separate evidence and ties event hours to the specific cited event. Both original failures passed a live recheck.

`scripts/deploy.sh` succeeded and production `/health` returned HTTP 200 with Sprite checkpoints. The final suite passed **241 Python tests**, **9 Node tests**, JavaScript syntax checks, and `git diff --check`.

## Production cleanup

The baseline and post-run diff are under `/workspace/tmp/hearth-qa/run49/`. Test side chats, Main messages, memory notes and forget rules, reminders, recurring tasks, automation and run records, the goal, local artifacts and uploads, Feed changes, approval receipts and test Timeline entries were removed. Both original Memory review proposals are pending and match the baseline. The Pinecone memory sync completed after cleanup. The diff records normal background changes and three AgentMail message hashes that prevent the test emails from reappearing during the polling lookback.

The two test files intentionally remain in Box.

- `QA49 Cedar Picnic Plan.docx`
- `QA49 Cedar Picnic Supplies.xlsx`

Both outbound emails went to the configured reminder address. The automation trigger went to the Hearth inbox. Sent email remains in provider mailboxes. Scrubbed screenshots are in the run directory and outside Git.
