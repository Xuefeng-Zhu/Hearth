# Run 66 — Improve Hearth

## Live Sprite check

On 2026-11-26, `scripts/deploy.sh` deployed `b9d34c885b0a4ef4c3d13f2e22f89d8c92996f12`. The running service returned HTTP 200 from `/health`, and Settings → About displayed the same commit. Settings → Connections showed the GitHub repository and its enabled proposal toggle.

A temporary chat asked Hearth to add one timestamped line to `docs/self-update.md`. That file was absent on the GitHub default branch, so the proposal added the one-line file. Hearth opened [PR #1](https://github.com/Xuefeng-Zhu/Hearth/pull/1). A separate gateway read confirmed the open PR and matched its head SHA to the proposal branch. The live card displayed the file, line count, diff, link, and controls in mobile Chromium. Clicking **Discard** closed the PR and deleted the branch. Connector reads verified the PR was closed and unmerged and the branch was gone. The temporary chat was deleted. Timeline retained the proposal and discard entries.

The Sprite TCP tunnel reset connections, so Playwright used an authenticated CLI HTTP relay with assets verified against the deployed release. The relay was stopped after verification.

GitHub reported that `main` was unprotected and its classic branch-protection endpoint returned HTTP 403. Chat approval can squash-merge only after the connector can verify that GitHub enforces up-to-date required checks on the base, applies the rule to administrators, and disallows force pushes. The waiting, failure, squash, deploy, and revert paths were exercised against the mocked gateway. The live verification exercised proposal and discard only. The commits remain local.

## Test results

| Check | Result |
| --- | --- |
| Reminder tick auth / cross-origin test | 30 consecutive passes |
| Python unittest discovery | 323 passed, including 8 self-update tests |
| Node test runner | 19 passed |
| JavaScript syntax | 28 files checked |
| Browser smoke | Chromium passed, including 390 px and 1440 px in light and dark |
| Stream disconnect smoke | Chromium passed |

The approval-card smoke checks touch targets of at least 44 px, WCAG AA text contrast, viewport overflow, keyboard focus in revision feedback, diff expansion, the waiting state, and one polite completion announcement. The full Python suite also exposed two unrelated fixture teardown races. The model-fallback and scheduler-health fixtures now isolate the background workers they do not exercise.
