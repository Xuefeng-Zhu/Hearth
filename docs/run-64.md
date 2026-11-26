# Run 64 · Integration on main

- Merged D06 in `591ddd6`. State and Home use revision-keyed snapshots and conditional GETs. Chat history is paged, and the browser adapts polling to activity and tab visibility. The D10 summary hooks and the D12 and D13 cache handling remain wired into chat and restore.
- Merged D04 in `8a415cb`. Scheduler claims and delivery run separately. Restore holds the scheduler barrier and reconciles reminder delivery from the journal. Local restore also advances both workspace and thread revisions so cached State and Home snapshots refresh. The restore regression checks that both routes return fresh data with new ETags, then return 304 on unchanged requests.
- Updated the worker fault tests in `496e54f` to pass the scheduler barrier through their restore wrapper. The initial full run failed three tests at that wrapper. All three passed after the fix.

## Verification

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests` | 304 passed, including 8 polling tests |
| `node --test tests/*.test.mjs` | 9 passed |
| `node --check` for `web/*.js` | 25 files passed |
| Offline Chromium smoke | 1 run passed |
| D06 Playwright polling fixture | 2 runs passed, desktop Chromium and mobile WebKit |

The polling fixture covered paged history and scroll position on both browsers. Desktop also checked idle and active polling, hidden-tab pause, focus refresh, sidebar overflow, streaming, Stop, and a Home 304. Mail delivery tests used mocked transport. Zero real emails were sent by the tests.

## Deployment and live smoke

`scripts/deploy.sh` succeeded. On November 26, 2026 at 09:11 UTC, the deployed Sprite returned HTTP 200 from `/health` with Sprite checkpoints enabled. Eight runtime source hashes matched the local tree.

- Home and `/api/home` returned HTTP 200 on the running service.
- An unchanged `/api/state` request returned HTTP 304 with the same ETag and an empty body.
- One arithmetic reply and one Exa-backed reply streamed and persisted. The Exa reply cited a source from the live search results. Both chats used the deployed code and live connectors in a temporary workspace on the Sprite.

Live Home verification used HTTP from inside the Sprite. The direct edge browser request returned 401 with the available credential, and the CLI tunnel reset the browser connection. The offline Chromium smoke verified Home rendering.
