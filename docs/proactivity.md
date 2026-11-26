# Feed and Action suggestions

The **Feed** is a Home panel. Use **Edit layout** to move it, remove it, or restore it. It brings together five kinds of cards.

| Card | What it shows |
| --- | --- |
| Read | An article found through Exa, with its publisher and a short explanation of why it matters to you |
| Idea | A next step grounded in a note or person saved in Memory |
| Digest | A short roundup with links to multiple Exa results on a topic you follow |
| Reminder | Useful prep for a scheduled reminder within the next two weeks |
| Action | A timely suggestion from Hearth’s existing proactivity planner, with a button that starts the offered work in a side chat |

Cards show when they appeared, why Hearth surfaced them, and links to their sources. Scroll the panel to load older cards, or use **Show more**. Choose **Like**, **Dismiss**, or **Less like this** to adjust the topic’s weight for the next run. **Save** bookmarks a card under **Saved** and also adds a small positive weight. **Ask about this** opens a side chat with a draft question using the card as context. You can edit the draft before sending.

## Timing and steering

**Settings → Feed** controls whether the Feed runs, how often it refreshes, and which topics to follow or mute. The default interval is four hours. The interest profile combines your explicit topics with interests derived from Memory and scores from card feedback. Edit the profile by following or muting topics. Set free-text steering here or at the top of the panel. For example, “AI and hackathon news in the morning, family weekend ideas on Fridays.”

**Refresh** requests an immediate discovery pass. Both scheduled and manual runs respect the Pacific quiet hours in **Settings → Action suggestions**, which default to 10 PM–7 AM. A pass targets three to six new cards. It may publish fewer when sources are sparse, muted, or already covered. Hearth catches up on wake after the Sprite sleeps. [Scheduler wake](deploy.md#wake-the-scheduler)

## Sources and privacy

The Feed uses the brain’s quick routing mode and the configured Memory recall backend, including Pinecone when available and selected by Recall. It uses bounded local references from people notes, other enabled Memory folders, and scheduled reminders. It passes the current Pacific day and time, topic weights, and your steering preference to the model. The Mock brain produces no discovery cards.

A discovery pass makes at most six Exa calls when Search is enabled and Exa is connected. Search queries use followed public topics and a list of general public subjects that match your interests. Hearth strips markup from excerpts and treats them as data. The generator has zero tools. Read and Digest cards link to verified result entries from that pass. Hearth deduplicates URLs in its retained history and avoids repeating a topic within 20 hours. It rechecks note and reminder revisions before displaying a card or opening it in Chat. Forgetting in Memory clears derived Feed cards and interests. [Feed generator](../hearth/feed.py), [Memory and Forget](memory.md)

## Action suggestions and email

Action cards retain the original proactivity schedule and controls under **Settings → Action suggestions**. Hearth checks every two hours by default, also checks for Memory and Inbox changes, and can publish up to three offers per pass. The default limit is three offers per Pacific day. Use **Suggestion options** on an Action card to snooze it for one day or one week, or mute its category. Clear the category preference in `PROACTIVITY_PREFERENCES.md` in Memory to allow it again.

The primary action starts the offered prompt, selected skill, or parallel workers in a side chat. Sending, spending, posting, and deleting still require approval. Timeline records card arrivals and when you start an offer. Hearth rechecks source revisions and skill availability. The Action planner can make one public lookup to ground an offer, and it may use recent chats, Inbox cards, and artifacts in addition to notes and reminders. [Proactivity engine](../hearth/proactivity.py), [Reference collection](../hearth/proactive_context.py)

**Email a daily digest** is off by default. When enabled, Hearth can queue one AgentMail digest of available Action suggestions for the recipient in **Settings → Reminders**. Delivery respects both Action suggestion and Reminder quiet hours and requires a connected inbox and configured recipient.

## Morning brief

Open **Reminders → Recurring tasks → Morning brief**. Use **Run now** for a one-off brief, or enable the weekday 8 AM Pacific schedule. The seeded task starts paused on a new workspace.

The brief assembles today’s reminders, current Action suggestions, the Home location’s weather, and pending approvals. It saves the result in the task’s side chat and Inbox. Select the task’s email delivery to receive it through AgentMail. [Recurring task runner](../hearth/tasks.py)

## Verification and refresh API

```sh
python -m unittest discover -s tests -p 'test_feed.py'
python -m unittest discover -s tests -p 'test_proactivity.py'
```

Within an authenticated workspace, `POST /api/feed/refresh` with an empty JSON object returns the run status and newly generated discovery cards. `GET /api/feed` returns a cursor-paginated page including available Action cards. Use `saved=1` for bookmarks. The token-protected `/api/proactivity/pass` endpoint continues to run and report the Action planner separately.
