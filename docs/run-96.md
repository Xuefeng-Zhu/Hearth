# Run 96 · Chat context for attachments and approval receipts

In Main, Hearth treated “这真的吗” accompanying a screenshot as a question about the preceding deletion receipt. It then denied a deletion Hearth had already performed with the owner’s approval. The image could be described independently by both configured vision models.

## Attachment context

Chat marks which attachment references belong to the latest user message. The system prompt grounds short or ambiguous questions in those attachments and tells the model to disclose which current files it could not read. Older attachments remain available for explicit follow-ups. A fresh attachment also takes precedence over an implicit Pages clarification. Explicit Pages requests still use the page planner, which receives the attachment guidance. [Chat prompt assembly](../hearth/agent.py), [Attachment guidance](../hearth/uploads.py)

## Receipt history

Model history labels successful approval receipts using the linked action’s saved status. Declined, failed, simulated, and unconfirmed results keep their recorded outcomes, and a receipt with a missing action record keeps its approval provenance. Recurring task and event automation outputs identify their source. The same rendering is used for earlier dialogue summaries and chat excerpts supplied to models. Chat displays the original receipt text. Reminder delivery itself records results in reminder and delivery state. [History rendering](../hearth/threads.py), [Approval result writer](../hearth/approvals.py), [Reminder scheduler](../hearth/scheduler.py)

## Verification

The regressions replay the Chinese screenshot question with a previous deletion receipt, simulate both vision models failing with an older readable attachment present, and compare the model’s receipt history with the stored transcript. They use a mock gateway and local fixtures. [Regression tests](../tests/test_chat_context.py)

- Python passed all 347 tests with `HEARTH_CJK_FONT` in a local filesystem copy with Git metadata. Runs from the workspace mount hit the existing three-second reminder subprocess timeout.
- Node passed all 37 tests. `node --check` passed for all 69 frontend modules.
- Offline Chromium passed `--core` and `--chat-search`, including the width sweep from 390 through 1920 px.
