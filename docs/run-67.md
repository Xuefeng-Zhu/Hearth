# Run 67 — Hearth’s self-update merge guard

Hearth keeps GitHub branch protection as the merge guard when it can verify strict required checks. On the unprotected private repository, Hearth checks that the PR is open, mergeable, out of draft, and at the explicitly approved head SHA. It compares that head with current `main` and requires successful GitHub Actions check runs for every configured job on the same head. Settings → Connections → GitHub defaults to `test` and `browser-smoke`.

**Refresh proposal** reapplies the file changes on current `main` and advances the same PR branch. The new head needs fresh CI and an explicit approval. If `main` moves between Hearth’s last read and the squash, the card and Timeline report the difference between the expected base and the squash commit’s parent. [Improve Hearth guide](self-update.md)

## Verification

| Check | Result |
| --- | --- |
| Python unittest discovery | 330 tests passed, including 15 self-update tests |
| Node test runner | 20 tests passed |
| JavaScript syntax | 28 files checked |
| Offline Chromium smoke | Passed at 390 px and 1440 px in light and dark |
| Chromium stream disconnect | Passed |
| Sprite deploy | `scripts/deploy.sh` succeeded. `/health` returned HTTP 200 with version `156e564c4ac851ed20284ce1facbc1ae3b086444`. |

The mocked gateway covers the strict and fallback guards, failed and missing jobs, cancelled and non-success conclusions, draft and unmergeable PRs, changed heads, waiting and re-polling, refreshed approvals, and a base move during a squash. Deploy tracking and the revert proposal use the Run 66 flow.

## Live Sprite check

On 2026-11-26, a temporary chat requested one additional line in `docs/self-update.md`. Hearth opened PR #2 with one addition in that file. GitHub reported that `main` was unprotected and the proposal head was zero commits behind. Both required jobs succeeded on head `aae27657592c9761d6249235ee0d9414e25999d3`. [Pull request](https://github.com/Xuefeng-Zhu/Hearth/pull/2) · [GitHub Actions run](https://github.com/Xuefeng-Zhu/Hearth/actions/runs/45863786238)

The Sprites connector returned HTTP 400 for the GitHub REST compare route. Hearth now falls back to GitHub's read-only GraphQL comparison and verifies both returned commit SHAs before using the behind count. [GitHub comparison fields](https://docs.github.com/en/graphql/reference/commits#comparison)

Mobile Chromium displayed **Ready to merge**, **Tests passed**, the proposal head SHA, and **Hearth's own checks: tests passed on an up-to-date branch**. The browser used a temporary authenticated CLI relay. Clicking **Discard** closed the PR unmerged and deleted its branch. Connector reads verified both outcomes, the temporary chat was deleted, and remote `main` stayed at `6415794`.
