# Hearth QA

The local suite uses disposable workspaces, the Mock brain, and provider fixtures. It covers Hearth's side of each integration. Provider behavior depends on the permissions, model access, and routes available to the deployed Sprite.

## Verification

| Check | Result |
| --- | --- |
| Python unit and HTTP tests | 155 passed. Coverage includes approval expiry and duplicate decisions, scheduled actions and retries, memory search and sync, artifacts, page sharing, mail, and voice. |
| Node tests | 8 passed. Coverage includes avatar state, CSV previews, artifact navigation, and time-zone formatting. |
| Syntax | JavaScript and deployment shell scripts passed syntax checks. |
| Playwright | Home, attachments, and Pages passed in Chromium at 390 and 1440 pixels, in light and dark modes. The demo flow passed on mobile and desktop, including the approval card, spreadsheet preview, page preview modes, task run, and Timeline. The contrast sweep recorded 11,375 measurements with zero sampled failures. |
| Local startup and deploy scripts | A fresh server reported local checkpoints and selected Mock. A stubbed Sprites CLI verified deployment, wake, and Pages publisher arguments with the default organization and an explicit override. |

The screenshots use existing QA captures. The Chat crop omits the recipient and the Memory crop omits the note body. [Screenshot strip](README.md#screenshots), [Test commands](docs/development.md)

## Connector and deployment limits

- Box upload and version receipts are covered by the fixture suite. Box history uses receipts when the versions GET is unavailable.
- Pinecone tests exercise dense vectors, integrated indexing, reranking, and local fallback. Verify sync against the index in your own connected project.
- The local call demo does not need a Vocal Bridge room. The live path needs a configured voice agent, browser microphone permissions, and provider access.
- Closed-browser delivery depends on an external wake source when the Sprite sleeps. The checked-in five-minute workflow is an inactive template.
- These checks used local Chromium. Real provider sends, native Sprite restore, and physical-device Safari were outside this verification.

[Deployment](docs/deploy.md), [Connector setup](docs/connectors.md)

## 90-second demo

Start with a fresh local workspace, **Mock** selected, and in-app reminders. In **Settings → Artifacts**, turn off **Auto-save to Box**.

| Time | Action |
| --- | --- |
| 0–10 s | Open Home and show reminders, recent files, and connector health. Switch to Chat and select **Plan Thanksgiving dinner**. |
| 10–25 s | Show the memory citations and the pending invitation. Point out **Approve**, **Edit**, and **Decline**. Leave the draft pending. |
| 25–40 s | Open the generated shopping list and show its spreadsheet preview and **Download** control. Mention that the plan is a PDF and both files appear in **Artifacts**. |
| 40–55 s | In Chat, send “Build a page for Thanksgiving dinner.” Open the page and switch between **Phone** and **Desktop**. |
| 55–75 s | Send “Every weekday at 8am list my reminders.” Show the upcoming local times, then **Confirm**. Open **Reminders → Recurring tasks**, select the new task, and choose **Run now**. |
| 75–90 s | Open the completed run and its side chat. End on Timeline to show the trail from memory recall to scheduled execution. |

For a longer walkthrough, open Memory to show the source notes or choose **Call** with Vocal Bridge disconnected to try the scripted voice demo. [Approvals and tasks](docs/approvals-and-tasks.md), [Voice](docs/voice.md)
