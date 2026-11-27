# Development

Use Python 3.12 and Node.js 22 to match CI. From the repository root, create a virtual environment and install the test dependencies.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-test.txt
```

On Debian-compatible development hosts, install the same Chinese PDF font as CI. This requires `curl`, `dpkg-deb`, and `sha256sum`. On other hosts, set `HEARTH_CJK_FONT` to a local WenQuanYi Micro Hei font file. [Font installer](../scripts/install-office-font.sh)

```sh
scripts/install-office-font.sh .hearth/fonts
export HEARTH_CJK_FONT="$PWD/.hearth/fonts/wqy-microhei.ttc"
python -m unittest discover -s tests
node --test tests/*.test.mjs
find web -type f \( -name '*.js' -o -name '*.mjs' \) -exec sh -c '
  for file do
    node --check "$file" || exit 1
  done
' sh {} +
```

## Playwright

The test requirements include Playwright. Run these commands from the repository root. Add `--with-deps` to the install command on Linux if system libraries are missing.

```sh
python -m playwright install --only-shell chromium
PYTHONPATH=. python tests/browser-smoke.py
PYTHONPATH=. python tests/browser-smoke.py --disconnect
PYTHONPATH=. python tests/browser-smoke.py --chat-search
PYTHONPATH=. python tests/browser-smoke.py --list-search
PYTHONPATH=. python tests/browser-smoke.py --motion
```

The default smoke uses temporary workspaces and offline fixtures, and runs the Settings, searchable combobox, Chat search, list search, and motion helpers. Use one flag per invocation. `--disconnect` checks stream recovery, `--chat-search` and `--list-search` add 390–1920 px overflow sweeps, and `--motion` isolates view transitions, reduced motion, and focus. The default and disconnect commands are the deploy gates. [Browser entry point](../tests/browser-smoke.py), [Chat search smoke](../tests/chat_search_smoke.py), [Settings smoke](../tests/settings_smoke.py), [Motion smoke](../tests/motion_smoke.py)

### WebKit and Firefox

Install the other Playwright browsers with `python -m playwright install webkit firefox`. The smoke entry point launches Chromium. For an engine-specific fixture, launch `playwright.webkit` or `playwright.firefox` and reuse the temporary workspace and page helpers. In Run 85 on Linux ARM64, WebKitGTK crashed on normal-motion view transitions, including on a standalone example. The full WebKit flow used `reduced_motion="reduce"`. Playwright screenshot capture also triggered an inline stylesheet CSP warning in WebKit. The isolated probe observed it only after capture. Firefox contexts omitted `is_mobile` and used explicit viewport sizes. Firefox crashed in the extra 390 px touch geometry check when opening Home’s Add panel sheet on both revisions. Targeted Firefox attachment and Home mutation checks passed with reduced motion. The tested phone layouts used emulation. [Run 85 browser matrix](run-85.md#local--browser-flow-matrix)

### Earlier browser fixtures

Run the browser regressions from the repository root. The first two scripts use `--shots` and the remaining scripts use `--output`. Each script accepts `--chromium` to use an existing browser binary.

```sh
export PYTHONPATH=.
for run in 21 22; do
  python "tests/run$run-browser.py" --shots "/tmp/hearth-browser-$run" || exit
done
for run in 25 30 31 32 33; do
  python "tests/run$run-browser.py" --output "/tmp/hearth-browser-$run" || exit
done
```

The fixtures exercise Home, attachments, Pages, Settings → Connections, the Skills library, parallel workers, structured Memory, and For you. The navigation, Connections, and Skills checks include 375, 390, and 1440 px in light and dark themes.

The Run 38 drawer and Settings fixture prefers WebKit and can use Chromium with phone emulation. It seeds 12 side chats with long titles and checks navigation, truncation, the pinned Settings button, and legacy bookmarks. The fixture predates the current Settings panels. Use the current Settings smoke for coverage of the migrated view. [Run 38 fixture](../tests/run38-browser.py), [Settings smoke](../tests/settings_smoke.py)

```sh
python -m playwright install webkit
PYTHONPATH=. python tests/run38-browser.py --output /tmp/hearth-browser-38
```

The Run 39 WebKit regression checks 375×667, 390×844, and 1440×1000 in both themes. It exercises every workspace page, measures pane overflow and mobile touch targets, samples WCAG AA contrast, and checks thread status and simulated visual-viewport changes. Pass `--output` to save screenshots and reports with fictional data. [Audit](../UX-AUDIT.md)

```sh
PYTHONPATH=. python tests/run39-browser.py --output /tmp/hearth-browser-39
```

The Run 43 WebKit fixture exercises Memory review at 390×844 and 375×667 in dark mode with fictional notes. It checks the settings, Feed card, individual and bulk review actions, and Timeline Undo. It also measures touch targets, overflow, and WCAG AA contrast on the review surfaces.

```sh
PYTHONPATH=. python tests/run43-browser.py --output /tmp/hearth-browser-43
```

The Run 47 WebKit fixture checks Ideas, approvals, goal editing, panel layout, and Timeline Undo in dark mode at 390×844 and 375×667. It uses a fake brain and fictional workspace data.

```sh
PYTHONPATH=. python tests/run47-browser.py --output /tmp/hearth-browser-47
```

The contrast sweep uses Node Playwright. The following commands install it in a temporary directory and start an isolated fixture server.

```sh
browser_deps=$(mktemp -d)
npm install --prefix "$browser_deps" --no-save playwright
"$browser_deps/node_modules/.bin/playwright" install chromium
PYTHONPATH=. python tests/contrast-fixture.py
```

In a second terminal, set `PLAYWRIGHT_PATH` to the path ending in `node_modules/playwright` from the installer above. Then run the sweep.

```sh
node tests/contrast.mjs
```

The fixture listens on loopback port 39519. Set `CHROMIUM_PATH` to use an existing Chromium binary, `HEARTH_QA_URL` to target another fixture, or `HEARTH_QA_SCREENSHOTS` to save captures. [Contrast fixture](../tests/contrast-fixture.py), [Contrast sweep](../tests/contrast.mjs), [Live Sprite results](../QA-REPORT.md)

## Add a workspace view

1. Add the view’s section to `web/index.html` with an ID of the form `<name>-view` and a matching `data-view="<name>"` button in the desktop sidebar and mobile drawer.
2. Put the Preact components in `web/<name>/view.js` and the data loading and actions in a controller, following Reminders or Timeline. Render into a stable host with `render` from `preact` and the shared htm binding. Use stable keys for list items and keep any native dialog or input mount stable across refreshes.
3. Import and mount the view in `web/app.js`, wire its loader into `refreshView` and its entry into `openView`, and add any bookmark handling to the workspace router. For a view that polls, add its refresh path to `viewRefreshPaths` and wire the refresh into `pollForeground`.
4. Add the module URLs and any new stylesheets to the server’s `STATIC` allowlist. Verify navigation, focus, and refresh behavior with the offline browser fixture.

[Shell and navigation](../web/index.html), [View wiring](../web/app.js), [Reminders mount](../web/reminders/view.js), [Reminders controller](../web/reminders/workspace.js), [Static allowlist](../hearth/server.py)

## Update vendored frontend dependencies

1. Copy the published browser ES modules and licenses into `web/vendor/`, keeping Preact and its hooks on the same version. The hooks module should import the bare specifier `preact` so both resolve to the same core.
2. Update the versioned filenames in the inline import map in `web/index.html` and the matching `STATIC` entries in `hearth/server.py`. Serve the modules as `text/javascript`.
3. Recompute `WORKSPACE_IMPORT_MAP_HASH` after the last edit to the map. Hash the bytes between the script tags, including indentation and newlines. Use the command below to print the value for the server constant.
4. Run the syntax checks, Python suite, and default browser smoke above. The HTTP test verifies that the served map matches the CSP hash and that the mapped modules are served with the expected content type.

```sh
python - <<'PY'
import base64
import hashlib
import re
from pathlib import Path

index = Path("web/index.html").read_bytes()
body = re.search(rb'<script type="importmap">(.*?)</script>', index, re.DOTALL)[1]
print("sha256-" + base64.b64encode(hashlib.sha256(body).digest()).decode("ascii"))
PY
```

[Vendored modules](../web/vendor/), [Import map](../web/index.html), [CSP and static assets](../hearth/server.py), [HTTP test](../tests/test_hearth.py)

## Conventions

- Keep browser features in the existing ES modules and server behavior in `hearth/`. Register new assets in the static asset map. Keep stream decoding in `web/sse.js` and Chat stream, snapshot, and page reconciliation in `web/chat-state.js` so the Node suite can exercise them independently of the DOM.
- Add HTTP handlers through `hearth/http_routes.py` with their method, body schema and limit, and applicable origin, token, and restore policy. Keep business and workspace validation in the service.
- Use the shared storage lock and atomic writes for persisted state and advance the relevant polling revision on writes. Use the web scheduler's claim and delivery paths for scheduled work. Keep model or provider calls outside the workspace state lock. Add brain tools through the shared tool handling and approval classifier so chat, workers, and scheduled runs use the same policy.
- Test provider integrations with gateway fixtures and use temporary data roots. Keep live credentials, private connector settings, and runtime captures outside tracked files.

[Route registry](../hearth/http_routes.py), [Storage](../hearth/storage.py), [Tool policies](../hearth/approvals.py), [CI](../.github/workflows/deploy.yml)
