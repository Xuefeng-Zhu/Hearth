# Proactivity

**Home → For you** offers timely next steps, such as preparing for a booking, collecting gift ideas, making a shopping workbook from a dinner Page, or checking a missing reminder detail. Each card shows why it’s timely, the work Hearth would do, the urgency, and when the offer expires.

- **Do it** starts a side chat with the offered prompt, a selected skill, or parallel workers. Offers that use a skill disappear if that playbook is deleted. Sending, spending, posting, and deleting require an approval card even when the corresponding workspace approval preference allows the action.
- **Snooze** hides the offer for one day or one week. A still-valid card can return during awake hours, subject to the daily limit and its original expiry.
- **Dismiss** clears the offer. Hearth uses the occasion’s dedupe key and its main reference to limit repeat offers.
- **Not interested in this kind** mutes the category and records a checked line in `PROACTIVITY_PREFERENCES.md`. Clear that line or uncheck it in Memory to allow future suggestions of that kind.

Timeline records each card’s arrival and the user’s **Do it** decision, with a link to the side chat for the latter. The entries carry the category and a suggestion ID. [Proactivity engine](../hearth/proactivity.py)

## Timing and settings

In **Settings → Proactivity**, turn suggestions on or off, set a frequency of 30–720 minutes, change quiet hours, or set a daily cap of 1–12. By default, Hearth checks every two hours while awake, with quiet hours from **10 PM to 7 AM Pacific time**. Quiet hours follow the Pacific clock through daylight saving changes. Set the start and end to the same time to allow checks at any hour.

Hearth also checks for local memory edits and newly imported Inbox cards. Change-triggered checks are spaced at least ten minutes apart. A pass can publish up to three offers, and the default limit is three published or resumed offers per Pacific day. Existing cards remain available until they expire, are handled, or their references become invalid. If the Sprite sleeps, Hearth catches up on wake. [Scheduler wake](deploy.md#wake-the-scheduler)

**Email a daily digest** is off by default. When enabled, the first batch of the day can queue one AgentMail digest for the recipient set in **Settings → Reminders**. The digest lists the day’s still-available offers at delivery time. It respects both Proactivity and Reminder quiet hours. A connected inbox and reminder recipient are required.

## References and privacy

The pass gives the selected brain a bounded set of local references. These include profile and notebook entries in enabled memory folders, reminders, recurring tasks, AgentMail Inbox cards, recent chats, and recent artifacts and Pages. Recent chats are a Proactivity input even when chat indexing for Memory search is off. Disconnect the brain or turn off Proactivity to stop this use. The Mock brain yields an empty For you feed.

Hearth treats references as data and exposes zero action tools to the planner. When Search is enabled and Exa is connected, a pass can make one public lookup for facts such as a forecast or venue hours. Query checks filter known contact names, identifiers, and copied passages. Source previews strip common contact details and booking codes. The card’s one-line explanation paraphrases its source. Hearth rechecks current source revisions and forget rules before showing or accepting an offer. Forgetting in Memory retires cached offers and suppresses matching copies of the forgotten excerpt in other inputs. [Reference collection](../hearth/proactive_context.py), [Memory and Forget](memory.md)

## Morning brief

Open **Reminders → Recurring tasks → Morning brief**. Use **Run now** for a one-off brief, or enable the schedule for weekday 8 AM Pacific delivery. Hearth’s seeded row is paused on a new workspace. Existing schedules and delivery settings are preserved when upgrading the seeded row, and duplicate rows matching the exact built-in template are consolidated.

The brief assembles today’s reminders, current For you suggestions, the Home location’s weather, and items waiting for approval. The built-in brief reads that information directly and saves the result in the task’s side chat and Inbox. Choose the task’s email delivery explicitly if you want the brief through AgentMail. [Recurring task runner](../hearth/tasks.py)

## Local verification

Run the targeted tests and the synthetic browser fixture from the repository root.

```sh
python -m unittest discover -s tests -p 'test_proactivity.py'
PYTHONPATH=. python tests/run33-browser.py --output /tmp/hearth-proactivity
```

The browser fixture uses 390 px and 1440 px viewports in light and dark themes. To diagnose a deployed pass, use the authenticated scheduler token with `POST /api/proactivity/pass` and an empty JSON object. The pass observes quiet hours, daily limits, and deduplication. Use `GET /api/proactivity/pass` with the same token to inspect the last completed attempt, including any offers still available on Home.
