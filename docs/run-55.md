# Run 55 · HTTP boundaries

Started from `main` with D06 (`591ddd6`) and D04 (`8a415cb`) already merged. Commit `bd4cc23` added the boundary tests first. They reproduced 39 failures on the baseline.

## Request policy

- The [route registry](../hearth/http_routes.py) lists exact method and path pairs. Screenshot names, page IDs, page versions, and share tokens each have a full-match path pattern. Query strings are parsed separately. Unknown paths return 404. A known path with the wrong method returns 405 and lists its supported methods in `Allow`.
- Every JSON route requires a UTF-8 object and rejects undeclared top-level fields. The registry lists required and optional fields and their types. Fixed nested objects, including automation schedules, triggers, actions, and call transcript entries, also reject undeclared fields. Approval edits use the pending action’s editable fields. Saved daily and weekly schedules can include their derived `cron` field. Page actions accept the selection fields sent by the page editor.
- Invalid framing or JSON returns 400. This covers duplicate keys, non-finite numbers, and malformed UTF-8. An oversized body returns 413 before it is read. The limit is 24,000 bytes for standard JSON and file questions, 48,000 for event automation writes, 160,000 for Memory and Skills routes using the large JSON limit, 1 MiB for other Artifact writes, and 512 KiB for call reports. Audio is capped at 8 MiB. Multipart uploads allow a 20 MiB file plus up to 16 KiB of framing. The scheduler tick takes an empty body.
- Automation validation errors return 400. I/O failures and malformed workspace data return 500 with a fixed message. Restore-time requests return 503 with `Retry-After: 2`. Static assets, Health, State, and Home remain readable so the browser can check restore progress. Origin and scheduler token checks still apply.
- The HTTP layer validates shape and transports JSON, audio, and multipart uploads. Domain services still check values against business rules and workspace state. The HTTP layer turns a started restore into the existing 202 response and keeps the browser’s response payloads and chat event format.

## Verification

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests` | 312 passed |
| `node --test tests/*.test.mjs` | 9 passed |
| `node --check` for `web/*.js` | 25 files passed |
| Offline Chromium smoke | Passed |

## Deployment and live smoke

`scripts/deploy.sh` succeeded. At 09:30 UTC on November 26, 2026, the running Sprite returned HTTP 200 from `/health` with Sprite checkpoints enabled. All 49 checked runtime files matched the deployed hashes.

- A chat reply streamed from the live Hugging Face connector and persisted in a temporary workspace running the deployed code.
- Chromium rendered Home and Settings → Automations using live API responses from the running Sprite and static assets with matching deployed hashes. The event automations and recurring task lists returned 200 with their expected response shapes.
- A GET to `/api/chat` returned 405 with `Allow: POST`.

The direct edge request returned 401 with the available credential, and the Sprite port tunnel reset its connection. The smoke checks used authenticated Sprite CLI execution and the running service’s loopback HTTP listener.
