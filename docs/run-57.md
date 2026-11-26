# Run 57 · Silent failures and stale status

D09 adds `GET /api/status` for workspace diagnostics. Each subsystem reports its last success, last failure time, last failure code, and cumulative failure count. The endpoint is available during a restore. `/health` reports service liveness.

| Subsystem | Recorded progress and failures |
| --- | --- |
| `http` | Completed successful responses, including 304. Unexpected handler faults return a sanitized 500 when headers are still writable. Request validation and client disconnects leave fault counts alone. |
| `scheduler` | Successful web scheduler iterations and failures such as `storage_error` from state or journal operations. |
| `box_recall` | Full refresh success clears `stale`. Failed listings keep the last snapshot, and partial downloads retain available cached content. The last full success timestamp is saved with the snapshot and reused if a refresh fails after restart. |

The counters and latest failure records are process-local. Diagnostic rows contain fixed subsystem names and error codes, timestamps, and counts. Legacy Box snapshots report an unknown success time until the first full refresh records one.

Chat and affected panels keep their current content through polling failures. Two failed background refreshes show a text indicator beside the view title. It distinguishes offline or disconnected browsers from HTTP faults. The next successful refresh, including a conditional 304, clears the indicator.

## Verification

The new regression tests reproduced the missing status records and indicators before implementation. The Chromium smoke checks the two-failure threshold, cached Home content, Home recovery on 200, Chat recovery on 304, and text contrast of at least 4.5:1 at 390 px in dark mode.

The long-chat tool-loop fixture now suppresses its background Ideas kick so the test can remove its temporary workspace after the reply. An Ideas worker writing during cleanup had caused an intermittent suite error.

| Check | Result |
| --- | --- |
| Python suite | 315 passed |
| Node suite | 9 passed |
| JavaScript syntax | Passed across `web/*.js` |
| Offline Chromium smoke | Passed |

## Deployment and live smoke

`scripts/deploy.sh` succeeded. At 09:47 UTC on November 26, 2026, the running Sprite returned HTTP 200 from `/health`, `/api/status`, and `/api/home`. Sprite checkpoints were enabled, and all 47 checked runtime file hashes matched the deployment candidate.

- Chromium rendered Home using the running Sprite's responses over authenticated CLI execution and the matching deployed assets.
- A live Hugging Face reply streamed and persisted in a temporary workspace running the deployed code on the Sprite.
