# Hearth QA for Hacksgiving

## Mobile

November 25, 2026 UTC · `main` · Sprite runtime commit `2acb786`

Touch-enabled Chromium with Playwright passed at **375×667**, **390×844**, and **430×932** portrait, **844×390** and **932×430** landscape, and an extra **320×640** check. The **1440×900** desktop sweep covered the sidebar, Chat, calls, and the workspace views. All sweeps completed without JavaScript or console errors. The harness used an isolated workspace with Mock, fixture Inbox mail, and synthetic microphone input. The Browser plugin was unavailable.

| Area | Verification |
| --- | --- |
| Navigation and Chat | Tested bottom tabs and the More sheet, one-tap access to the thread sheet, side-chat creation and switching, Ember full-screen and return, and the mic, call, and send controls on one row. Checked Markdown and artifact chips. An 800-character URL and code token wrapped within the transcript. |
| Viewport and PWA | Checked the standalone manifest, Apple Home Screen metadata and icon, and `viewport-fit=cover`. Chromium simulated a shrinking and panning visual viewport. The composer stayed within it and the tab bar returned on dismissal. A separate Safe Area test supplied 47/34/12/10 px for top, bottom, left, and right. |
| Workspace views | Opened Timeline details, checked Artifacts as a list, edited a preview in the full-screen drawer, and scrolled a ten-column CSV inside its table viewport. Checked the reminder form and its Settings shortcut, forwarded Inbox, Memory, Connections tabs, and all seven Settings disclosures. Sampled interactive controls met 44 px and sampled entry fields used at least 16 px type. |
| Voice and appearance | Exercised full-screen demo calls, mute, minimize, resume, and hang-up. Started and canceled dictation with the mobile overlay. Swept dark mode at 390 px and used reduced motion throughout. |

Physical iPhone Safari, the operating system keyboard animation, and installation from the iOS share sheet remain unverified. The keyboard check exercised the visual viewport response in Chromium. [WebKit visual viewport timing](https://bugs.webkit.org/show_bug.cgi?id=265578), [Apple status-bar metadata](https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/SafariHTMLRef/Articles/MetaTags.html)

### 390×844 captures

[Mobile overview](/workspace/tmp/hearth-qa/mobile-overview.png)

| Screen | Before | After |
| --- | --- | --- |
| Chat | [Before](/workspace/tmp/hearth-qa/mobile-chat-before.png) | [After](/workspace/tmp/hearth-qa/mobile-chat-after.png), [Markdown and chips](/workspace/tmp/hearth-qa/mobile-chat-markdown-after.png) |
| Chat threads | [Before](/workspace/tmp/hearth-qa/mobile-threads-before.png) | [After](/workspace/tmp/hearth-qa/mobile-threads-after.png) |
| Timeline | [Before](/workspace/tmp/hearth-qa/mobile-timeline-before.png) | [After](/workspace/tmp/hearth-qa/mobile-timeline-after.png) |
| Artifacts | [Before](/workspace/tmp/hearth-qa/mobile-artifacts-before.png) | [After](/workspace/tmp/hearth-qa/mobile-artifacts-after.png) |
| Artifact detail | [Before](/workspace/tmp/hearth-qa/mobile-artifact-detail-before.png) | [After](/workspace/tmp/hearth-qa/mobile-artifact-detail-after.png) |
| Reminders | [Before](/workspace/tmp/hearth-qa/mobile-reminders-before.png) | [After](/workspace/tmp/hearth-qa/mobile-reminders-after.png) |
| More | [Workspace links before](/workspace/tmp/hearth-qa/mobile-more-before.png) | [After](/workspace/tmp/hearth-qa/mobile-more-after.png) |
| Inbox | [Before](/workspace/tmp/hearth-qa/mobile-inbox-before.png) | [After](/workspace/tmp/hearth-qa/mobile-inbox-after.png) |
| Memory | [Before](/workspace/tmp/hearth-qa/mobile-memory-before.png) | [After](/workspace/tmp/hearth-qa/mobile-memory-after.png) |
| Connections | [Before](/workspace/tmp/hearth-qa/mobile-connections-before.png) | [After](/workspace/tmp/hearth-qa/mobile-connections-after.png) |
| Settings | [Before](/workspace/tmp/hearth-qa/mobile-settings-before.png) | [After](/workspace/tmp/hearth-qa/mobile-settings-after.png), [Open Brain section](/workspace/tmp/hearth-qa/mobile-settings-brain-after.png) |
| Call | [Before](/workspace/tmp/hearth-qa/mobile-call-before.png) | [After](/workspace/tmp/hearth-qa/mobile-call-after.png) |
| Voice input | [Before](/workspace/tmp/hearth-qa/mobile-voice-before.png) | [After](/workspace/tmp/hearth-qa/mobile-voice-after.png) |

[Simulated keyboard](/workspace/tmp/hearth-qa/mobile-keyboard-after.png), [Safe areas](/workspace/tmp/hearth-qa/mobile-safe-area.png), [Landscape Chat](/workspace/tmp/hearth-qa/mobile-chat-landscape.png), [Landscape Call](/workspace/tmp/hearth-qa/mobile-call-landscape.png), [Dark Settings](/workspace/tmp/hearth-qa/mobile-dark-settings-brain.png), [Desktop Chat](/workspace/tmp/hearth-qa/mobile-desktop-chat.png)

### Live Box upload

The deployed `POST /api/artifacts/create` returned **201** and synchronized to Box. The deployed `POST /api/artifacts/update` returned **200** for the same file. A detail request after the final deployment returned version 2 and both receipts. The direct gateway request to `GET 2.0/files/2614704783851/versions` returned **403** with “request is not supported by this connector.” Hearth used its saved history. The live verification file remains in Box. [Box verification file](https://app.box.com/file/2614704783851)

| Receipt | ID |
| --- | --- |
| Hearth artifact | `4a2a28b60023449ebe6abaf5f1a156b5` |
| Box file | `2614704783851` |
| Box version 1 | `2902976041451` |
| Box version 2 | `2902968544059` |

The Box fixture checked both gateway upload paths, multipart ordering, the 50 MiB file limit, fallback and retry, and workspace-only Trash and restore. `python3 -m unittest discover -s tests` passed **91 tests**. `node --test tests/*.test.mjs` passed **5 tests**. Every `web/*.js` file passed `node --check`. `scripts/deploy.sh` succeeded. The authenticated Sprite `/health` responded with `{"ok": true, "checkpoints": "sprite"}`, and the hashes for seven served assets matched the local files.

## Round 2

November 25, 2026 UTC · `main` · Sprite runtime commit `37caf1e`

The Mock demo flow passed. Round 2 reproduced defects in Inbox polling, chat rendering, keyboard focus, connection testing and idle Chat transfer. The runtime fixes were deployed to the private Hearth Sprite.

| Area | Result | Round 2 evidence |
| --- | --- | --- |
| 0. Artifacts and Box | Open | Chromium exercised chat creation, preview, CSV, grid/list, filters, download, edits, deletion during reload and return focus after editing. The Box fixture covered sync, the file link, version history, Trash and Undo. Sprite listing and preview responded. Live Box upload and version writes remain blocked by the known gateway 403. |
| 1. Chat | Fixed | Both widths covered streaming, completion, Markdown, long and unusual text, model chips, interrupted SSE and retry. Tests exercised fallback after a tool action, split/self-closing tool tags and incomplete credentials. The Sprite exposed two older replies with tool tags before deployment and zero after sanitization. Live greeting and action requests returned replies in an isolated Sprite workspace. |
| 2. Side chats | Pass | At both widths, Main and side turns overlapped, switching preserved isolation, and reload during another turn kept the selected thread and recovered its saved reply. A local process restart preserved the started prompt, cleared volatile queued work, and accepted a new retry. |
| 3. Memory | Open | Chromium exercised note save, local recall, Remembered disclosure, settings and the Pinecone fixture. The suite covered English and Chinese matching and vector deletion/reindex after Forget, Undo and Redo. Live Pinecone remains blocked by the known 403 on index creation. |
| 4. Timeline | Pass | Both widths rendered and opened all 17 supported kinds using an exhaustive fixture, with search, filter, empty results and live arrival of an artifact event. Separate flows exercised real tool, connector, reminder, Inbox, Voice and Undo entries. Live Sprite Timeline snapshots loaded in Chromium. |
| 5. Undo | Pass | Verified reversible note changes, reminder cancellation, Inbox imports, artifact create/update/Trash, simulated email and local checkpoint restore against server state. Native checkpoint restore on the shared Sprite remains outside the verified scope because a restore would roll back the shared workspace. |
| 6. Reminders and wake | Open | Both widths exercised channel selection, list, in-app and email test controls, disconnected Outbox, and the action page. The suite verified natural-language channels, quiet hours, urgent bypass, retries and signed-link replay. The Sprite was cold before the 15:24:28 UTC due time and immediately before authenticated wake. One in-app delivery appeared at 15:24:37 UTC, a second tick produced zero duplicate deliveries, and an unsigned tick returned 401. The recipient stayed empty and no real reminder email was sent. The external periodic wake workflow remains inactive. |
| 6b. Forward-to-Hearth Inbox | Fixed | Browser polling, manual polling over a pending check, simultaneous drafts, flight/booking/receipt/school/Chinese/plain messages, instruction-like text and ICS attachments were exercised against the fixture. Tests covered the cursor, allowlist/DMARC, opt-in acknowledgment, and Accept/Edit/Undo effects. After deployment, two forced polls returned HTTP 200 with zero new imports, and the single existing flight still appeared at both widths. |
| 7. Connections | Fixed | Both widths covered configured/catalog tabs, keyboard switches, search and filtering. The live sweep reproduced a Test 409 during discovery. The regression suite exercises discovery contention for Rescan, Test and Memory search. Configured checks were verified for Hugging Face, Exa, Pinecone, Box and Vocal Bridge. |
| 8. Settings | Pass | Chromium visited Brain, Memory, Search, Reminders, Artifacts, Appearance, Voice and Calls at both widths. Routing preview classified greeting and action prompts separately. The suite covered model-pool tags and routing/fallback. Chinese call language and transcript preferences persisted in the demo. |
| 9. Ember | Pass | A complete Mock turn exercised all nine poses, captions, placement and full-screen mode, presets, color, reduced motion and side-thread activity. Keyboard controls and pose announcements were checked. |
| 10. Voice input | Pass | Chromium exercised microphone, level meter, hold-Space, Escape, edit, auto-send, permission denial and unsupported feedback with synthetic audio or browser fixtures. The Sprite Whisper endpoint returned HTTP 200 with a nine-word transcription in 1.242 s. Synthetic speech accuracy beyond that sample remains unmeasured. |
| 11. Vocal Bridge | Open | Chromium exercised demo call controls and saved Main and side-chat transcript cards. The suite verified redaction. The configured Sprite minted one real token with HTTP 200 and `Cache-Control: no-store`. The token stayed out of output. Chromium could not negotiate the LiveKit connection through the harness proxy, so a real conversation and its language hint remain unverified. |
| 12. Shell and assets | Pass | Shell title, icons, manifest, 404, responsive width, network and page errors were checked. The authenticated Sprite CLI proxy reset TCP connections. The browser used a loopback relay for real Sprite APIs and static files checked against remote hashes. The relay did not forward Timeline's long-lived event stream, which was tested locally and checked directly on the Sprite. |
| 13. Security | Fixed | Tests checked the shared origin gate, oversized or malformed bodies, lone surrogates, non-finite numbers, signed actions, and transcript/stream redaction. HTML-shaped text in chat, a side-chat title and memory stayed literal in Chromium. A targeted `git grep` found no tracked key-pattern matches. |
| 14. Accessibility | Fixed | Keyboard navigation, focus visibility, disclosure, reduced motion, and artifact return focus passed at 1440 and 390 px. The chat regression keeps an expanded Remembered item and its keyboard focus through other-tab updates. Sampled CSS contrast was 4.89:1 for unselected navigation, 8.11:1 for selected navigation, and 5.38:1 for the focus outline on the page background. Full screen-reader and WCAG audits remain unverified. |
| 15. Performance | Fixed | A 320-message thread transferred 211–215 KB every three seconds before the fix. Two idle checks at each width returned 304 with zero response body after it. The final Sprite loaded 273 KB of static resources with the call SDK deferred. Mock reply paint was 0.41–0.50 s. Live Sprite first token was 1.205 s for the greeting and 2.724 s for the action turn. A 14-cycle Chat/Timeline navigation sample retained about 0.29 MB more JavaScript heap after garbage collection at each width. Multi-hour behavior and server-side work on large state remain unmeasured. |

### Round 2 defects

| Severity | Defect | Fix and verification | Commit |
| --- | --- | --- | --- |
| High | AgentMail rejected the persisted `after` cursor once Hearth had imported a message. Subsequent browser and wake polls could stop importing new mail. | Convert stored UTC offsets to `Z` at the AgentMail boundary. The live gateway returned 400 for the saved offset and 200 for the same instant in the fixed format. | `37caf1e` |
| Medium | Chat streamed Mock note excerpts with raw tool markup, self-closing tags could swallow following text, and old saved replies still displayed tool tags. | Apply the same filter before Mock emission, preserve following text, and sanitize archived replies when read. | `cc2ec03` |
| Medium | Check mail silently dropped requests during a browser poll, could return completion when the connector failed, and a different card's action destroyed open Inbox drafts. | Queue an explicit manual check after browser polling, wait for the Inbox lock, surface connector errors, and preserve active editor nodes. | `cc2ec03` |
| Medium | Unchanged chat messages were replaced after another-tab update, closing disclosures and clearing keyboard focus. | Keep unchanged message nodes in place while reconciling the transcript. Verified at both widths. | `cc2ec03` |
| Medium | Idle Chat repeatedly transferred complete long conversations. | Send entity tags with state responses and reuse the current snapshot on a 304. | `aa9e277` |
| Medium | Connection tests could return 409 during normal background discovery. | Reuse the bounded operation-lock wait for Test. | `37caf1e` |
| Medium | Incomplete private key blocks and non-finite or truncated JSON were not handled consistently. | Redact unfinished key blocks and reject non-finite JSON and early EOF up front. | `aa9e277`, `cc2ec03` |
| Low | Closing an artifact after saving an edit moved keyboard focus to Search. | Restore focus to the artifact's replacement opener and keep it through list refresh. | `37caf1e` |

### Round 2 verification and captures

- `python3 -m unittest discover -s tests` passed **89 tests**. `node --test tests/*.test.mjs` passed **5 tests**. `node --check` passed for every `web/*.js` file. `scripts/deploy.sh` and the requested authenticated `sprite exec --http-post --no-stdin --no-port-forward -o xuefeng-zhu -s hearth` health check passed.
- Six adversarial Chromium scenarios and three focused regression checks passed at each width. The deployed desktop and mobile sweeps reported no JavaScript or console errors. Twenty-one deployed web files matched the local runtime by SHA-256.
- Overview at [1440 px](/workspace/tmp/hearth-qa/qa-overview-desktop.png) and [390 px](/workspace/tmp/hearth-qa/qa-overview-mobile.png). The single deployed Inbox flight import at [1440 px](/workspace/tmp/hearth-qa/qa-inbox-desktop.png) and [390 px](/workspace/tmp/hearth-qa/qa-inbox-mobile.png).
- Chat disclosure and focus on [desktop before](/workspace/tmp/hearth-qa/qa-r2-chat-disclosure-before-1440.png), [desktop after](/workspace/tmp/hearth-qa/qa-r2-chat-disclosure-after-1440.png), [mobile before](/workspace/tmp/hearth-qa/qa-r2-chat-disclosure-before-390.png) and [mobile after](/workspace/tmp/hearth-qa/qa-r2-chat-disclosure-after-390.png).
- Archived tool markup on [desktop before](/workspace/tmp/hearth-qa/qa-r2-sanitizer-before-1440.png), [desktop after](/workspace/tmp/hearth-qa/qa-r2-sanitizer-after-1440.png), [mobile before](/workspace/tmp/hearth-qa/qa-r2-sanitizer-before-390.png) and [mobile after](/workspace/tmp/hearth-qa/qa-r2-sanitizer-after-390.png).
- Manual Inbox poll on [desktop before](/workspace/tmp/hearth-qa/qa-r2-inbox-poll-before-1440.png), [desktop after](/workspace/tmp/hearth-qa/qa-r2-inbox-poll-after-1440.png), [mobile before](/workspace/tmp/hearth-qa/qa-r2-inbox-poll-before-390.png) and [mobile after](/workspace/tmp/hearth-qa/qa-r2-inbox-poll-after-390.png). Parallel edit drafts at [1440 px](/workspace/tmp/hearth-qa/qa-r2-inbox-drafts-1440.png) and [390 px](/workspace/tmp/hearth-qa/qa-r2-inbox-drafts-390.png).
- Artifact return focus on [desktop before](/workspace/tmp/hearth-qa/qa-r2-artifact-focus-before-1440.png), [desktop after](/workspace/tmp/hearth-qa/qa-r2-artifact-focus-after-1440.png), [mobile before](/workspace/tmp/hearth-qa/qa-r2-artifact-focus-before-390.png) and [mobile after](/workspace/tmp/hearth-qa/qa-r2-artifact-focus-after-390.png).
- Timeline kinds at [1440 px](/workspace/tmp/hearth-qa/qa-r2-timeline-kinds-1440.png) and [390 px](/workspace/tmp/hearth-qa/qa-r2-timeline-kinds-390.png). [Box fixture](/workspace/tmp/hearth-qa/qa-r2-artifact-detail.png), [Pinecone fixture](/workspace/tmp/hearth-qa/qa-r2-pinecone-recall.png), [Outbox](/workspace/tmp/hearth-qa/qa-r2-reminder-email.png) and [Vocal Bridge demo](/workspace/tmp/hearth-qa/qa-r2-call-live.png).

## 90-second demo

Use a demo workspace with **Mock** selected and **Auto-save to Box** off. Leave the email draft awaiting approval. The complete automated walkthrough took 18 seconds at each width, leaving time for narration.

| Time | Action |
| --- | --- |
| 0–15 s | Open Chat and select **Plan Thanksgiving dinner**. Show Ember changing poses while the tools run. |
| 15–35 s | Show the streamed plan. Open **Remembered**, point to the source notes, and show the email draft and in-app reminder card. |
| 35–52 s | Send `Remember topics/demo-oven.md: Preheat the oven at 3 pm.` Open **Memory** and select the saved note. |
| 52–68 s | Search for `topics/demo-oven.md` in **Timeline**. Select **Undo** on its memory edit and confirm **Undo change**. Show **Undone** and verify the note disappeared from Memory. |
| 68–90 s | Return to Chat, open **Saved “Thanksgiving plan” locally**, and select **Download**. |

## Round 1

November 25, 2026 UTC · `main` · runtime release `9e35978`

### Coverage

**Pass** means the stated checks succeeded. **Fixed** means a QA defect was corrected and rechecked. **Open** means an integration or verification gap remains, even where the rest of the area passed.

| Area | Result | Evidence and limits |
| --- | --- | --- |
| 0. Artifacts and Box | Open | Chromium verified chat-created artifacts, list/grid, search, preview, edits, copy, download, status, deletion and Undo with the Box fixture. The fixture covered upload, versioning, Trash restore and the original Box link. The deployed connector can list files. Live upload and version writes remain unavailable through the configured gateway. The local-only and failed-sync copies remain usable. |
| 1. Chat | Fixed | Chromium checked Mock replies, chip, rendered Markdown, a 3,900-character prompt, escaped text and interruption/retry. Tests cover split tool markup, provider fallback and suppression of replay after a state-changing tool. The deployed release routed a greeting to Llama and a reminder to Qwen, with one in-app job created in an isolated Sprite workspace. No live outage was induced. |
| 2. Side chats | Pass | Chromium checked creation, thread switching and reload persistence. The thread suite covers isolated context, simultaneous turns, queued ordering and deleted sources. A real local process restart confirmed that pending turns are cleared, the started prompt remains in history, and retry works after startup. |
| 3. Memory | Open | Chromium exercised save/recall, Settings, local fallback, and fixture Pinecone sync/rebuild/status. The gateway fixture and suite cover English and Chinese queries, deletion and reindexing after Undo/Redo. The real connector has no usable `hearth-memory` index, so live vector reads, writes and deletion remain unverified. |
| 4. Timeline | Open | Chromium checked search, empty results, filtering, expansion, Raw details, and live chat/voice/reminder updates across the local sweep and targeted checks. Coverage across feature suites includes chat, routing, recall, memory, email, reminders, voice, search, artifacts, Inbox, connector activity and checkpoints. An exhaustive rendered assertion for every event subtype remains open. |
| 5. Undo | Pass | Verified item-level server reversions for notes, artifacts, reminders and Inbox acceptance, plus local workspace restore and simulated email state. The suite covers artifact conflicts and guarded approvals. Real email delivery and other provider-side operations remain external. No native rollback of the shared Sprite was run during this QA pass. |
| 6. Reminders and wake | Open | Desktop and mobile Chromium covered channels, creation, listing, Undo, late delivery, test controls and the disconnected Outbox. Automated checks cover quiet hours, urgent bypass, retry keys, dedupe, signed Done/Snooze, expiry, and replay. Authenticated wake caught up the deployed in-app reminder due at 11:59:10 UTC at 12:05:51 UTC. The saved recipient was empty and stayed empty. AgentMail reminder delivery was not sent live. The external periodic wake workflow is still inactive. |
| 6b. Forward-to-Hearth Inbox | Fixed | Manual **Check mail** now bypasses the background poll interval. The deployed Inbox contains exactly one flight import and a subsequent poll reported no duplicate. Fixtures cover flight, receipt, school, Chinese, plain mail, attachments, ICS, cursor, sender authentication, opt-in acknowledgments, and injection-like text. Chromium exercised Accept, Edit, Dismiss and Undo against six local mail fixtures. The existing live flight was already Undone. No second live flight or acknowledgment was sent. |
| 7. Connections | Pass | Chromium covered both tabs, keyboard switching, search and the configured/catalog distinction. Concurrent discovery and Memory searches now wait briefly for ordinary lock contention. The deployed checks exercised Hugging Face, Exa, Pinecone, Box and Vocal Bridge. A gateway authorization check alone does not establish support for specific write endpoints. |
| 8. Settings | Pass | Chromium exercised Brain, Memory, Search, Appearance, Voice, Calls, Reminders and Artifacts at the requested widths. Model pool tags, routing/fallback and disconnected search adapters are covered by fixture or Python tests. |
| 9. Ember | Pass | Chromium observed idle, listening, thinking, working, concerned, speaking, remembering, happy and sleeping. Checked placement, full screen/captions, pose announcements, presets, color, reduced motion and activity across threads. |
| 10. Voice input | Pass | Chromium exercised the mic, fake-microphone recording/level, hold-Space, Escape, interim speech, edit/auto-send, permission denied and unsupported feedback. The deployed Whisper endpoint transcribed the synthetic WebM correctly in 0.756 s. |
| 11. Vocal Bridge | Open | Chromium completed demo calls, live-sheet controls and transcript persistence on Main and a side chat. Tests cover transcript redaction and token isolation. The configured release minted one real credential with HTTP 200 and `Cache-Control: no-store`. The token was never printed. A fresh real WebRTC conversation and the agent’s use of the non-Auto language hint remain unverified in this pass. |
| 12. Shell and assets | Pass | Chromium checked the Hearth title, manifest, icons, broken-image state and responsive layout. The app returns a JSON 404 for unknown routes. The final local browser sweep recorded no console errors at either width. Sprite release asset hashes were compared with the files loaded in the QA browser. The CLI relay occasionally could not carry large JSON responses, so coverage of the full live browser flow is incomplete. |
| 13. Security | Fixed | Every POST handler shares the origin gate, including endpoints that accept raw audio. The scheduler also requires its separate token. Regression tests cover malformed, oversized and deeply nested JSON, escaped user text and credential redaction. `git grep` found no matches for the checked API key, GitHub, Hugging Face, Pinecone, Slack or private-key patterns in tracked files. This was a targeted review of user-facing data paths. |
| 14. Accessibility | Pass | A Chromium keyboard walkthrough checked navigation, visible composer focus, Escape, Timeline disclosure and reduced motion. Labels were checked on chat, voice, search and settings controls. The sampled color pairs had contrast ratios from 5.30:1 to 7.10:1. Full screen-reader and WCAG conformance audits were outside this pass. |
| 15. Performance | Open | Chromium measured 269,980 bytes of initial static resources with the call SDK deferred. Idle Chat made two state requests in 6.5 seconds at each width. Local Mock reply paint was approximately 0.41–0.48 s in the instrumented browser. On the Sprite, greeting first token was 0.554 s and tool-turn first token 2.806 s. Completed background turns are released from client memory. Long-session heap behavior and large workspace performance remain unmeasured. |

### Defects and fixes

| Severity | Defect | Fix and verification | Commit |
| --- | --- | --- | --- |
| High | Some POST handlers checked only `Sec-Fetch-Site: cross-site`, while newer routes also enforced exact Origin. | Put the exact-origin gate in front of all POST dispatch. Regression checks cover route families and scheduler authentication. | `8223375` |
| Medium | Several JSON body readers could wait indefinitely on a stalled request. Lone Unicode surrogates and extreme JSON nesting could also interrupt a request instead of returning a handled error. | Bound body reads and reject invalid inputs. Tests cover size, surrogate and nesting cases. The same change redacts recognized credentials when reading legacy Markdown through the Memory API. | `8223375` |
| Medium | Provider replies could display or store model-control markup such as `</function>`. Stream deltas and model-generated draft email could also expose recognized credential strings before redaction. | Filter split model markup and redact before publishing streamed deltas, saving replies, or staging email content. Tests split tool tags and credentials across deltas and check the transcript and events. | `160a425` |
| Medium | Completed assistant answers showed Markdown control characters as plain paragraphs. | Reuse the existing text-node Markdown renderer for completed replies. Desktop and mobile Chromium verified headings and literal handling of unfamiliar tags. | `e05c738` |
| Medium | **Check mail** used the same throttle as background polling and could report completion without contacting AgentMail. | Send an explicit manual flag through the same-origin endpoint. Regression checks verify that manual polling fetches immediately and deduplicates subsequent mail. | `d409cf5` |
| Medium | An interrupted chat could keep partial text while losing the explanation and leaving the prompt difficult to retry. | Keep the error on the turn and add **Edit and retry**. The action restores the prompt to an empty composer and preserves an existing draft. Chromium exercised this with an interrupted SSE fixture. | `4724048` |
| Medium | Multiple tabs could trigger 409s on Connections discovery and Memory search during ordinary lock contention. | Allow a bounded wait. A regression test holds the operation lock during each request and verifies both complete successfully. | `9e35978` |
| Low | Completed turns in background threads could remain in the client’s pending set until the user reopened the thread. | Release completed turns after the server saves them. Clean up local thread state when the server reports that a selected thread no longer exists. | `4724048` |

### Verification and remaining risks

- `python3 -m unittest discover -s tests` passed **84 tests**. `node --test tests/*.test.mjs` passed **5 tests**. `node --check` passed for each file under `web/*.js`. `scripts/deploy.sh` and the subsequent authenticated `sprite exec --http-post --no-stdin --no-port-forward -o xuefeng-zhu -s hearth` health check passed.
- Used Chromium at **1440 px** and **390 px** with Playwright because the Browser plugin was unavailable. Local checks used isolated workspaces and deterministic provider fixtures. Deployed checks used the private Sprite through authenticated CLI access. The public entry URL required Sprite sign-in. Browser checks against the deployed API used a loopback relay with byte-matched static assets. Live SSE timings were measured inside the Sprite.
- The live Pinecone connector still needs a usable index. The live Box connector’s write restrictions make the upload path a poor demo dependency. External wake cadence determines the worst-case delivery delay when the Sprite sleeps. Real-time delivery below that cadence requires another wake source.
- Pending chat turns are intentionally volatile under the current design. An automatic replay after restart could repeat tools that changed workspace state. Retry is an explicit user action. Larger histories also increase idle Chat transfer and render cost.
- The configured private Sprite received no outbound reminder test email. Testing used an in-app cold-wake job and a separate local fixture for reminder emails.

### Captures

- Overview at [1440 px](/workspace/tmp/hearth-qa/qa-overview-desktop.png) and [390 px](/workspace/tmp/hearth-qa/qa-overview-mobile.png).
- Markdown before and after on [desktop before](/workspace/tmp/hearth-qa/qa-markdown-before-1440.png), [desktop after](/workspace/tmp/hearth-qa/qa-markdown-after-1440.png), [mobile before](/workspace/tmp/hearth-qa/qa-markdown-before-390.png) and [mobile after](/workspace/tmp/hearth-qa/qa-markdown-after-390.png).
- Interrupted reply and retry on [desktop](/workspace/tmp/hearth-qa/qa-retry-after-1440.png) and [mobile](/workspace/tmp/hearth-qa/qa-retry-after-390.png).
- The single live flight import in Inbox at [1440 px](/workspace/tmp/hearth-qa/qa-inbox-desktop.png) and [390 px](/workspace/tmp/hearth-qa/qa-inbox-mobile.png).
- Timeline at [1440 px](/workspace/tmp/hearth-qa/qa-timeline.png) and [390 px](/workspace/tmp/hearth-qa/qa-timeline-mobile.png).
- [Box fixture](/workspace/tmp/hearth-qa/qa-artifact-detail.png), [Pinecone fixture](/workspace/tmp/hearth-qa/qa-pinecone-recall.png), [reminder Outbox](/workspace/tmp/hearth-qa/qa-reminder-email.png), and [demo call](/workspace/tmp/hearth-qa/qa-call-live.png).
