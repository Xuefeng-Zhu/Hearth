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
for file in web/*.js; do node --check "$file" || exit; done
```

## Playwright

The Python requirements include Playwright. Install Chromium with `python -m playwright install chromium` to run the Python browser fixtures. Use `--with-deps` on a Linux host that needs browser system libraries. Browser fixtures exercise desktop and touch layouts in light and dark themes.

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

The drawer and Settings screenshot fixture prefers WebKit and falls back to Chromium with iPhone emulation when WebKit cannot launch. It checks both themes at 375×667 and 390×844 on phones and 1440×1000 on desktop. The fixture seeds 12 side chats with long titles and checks that every workspace link fits before scrolling, thread titles truncate, and Settings stays pinned while the drawer scrolls. It also exercises all 11 Settings disclosures, the Skills page, and former Connections and Skills bookmarks. [Browser fixture](../tests/run38-browser.py)

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

## Conventions

- Keep browser features in the existing ES modules and server behavior in `hearth/`. The server's static asset map controls which files the workspace serves.
- Use the shared storage lock and atomic writes for persisted state. Add brain tools through the agent and the approval classifier so chat and scheduled runs use the same policy.
- Test provider integrations with gateway fixtures and use temporary data roots. Keep live credentials, private connector settings, and runtime captures outside tracked files.

[Server](../hearth/server.py), [Storage](../hearth/storage.py), [Tool policies](../hearth/approvals.py), [CI](../.github/workflows/deploy.yml)
