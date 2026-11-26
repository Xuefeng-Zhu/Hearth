# Run 53 — Worker lifecycle and storage failure

Run 53 resolves D03 in the [design review](../DESIGN-REVIEW.md).

Queue and start persist worker status before registering the worker or reserving an executor slot. A failed write ends that assignment with “Hearth could not save the worker’s status.” Other workers in the batch can continue. Finish releases the executor slot, removes the worker from the active pool, and wakes batch waiters even when the terminal write fails.

Hearth reloads the last durable state before reconciling a worker and saves any related approval withdrawals in the same write. If writes remain unavailable, the turn receives the sanitized failure immediately and the pool retries the durable update on later dispatch or Stop all. Startup recovery also resolves interrupted workers. Checkpoint restore is available once actual in-flight worker tools have drained.

## Local verification

The fault tests cover queue, start, and finish writes, cancellation during Stop all, reconciliation after writes resume, and executor submission failures. They verify slot release, waiter notification, sanitized worker events, durable state, and local checkpoint restore.

- `python -m unittest discover -s tests` passed 247 tests with the pinned test requirements and the project’s PDF font.
- `node --test tests/*.test.mjs` passed 9 tests.
- `node --check` passed for all 25 `web/*.js` files.
