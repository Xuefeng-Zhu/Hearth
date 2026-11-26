# Testing Hearth

See the [development guide](development.md) for the Python suite, Node tests, and JavaScript syntax checks.

## Offline Chromium smoke

Run the smoke from the repository root with the pinned test dependencies installed.

```sh
python -m playwright install --only-shell chromium
PYTHONPATH=. python tests/browser-smoke.py
```

Add `--with-deps` to the install command if Chromium needs Linux system libraries. In the ARM workspace, set `LD_LIBRARY_PATH=/workspace/tools/chromelibs/usr/lib/aarch64-linux-gnu` when launching the test. Set `PLAYWRIGHT_BROWSERS_PATH` if Chromium was installed outside Playwright’s default cache.

The smoke starts Hearth on a random loopback port with temporary data, the mock model, empty connector discovery, and browser requests restricted to the local server. It checks Home, Settings, the 390×844 drawer, keyboard send and Stop, focus during a mid-stream thread switch, and one live-region update per completed reply.

Run the stream disconnect regression with `PYTHONPATH=. python tests/browser-smoke.py --disconnect`. It aborts the Chat request after the first visible token and lets the server persist the reply. It checks that polling replaces the partial bubble, announces the saved reply once, and keeps the announcement count unchanged after another refresh. The deploy workflow caches Chromium and requires both browser checks and the unit test job to pass. [Workflow](../.github/workflows/deploy.yml)

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

The script uses an anonymous client without cookies or authorization headers and reports the first status it receives. Each POST sends an empty JSON object. Results print fixture labels and status codes so the workspace URL and share tokens stay out of the output. Keep fixture values out of commits and logs. The live matrix is manual. Its URL, status, and redirect parsing tests run in the regular Python suite.
