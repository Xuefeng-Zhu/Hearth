# Ideas and Goals

## Ideas in Home Feed

Open **Home → Feed → Ideas** to find up to five things Hearth can help with. Swipe or scroll through the strip. **Open draft** and **Draft in Chat** prefill an editable side chat. **Review reminder**, **Review automation**, and **Review watcher** open approval cards that show the proposed action before it runs.

Ideas use the quick brain route, with the same scheduled interval as Feed (four hours by default). A completed chat with at least four user turns or 3,000 dialogue characters can also prompt a pass, at most once per chat every 30 minutes. The pass uses bounded excerpts from recent chats, enabled Memory folders, and workspace data already available through existing connector flows, such as Inbox and Artifacts. Hearth treats those excerpts as data and supplies zero tools to the model. Ideas respect Feed’s on/off and mute settings and Action suggestions’ quiet hours. The Mock brain skips generation.

**Dismiss** removes the card and suppresses its duplicate for the rest of its seven-day lifetime. **Not interested** also saves the topic and action preference for future passes. Ideas expire after seven days or when their source changes. Reminder Ideas are in-app. Automation Ideas can propose a follow-up reminder after an existing reminder fires.

Approved watchers appear under **Reminders → Recurring tasks**. A watcher starts with a daily 9 AM schedule in the workspace time zone. The first read saves a baseline, and later checks notify on changes in displayed prices or readable page text. A price watcher compares prices displayed on the page. Product pages that require sign-in, render prices only through JavaScript, or block the public reader can fail. Watchers use Hearth’s existing bounded public-page reader. [Run 45 Apify gateway probe](watchers.md)

## Goals on Home and in Chat

Select **Home → Goals → New goal** or ask Chat to track a goal. Add an optional target date and an in-app daily or weekly check-in. Use **Edit layout** to move the panel, remove it, or restore it. Removing the panel keeps the goals and their check-in reminders.

**Check in** records progress from 0 to 100 percent and an optional note. Link reminders or recurring tasks in the editor to derive progress from them. A linked reminder counts when marked **Done**, and a linked task counts after a completed run. A linked goal accepts check-in notes. Reach 100 percent to stop future goal check-in reminders.

Hearth stores goals in workspace memory and includes them in chat context. Incomplete goals can get a next step from the quick brain. Suggestions refresh after a goal or its progress changes and may be absent while generation is pending or the connected brain is unavailable.

Chat uses `goal_create`, `goal_update`, and `goal_checkin`. Create and delete default to **Ask first** under **Settings → Approvals**. Creation follows **Create goals** and deletion follows **Delete items**. The same policies apply when you use the Home panel. Timeline logs creates, edits, deletions, and check-ins. Use **Undo** on the most recent change to that goal to restore its previous state. [Run 47 verification](run-47.md)
