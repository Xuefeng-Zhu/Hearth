# Testing Hearth

See the [development guide](development.md) for the Python suite, Node tests, and JavaScript syntax checks.

## Runs 85 and 86 verification

Run 85 walked through the deployed workspace in read-only Chromium at 1440 × 900 and 390 × 844 in light and dark. Local Playwright fixtures exercised streaming, Stop, attachments, side chats, reminders and recurring tasks, Inbox review, Artifacts, Skills, Memory, Settings, Home layout, and the voice UI in Chromium 159, WebKitGTK 27.2, and Firefox 159. WebKit used reduced motion after a graphics crash on normal-motion view transitions on the Linux ARM64 host. Firefox’s additional emulated-touch geometry check crashed at 390 px. The local attachment and Home mutation checks passed in a targeted Firefox rerun with reduced motion. [Run 85 full-flow QA](run-85.md), [Engine notes](development.md#webkit-and-firefox)

Run 85 found that clicking a desktop Chat search result dismissed the popover before jumping. Run 86 fixed the dismissal boundary. The pointer-click regression passed in Chromium and Firefox with normal motion and in WebKit with reduced motion. The local voice checks used fake media, mocked speech recognition, and a mocked Vocal Bridge SDK. A real microphone, a real Vocal Bridge call, and a physical iPhone were outside coverage. [Run 86 pointer fix](run-86.md), [Voice test coverage](run-85.md#local--browser-flow-matrix)

| Check | Result |
| --- | --- |
| Python suite with the CJK font | 342 passed in Runs 85 and 86 |
| Node unit tests | 37 passed in both runs |
| JavaScript syntax | 63 frontend modules passed in both runs |
| Offline Chromium | Default smoke, stream disconnect, Chat search, list search, and motion passed in both runs |

## Offline Chromium smoke

Run the smoke from the repository root with the pinned test dependencies installed.

```sh
python -m playwright install --only-shell chromium
PYTHONPATH=. python tests/browser-smoke.py
PYTHONPATH=. python tests/browser-smoke.py --disconnect
```

Add `--with-deps` to the install command if Chromium needs Linux system libraries. In the ARM workspace, set `LD_LIBRARY_PATH=/workspace/tools/chromelibs/usr/lib/aarch64-linux-gnu` when launching the test. Set `PLAYWRIGHT_BROWSERS_PATH` if Chromium was installed outside Playwright’s default cache.

The smoke starts Hearth on a random loopback port with temporary data, the mock model, empty connector discovery, and browser requests restricted to the local server. It checks Settings, the 390 × 844 drawer, Home panel creation and restoration, thread actions, searchable selects, Chat and list search, motion, and the self-update card. Chat coverage includes keyboard send and Stop, focus during a mid-stream thread switch, and one live-region update per completed reply. The stale-data check verifies that two consecutive background failures show a stale indicator and that a later `200` or `304` clears it. Accessibility assertions cover focus, live-region DOM updates, and sampled contrast. [Smoke entry point](../tests/browser-smoke.py), [Targeted smoke commands](development.md#playwright)

The disconnect regression aborts the Chat request after the first visible token and lets the server persist the reply. It checks that polling replaces the partial bubble, announces the saved reply once, and keeps the announcement count unchanged after another refresh. The deploy workflow caches Chromium and requires both browser checks and the unit test job to pass. [Workflow](../.github/workflows/deploy.yml)

## Signed-out edge authorization matrix

Run [scripts/check-edge-auth.sh](../scripts/check-edge-auth.sh) from a host that can reach both deployed origins. Use a disposable test workspace and non-sensitive fixtures. While signed in, copy the path and query of an artifact file and the path of a private Page. Approve two public Page shares, keep one active, and copy the other URL before revoking it. Supply these values as environment variables in your shell.

| Variable | Fixture |
| --- | --- |
| `HEARTH_BASE_URL` | Origin of the private workspace, with Sprite authentication enabled |
| `HEARTH_ARTIFACT_PATH` | Existing workspace artifact path and query, of the form `/api/artifacts/file?id=…` |
| `HEARTH_PAGE_PATH` | Existing private Page path, of the form `/pages/<id>` or `/pages/<id>/v/<version>` |
| `HEARTH_PAGE_SHARE_URL` | Active `/p/<token>` URL on the separate public Pages origin |
| `HEARTH_REVOKED_PAGE_SHARE_URL` | Previously approved, now revoked `/p/<token>` URL on that origin |

```sh
scripts/check-edge-auth.sh
```

| Anonymous request | Expected first response |
| --- | --- |
| GET and POST on the workspace for `/health`, `/api/state`, `/api/chat`, the artifact, the private Page, and the active token path | 401 or a redirect with a valid Location |
| GET and HEAD to the active token on the public Pages origin | 200 with an HTML content type |
| GET with a missing, malformed, unknown, or revoked token on the public Pages origin | 404 |
| GET to sampled workspace routes on the public Pages origin | 404 |

The script sends no cookies or authorization headers and stops at the first response without following redirects. Inspect the edge configuration separately to confirm login. Each POST sends an empty JSON object. Results print fixture labels and status codes, and any mismatch causes a nonzero exit. Keep fixture values out of commits and logs. The live matrix is manual. Its URL, status, and redirect parsing tests run in the regular Python suite. [Edge-check implementation](../scripts/check_edge_auth.py), [Edge-check tests](../tests/test_edge_auth.py)

## Run 63 verification

Run 63 verified `6ee3a23` with 315 Python tests, 16 Node tests, syntax checks for 27 frontend modules, and both offline Chromium runs. All 23 signed-out edge checks passed against loopback fixtures, and the matrix rejected a fixture that exposed anonymous health. [Run 63 design-review status](../DESIGN-REVIEW.md#run-63-status)
