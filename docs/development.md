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

The fixtures exercise Home, attachments, Pages, Skills, parallel workers, structured Memory, and For you. [Live Sprite results](../QA-REPORT.md)

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

The fixture listens on loopback port 39519. Set `CHROMIUM_PATH` to use an existing Chromium binary, `HEARTH_QA_URL` to target another fixture, or `HEARTH_QA_SCREENSHOTS` to save captures. [Contrast fixture](../tests/contrast-fixture.py), [Contrast sweep](../tests/contrast.mjs)

## Conventions

- Keep browser features in the existing ES modules and server behavior in `hearth/`. The server's static asset map controls which files the workspace serves.
- Use the shared storage lock and atomic writes for persisted state. Add brain tools through the agent and the approval classifier so chat and scheduled runs use the same policy.
- Test provider integrations with gateway fixtures and use temporary data roots. Keep live credentials, private connector settings, and runtime captures outside tracked files.

[Server](../hearth/server.py), [Storage](../hearth/storage.py), [Tool policies](../hearth/approvals.py), [CI](../.github/workflows/deploy.yml)
