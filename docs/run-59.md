# Run 59 — Box and artifact I/O

D13 in the [design review](../DESIGN-REVIEW.md) is complete on `d13-box-io`.

- `GET /api/artifacts` returns local rows, Pages, and the cached Box listing. `box_status` reports `fresh`, `stale`, or `refreshing`. `box_refreshed_at` reports the last successful refresh and is null on a cold cache. A successful snapshot is fresh for 30 seconds. A failed walk retains the previous snapshot and retries on demand after five seconds. The Artifacts view checks for completion while visible, and its Refresh button requests a background refresh immediately.
- Each folder walk runs outside the artifact lock. A walk for a previous Box account, folder, or checkpoint cannot overwrite the current cache. File questions and explicit memory refreshes still wait for a scoped Box snapshot.
- Generated-file writes, retries, and artifact undo release the artifact and workspace locks during generation and Box I/O. Metadata commits validate the artifact revision and workspace checkpoint. Same-artifact mutations cannot overwrite an in-flight receipt. Box version uploads retain `If-Match`, including when a remote edit lands after Hearth's metadata check.
- Box multipart uploads read the staged file in 64 KiB chunks. Remote downloads spool in bounded chunks before Hearth sends the HTTP response. Local artifact downloads stream from disk. The 50 MiB limit and existing download headers are preserved.

## Verification

- `python -m unittest discover -s tests` passed 250 tests with the repository's test dependencies and the CJK PDF font. The new cases exercised blocked refreshes and uploads, concurrent edits, checkpoint restore during retry, bounded transfers, and the Box revision precondition.
- `node --test tests/*.test.mjs` passed 9 tests. Every `web/*.js` file passed `node --check`.
- A local Chromium smoke test verified that local artifacts appear during a cold refresh, Box rows appear automatically when it completes, and the Refresh button keeps cached rows visible during the next walk.
- All Box traffic was mocked. The branch was committed locally.
