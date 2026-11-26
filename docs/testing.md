# Testing Hearth

See the [development guide](development.md) for the Python suite, Node tests, and JavaScript syntax checks.

## Run 63 verification

Run 63 verified `main` at `6ee3a23` using Python 3.12, Node.js 22, the pinned requirements, and the project's Chinese PDF font.

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests` | 315 passed |
| `node --test tests/*.test.mjs` | 16 passed |
| `node --check` for `web/*.js` | 27 files passed |
| Offline Chromium smoke and stream disconnect | Both passed |
| Signed-out edge matrix on loopback fixtures | All 23 checks passed. A fixture that exposed anonymous health was rejected. |

The Python suite covers conditional polling and paging, worker storage faults, delivery during restore, summary recovery, Box cache and transfers, HTTP validation, subsystem status, untrusted content, and edge-check parsing. The browser checks use local fixtures. Live connector probes and the deployed edge matrix are outside this run. [Python tests](../tests/), [Design-review status](../DESIGN-REVIEW.md#run-63-status)

## Offline Chromium smoke

Run the smoke from the repository root with the pinned test dependencies installed.

```sh
python -m playwright install --only-shell chromium
PYTHONPATH=. python tests/browser-smoke.py
PYTHONPATH=. python tests/browser-smoke.py --disconnect
```

Add `--with-deps` to the install command if Chromium needs Linux system libraries. In the ARM workspace, set `LD_LIBRARY_PATH=/workspace/tools/chromelibs/usr/lib/aarch64-linux-gnu` when launching the test. Set `PLAYWRIGHT_BROWSERS_PATH` if Chromium was installed outside Playwright’s default cache.

The smoke starts Hearth on a random loopback port with temporary data, the mock model, empty connector discovery, and browser requests restricted to the local server. It checks Home, Settings, the 390×844 drawer, keyboard send and Stop, focus during a mid-stream thread switch, and one live-region update per completed reply. It also checks that two consecutive background failures mark the view stale while keeping existing content visible and that later `200` or `304` responses clear the indicator. Accessibility assertions cover focus, live-region DOM updates, and sampled contrast.

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
