# Approvals and tasks

## Approvals

Review pending actions in Chat, Home, or Inbox. A card shows the target and relevant preview, such as email recipients, subject, and body. Use **Edit** when the action supports it, then **Approve** or **Decline**. Recurring schedules proposed in chat show their upcoming times and use **Confirm**. Pending policy approvals expire after 24 hours.

In **Settings → Approvals**, the Send, Spend, Publish, Delete, Skills, and Create goals categories default to **Always ask**. **Allow without asking** changes the policy for eligible brain tools in that category. The built-in **Draft an email** skill always uses an approval card for an explicit send. If an action matches several categories, any category set to ask will require review. Scheduled brain tools that request actions in those categories still require approval. A recurring task's configured email delivery is a separate notification to the saved reminder recipient.

Hearth persists a decision and execution receipt to guard against repeat approval. Timeline records decisions and outcomes. If a provider outcome is unconfirmed, verify it with the provider before requesting the action again. Approved Mock mail uses the workspace Outbox. Delivered live email persists separately from Hearth's disk. [Approval policy and receipts](../hearth/approvals.py), [Agent execution](../hearth/agent.py)

## Reminders

A reminder delivers a message when it comes due. Use **Reminders** to review scheduled items or ask in Chat for a reminder such as “Remind me to check the oven in 10 minutes.” Configure **In app**, **Email**, or **Both**, a time zone, and quiet hours in **Settings → Reminders**. Email uses AgentMail and the saved recipient. Reminder emails can offer signed Done and Snooze links when the Sprite URL is configured. Quiet hours defer delivery, with an override for urgent reminders. [Reminder delivery](../hearth/reminders.py)

An AgentMail inbox can also import forwarded email into Inbox as proposals for review. Sender allowlists and opt-in rules govern automatic acceptance and acknowledgments. [Inbox](../hearth/inbox.py), [AgentMail setup](connectors.md)

## Recurring tasks

A recurring task sends a saved instruction to Hearth's brain. In **Reminders → Recurring tasks**, choose **New task** and set its instruction, schedule, IANA time zone, and delivery. The scheduler supports **Once**, **Daily**, **Weekly**, **Interval**, and five-field **Cron**, with a preview of up to three upcoming run times. You can also ask in Chat, for example “Every weekday at 8am list my reminders,” and confirm the schedule on its card. A first-time workspace includes a paused **Morning brief** with reminders, For you suggestions, weather, and pending approvals. [Morning brief](proactivity.md#morning-brief)

Use **Run now** for an immediate run. Each task keeps a side chat and its recent runs show status, output, and tool results. You can edit, pause, resume, or delete the schedule. The runner claims an occurrence before starting it, catches up once for missed runs, and retries a failed run once. Task results appear in Inbox after quiet hours. Email delivery also needs a connected AgentMail inbox and a recipient. [Task runner](../hearth/tasks.py), [Waking a sleeping Sprite](deploy.md#wake-the-scheduler)

## Event-triggered automations

Open **Settings → Automations** and choose **New automation**. Choose one trigger and up to six actions. Use **Pause**, **Enable**, **Edit**, or **Delete** to manage a rule. Expand **Run history** to see its most recent 20 runs and their action results. Chat can also prepare a proposal, for example “When Sam emails me, summarize it and remind me tomorrow.” Hearth needs a complete sender address, which it can take from the request or recall from the user's notes. Review **When** and **Then** on the card and choose **Confirm** to save.

| Trigger | Options |
| --- | --- |
| Incoming email | Match the AgentMail sender address, a case-insensitive subject substring, the presence of an attachment, or any new incoming email. If you set several filters, the message must match all of them. A forwarded message matches the forwarding address. |
| Reminder fires | Choose a reminder or match any reminder when the scheduler fires it. |
| Feed card appears | Match a new card by kind, case-insensitive exact topic, or both. Existing cards stay outside a newly enabled rule. |
| Schedule | Run once or use a daily, weekly, interval, or five-field cron schedule with a time zone. Hearth catches up once after a sleep that spans several scheduled times. |

Actions run in order. A prompt writes a result to an existing chat or a new side chat. It receives the event as reference data and runs with tools disabled. You can also save incoming attachments to local Artifacts or through the Box gateway, create an in-app reminder with a delay, email a summary to **Settings → Reminders → Recipient email**, or add a Feed card. An email summary or Feed card uses the latest prompt result in the current run, or summarizes the event if there is no earlier prompt. Each attachment can be up to 20 MiB.

**Settings → Approvals → Send messages** governs summary emails and Box uploads. Hearth prepares the approval when the run reaches the action. Find it in Home or Inbox. **Allow without asking** applies the saved policy automatically. The **Delete items** policy governs automation deletion. Pausing a rule or changing its trigger or actions stops queued runs and cancels pending approvals. A declined, expired, or failed action stops the remaining steps.

Hearth deduplicates events and starts at most 10 runs per rule in a rolling hour. A generated reminder or Feed card carries the rules that already ran in its chain so those rules cannot run again in that chain. Hearth also ignores its own outbound mail as a trigger. Incoming email and Feed text are reference data. Automation creation through Chat requires a direct user request and confirmation.

Timeline records each run, including runs skipped due to the hourly limit. Undo can cancel a still-pending in-app reminder and remove a Feed card created by the run. Artifact creation has its own Timeline Undo for the Hearth copy. A file already uploaded to Box stays in Box, and mail already sent stays delivered. [Runner](../hearth/event_automations.py), [Run 44 verification](run-44.md)
