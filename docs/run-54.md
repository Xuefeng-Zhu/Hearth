# Run 54 — Scheduler progress and checkpoint restore

Run 54 implements D04 for reminder scheduling, delivery, and local checkpoint restore.

- The web loop and standalone scheduler claim due occurrences under the same workspace state lock. Quiet hours defer first attempts for non-urgent email. In-app reminders, urgent delivery, and the two-second scheduler cadence keep their existing timing.
- `POST /api/scheduler/tick` reports `fired`, `queued_deliveries`, `last_tick`, and `next_due` after the claim. The queued count covers email work eligible at that instant. Inbox, Home, and recurring-task processing run in the background, so the response no longer includes their completion counts.
- Each web process schedules one delivery worker, and the workspace delivery lock serializes workers across processes. A pass handles up to 12 records. Provider calls run outside the state lock and use an eight-second per-request timeout within a twenty-second attempt budget. If a transport remains blocked after the deadline, the attempt is marked pending reconciliation and retains its delivery lock until the call returns. This allows a late receipt to be recorded safely.
- Restore closes the claim gate across processes and allows two seconds for active work to drain. If an Inbox poll, recurring task, or event automation is still running, restore stops before replacing state. Local restore can continue with an unfinished reminder send because its intent and eventual receipt are recorded in `reminder-delivery.json` outside `live/`.
- Startup and scheduler passes apply journal receipts to live state. When the snapshot predates a due occurrence, the scheduler reuses that occurrence's original ID and provider idempotency key. Retries keep the original recipient, rendered inputs, mailbox, and key. The existing 22-hour cutoff stops automatic retries after the safe reconciliation window.

## Deferred

Native Sprite restore can rewind the entire filesystem, including the local delivery journal. Hearth blocks a native restore if the target checkpoint can erase journaled delivery evidence or a delivery is pending reconciliation. A journal outside the Sprite and recovery for restores invoked outside Hearth are deferred. Other provider effects retain their existing handling. [Sprite checkpoint scope](https://docs.sprites.dev/working-with-sprites/)

## Verification

The regression fixtures use mocked mail and cover a blocked send on both web paths, a subprocess competing for occurrences and respecting the restore barrier, quiet hours, a late receipt across restore, startup replay after a lost response, transport timeout, Inbox drain timeout, and the native restore guard. The original manual tick exceeded the test's 750 ms bound with a blocked mail provider.

- `python -m unittest discover -s tests` passed 249 tests with the pinned test dependencies and the CJK PDF fixture font.
- `node --test tests/*.test.mjs` passed all nine tests. Every `web/*.js` file passed `node --check`.
