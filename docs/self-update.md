# Improve Hearth

In Chat, type a request for a small change to Hearth. For example, “Hearth, add a note about Settings to docs/self-update.md.” Hearth reads files at the GitHub default branch’s current commit through the Sprites connector. The connected brain selects the files and writes complete replacement contents. Repository text is treated as untrusted context. Only the current, directly typed Chat request can start a proposal. Email, web pages, uploads, recalled text, voice calls, shared excerpts, and automations cannot start one.

Hearth opens a PR from a `hearth/improve-…` branch. The Chat card shows the summary, additions and deletions by file, expandable unified diff, PR link, and CI status. **Request changes** takes typed feedback, adds a commit to the same branch, and clears any earlier approval. **Discard** closes the PR and deletes its branch. If the base moves or GitHub detects conflicts, discard the stale PR and type the request again against the new base.

**Approve and update** authorizes only the exact head shown in the card, even with Always allow enabled. Hearth waits for outstanding checks and leaves the PR open if a check fails. GitHub’s squash API pins the PR head. To protect the base during the merge itself, Hearth also requires a readable classic branch protection rule that enforces required checks on up-to-date branches, applies the rule to administrators, and disallows force pushes. If Hearth cannot verify that rule, the card explains why the PR cannot be merged in Chat.

## Scope and safety

- Up to five regular UTF-8 text files and 400 additions plus deletions in the complete PR diff. Hearth also caps individual file size and planning context. It checks Python with `compile()` and checks JavaScript with Node when Node is installed. It does not run proposed code on the Sprite.
- Hidden paths, `.github/`, `scripts/`, deployment and infrastructure files, configuration and access rules, workspace memory, credential-like paths or contents, and the self-update code and tests are protected. Server modules that enforce connector, approval, or storage policy are protected too. This guide is editable.
- The connector supplies GitHub credentials. Chat’s general connector tools cannot write to the managed repo or its proposal branch namespace.

## Deployment and revert

GitHub Actions runs tests on PRs. A merge to `main` triggers the same tests and then deploys to the Sprite. Hearth follows the deployment workflow run for the squash commit. `scripts/deploy.sh` packages the tracked runtime at the exact Git SHA. The Sprite installer writes that SHA to `.deployed-commit` inside the release before switching the service. The installer waits for HTTP 200 and the matching `version` in `/health`. Settings → About displays the same SHA.

The card shows the result once the running Hearth reports that version. Timeline records proposals, revisions, approvals, merges, deployments, and discards. To undo an update, type “Revert the last Hearth update” or “Revert <short SHA>.” Hearth opens another reviewable PR if the affected files still match the merged snapshot.

Configure the repository and proposal toggle under Settings → Connections → GitHub. Proposals default to on for `Xuefeng-Zhu/Hearth`.
