# Run 56 — Rolling summaries

Rolling summaries share a two-worker executor per process. Jobs coalesce by workspace and thread across agent instances. A queued update reads the latest dialogue. Triggers during an active update can queue one follow-up.

- A thread’s `summary.pending` marker persists from enqueue through completion. A summary-enabled agent picks up markers on startup. Provider failures retain the marker for a later startup or reply.
- Chat reads a corrupt summary as empty. The updater rechecks the file under the workspace lock, records a content-free `summary.corrupt` marker, and removes the invalid file. It rebuilds the summary from eligible dialogue at the usual threshold.
- Updates use the existing model preference and fallback and save the summary text and cursor in the existing format. The commit checks the current agent, thread membership, forget rules, and prior summary state so an in-flight result cannot overwrite a reset or restore forgotten information.

## Verification

- `python -m unittest discover -s tests` passed all 247 tests with the pinned requirements and the project’s CJK font. The rolling-summary suite covers the worker cap, coalescing, startup recovery, corrupt summaries, cursor advancement, reset, permanent forget, and agent replacement.
- `node --test tests/*.test.mjs` passed all 9 tests. `node --check` passed for all 25 files matched by `web/*.js`.
- A separate process exited during a summary model call. A fresh agent recovered the marker on startup, saved the summary and cursor, and cleared the marker.
- The application startup path also drained a pending marker after connector discovery with a fake gateway.
