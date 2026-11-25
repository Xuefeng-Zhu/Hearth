# Approvals and tasks

## Approvals

Review pending actions in Chat, Home, or Inbox. A card shows the target and relevant preview, such as email recipients, subject, and body. Use **Edit** when the action supports it, then **Approve** or **Decline**. Recurring schedules proposed in chat show their upcoming times and use **Confirm**. Pending policy approvals expire after 24 hours.

In **Settings → Approvals**, the Send, Spend, Publish, and Delete categories default to **Always ask**. **Allow without asking** changes the policy for brain tools in that category. If an action matches several categories, any category set to ask will require review. Scheduled brain tools in those categories still require approval. A recurring task's configured email delivery is a separate notification to the saved reminder recipient.

Hearth persists a decision and execution receipt to guard against repeat approval. Timeline records decisions and outcomes. If a provider outcome is unconfirmed, verify it with the provider before requesting the action again. Approved Mock mail uses the workspace Outbox. Delivered live email persists separately from Hearth's disk. [Approval policy and receipts](../hearth/approvals.py), [Agent execution](../hearth/agent.py)

## Reminders

A reminder delivers a message when it comes due. Use **Reminders** to review scheduled items or ask in Chat for a reminder such as “Remind me to check the oven in 10 minutes.” Configure **In app**, **Email**, or **Both**, a time zone, and quiet hours in **Settings → Reminders**. Email uses AgentMail and the saved recipient. Reminder emails can offer signed Done and Snooze links when the Sprite URL is configured. Quiet hours defer delivery, with an override for urgent reminders. [Reminder delivery](../hearth/reminders.py)

An AgentMail inbox can also import forwarded email into Inbox as proposals for review. Sender allowlists and opt-in rules govern automatic acceptance and acknowledgments. [Inbox](../hearth/inbox.py), [AgentMail setup](connectors.md)

## Recurring tasks

A recurring task sends a saved instruction to Hearth's brain. In **Reminders → Recurring tasks**, choose **New task** and set its instruction, schedule, IANA time zone, and delivery. The scheduler supports **Once**, **Daily**, **Weekly**, **Interval**, and five-field **Cron**, with a preview of up to three upcoming run times. You can also ask in Chat, for example “Every weekday at 8am list my reminders,” and confirm the schedule on its card. A first-time workspace includes a paused **Morning brief** example.

Use **Run now** for an immediate run. Each task keeps a side chat and its recent runs show status, output, and tool results. You can edit, pause, resume, or delete the schedule. The runner claims an occurrence before starting it, catches up once for missed runs, and retries a failed run once. Task results appear in Inbox after quiet hours. Email delivery also needs a connected AgentMail inbox and a recipient. [Task runner](../hearth/tasks.py), [Waking a sleeping Sprite](deploy.md#wake-the-scheduler)
