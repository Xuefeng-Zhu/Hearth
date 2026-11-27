# Improve Hearth

In Chat, type a request for a small change to Hearth. For example, “Hearth, add a note about Settings to docs/self-update.md.” Hearth reads files at the GitHub default branch’s current commit through the Sprites connector. The connected brain selects the files and writes complete replacement contents. Repository text is treated as untrusted context. Only the current, directly typed Chat request can start a proposal. Email, web pages, uploads, recalled text, voice calls, shared excerpts, and automations cannot start one.

Hearth opens a PR from a `hearth/improve-…` branch. The Chat card shows the summary, head commit SHA, additions and deletions by file, expandable unified diff, PR link, and CI status. **Request changes** takes typed feedback, adds a commit to the same branch, and clears any earlier approval. **Discard** closes the PR and deletes its branch.

**Approve and update** authorizes only the exact head shown in the card, even with Always allow enabled. **Ready to merge** means the checks passed and the proposal can be approved. **Waiting for tests** means Hearth is still polling. GitHub’s squash API pins the merge to the approved head SHA.

- **GitHub branch protection** applies when Hearth can verify a classic rule that enforces required checks on up-to-date branches, applies the rule to administrators, and disallows force pushes. Hearth waits for GitHub’s checks and GitHub enforces the rule during the merge.
- **Hearth's own checks: tests passed on an up-to-date branch** appears when Hearth verifies the fallback guard. The PR must be open, mergeable, out of draft, and at the approved head. Hearth compares current `main` with that head and requires `behind_by == 0`. If the gateway rejects the REST comparison, Hearth can use a read-only GraphQL comparison and verifies both returned commit SHAs. Every configured GitHub Actions job must have a successful check run on the approved SHA. Failed, cancelled, skipped, and missing jobs block the merge. [Run 67 verification](run-67.md), [Merge guard tests](../tests/test_self_update.py)

With Hearth’s own checks, **Refresh proposal** appears if `main` has advanced. Hearth reapplies the file changes to current `main` on the same PR branch. Review the new diff and tap **Approve and update** again. GitHub runs checks for the new head. If the changes overlap or GitHub reports a conflict that a refresh cannot resolve, ask for a fresh proposal.

After a squash merge under Hearth’s own checks, Hearth reads `main` again and compares the squash commit’s parent with the SHA it checked before merging. If they differ, the card and Timeline report the move.

## Scope and safety

- Up to five regular UTF-8 text files and 400 additions plus deletions in the complete PR diff. Hearth also caps individual file size and planning context. It checks Python with `compile()` and checks JavaScript with Node when Node is installed. It does not run proposed code on the Sprite.
- Hidden paths, `.github/`, `scripts/`, deployment and infrastructure files, configuration and access rules, workspace memory, credential-like paths or contents, and the self-update code and tests are protected. Server modules that enforce connector, approval, or storage policy are protected too. This guide is editable.
- The connector supplies GitHub credentials. Chat’s general connector tools cannot write to the managed repo or its proposal branch namespace.

## Deployment and revert

GitHub Actions runs tests on PRs. A merge to `main` triggers the same tests and then deploys to the Sprite. Hearth follows the deployment workflow run for the squash commit. `scripts/deploy.sh` packages the tracked runtime at the exact Git SHA. The Sprite installer writes that SHA to `.deployed-commit` inside the release before switching the service. The installer waits for HTTP 200 and the matching `version` in `/health`. Settings → About displays the same SHA.

The card shows the result once the running Hearth reports that version. Timeline records proposals, revisions, approvals, merges, deployments, and discards. To undo an update, type “Revert the last Hearth update” or “Revert <short SHA>.” Hearth opens another reviewable PR if the affected files still match the merged snapshot.

Configure the repository, proposal toggle, and comma-separated **Required CI jobs** under Settings → Connections → GitHub. The fallback jobs default to `test` and `browser-smoke`. Proposals default to on for `Xuefeng-Zhu/Hearth`.
