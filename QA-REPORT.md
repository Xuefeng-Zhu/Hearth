# Hearth QA for Hacksgiving

November 25, 2026 UTC · `main` · runtime release `9e35978`

**The core demo is ready.** The local Mock workflow, item-level memory Undo, locally saved artifacts, and in-app reminders passed. Live Box writes and Pinecone-backed recall remain open on this Sprite. All fixes and this report are local commits on `main`.

## Coverage

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

## Defects and fixes

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

## Verification and remaining risks

- `python3 -m unittest discover -s tests` passed **84 tests**. `node --test tests/*.test.mjs` passed **5 tests**. `node --check` passed for each file under `web/*.js`. `scripts/deploy.sh` and the subsequent authenticated `sprite exec --http-post --no-stdin --no-port-forward -o xuefeng-zhu -s hearth` health check passed.
- Used Chromium at **1440 px** and **390 px** with Playwright because the Browser plugin was unavailable. Local checks used isolated workspaces and deterministic provider fixtures. Deployed checks used the private Sprite through authenticated CLI access. The public entry URL required Sprite sign-in. Browser checks against the deployed API used a loopback relay with byte-matched static assets. Live SSE timings were measured inside the Sprite.
- The live Pinecone connector still needs a usable index. The live Box connector’s write restrictions make the upload path a poor demo dependency. External wake cadence determines the worst-case delivery delay when the Sprite sleeps. Real-time delivery below that cadence requires another wake source.
- Pending chat turns are intentionally volatile under the current design. An automatic replay after restart could repeat tools that changed workspace state. Retry is an explicit user action. Larger histories also increase idle Chat transfer and render cost.
- The configured private Sprite received no outbound reminder test email. Testing used an in-app cold-wake job and a separate local fixture for reminder emails.

## 90-second demo

Use the private Sprite’s demo workspace with **Mock** selected. Keep AgentMail approval and Box sync out of the timed flow.

| Time | Action |
| --- | --- |
| 0–15 s | Open Chat and select **Plan Thanksgiving dinner**. Show Ember changing poses as the tools run. |
| 15–35 s | Show the streamed plan, open **Remembered**, and point to the Markdown notes. Show the draft awaiting approval and the in-app reminder card. |
| 35–52 s | Send `Remember topics/demo-oven.md: Preheat the oven at 3 pm.` Open **Memory** and show the saved note. |
| 52–68 s | In **Timeline**, find that exact memory edit, select **Undo** and confirm **Undo change**. Show **Undone** and return to Memory to verify that the note was removed. |
| 68–90 s | Return to Chat, choose **Save as artifact** on the dinner plan, then open the artifact preview and use **Download**. |

## Captures

- Overview at [1440 px](/workspace/tmp/hearth-qa/qa-overview-desktop.png) and [390 px](/workspace/tmp/hearth-qa/qa-overview-mobile.png).
- Markdown before and after on [desktop before](/workspace/tmp/hearth-qa/qa-markdown-before-1440.png), [desktop after](/workspace/tmp/hearth-qa/qa-markdown-after-1440.png), [mobile before](/workspace/tmp/hearth-qa/qa-markdown-before-390.png) and [mobile after](/workspace/tmp/hearth-qa/qa-markdown-after-390.png).
- Interrupted reply and retry on [desktop](/workspace/tmp/hearth-qa/qa-retry-after-1440.png) and [mobile](/workspace/tmp/hearth-qa/qa-retry-after-390.png).
- The single live flight import in Inbox at [1440 px](/workspace/tmp/hearth-qa/qa-inbox-desktop.png) and [390 px](/workspace/tmp/hearth-qa/qa-inbox-mobile.png).
- Timeline at [1440 px](/workspace/tmp/hearth-qa/qa-timeline.png) and [390 px](/workspace/tmp/hearth-qa/qa-timeline-mobile.png).
- [Box fixture](/workspace/tmp/hearth-qa/qa-artifact-detail.png), [Pinecone fixture](/workspace/tmp/hearth-qa/qa-pinecone-recall.png), [reminder Outbox](/workspace/tmp/hearth-qa/qa-reminder-email.png), and [demo call](/workspace/tmp/hearth-qa/qa-call-live.png).
