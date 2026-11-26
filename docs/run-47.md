# Run 47 — Ideas and Goals

**Home → Feed → Ideas** offers up to five actions grounded in workspace context. A tap opens a Chat draft or an approval card for an in-app reminder, follow-up automation, or public-page watcher. **Goals** is a Home panel with target dates, manual or linked progress, check-in reminders, and suggested next steps. Chat includes goal memory, and Timeline can undo goal changes. [Ideas and Goals guide](ideas-and-goals.md)

## Sprite verification

On November 26, 2026, at 06:11 UTC, `scripts/deploy.sh` completed and the deployed Sprite returned HTTP 200 from `/health` with Sprite checkpoints enabled. The deployed `/api/home` and `/api/feed` both returned HTTP 200 with their Run 47 fields.

A temporary workspace on that Sprite used the deployed code and the real Sprites gateway with fictional data. The quick route used Hugging Face’s DeepSeek Flash model and returned one Idea and a goal next step. The check exercised opening the generated Idea, approving a goal, recording a 35 percent check-in, reading its scheduled check-in reminder, and using Timeline Undo to restore progress to 0 percent. The temporary workspace was removed after the check.

Watcher page reads and the Idea-to-automation path were verified with local fakes. The live pass covered generation, opening an Idea, and the goal lifecycle above.

## Local verification

- `python -m unittest discover -s tests` passed 239 tests, including nine cases for Ideas and Goals.
- `node --test tests/*.test.mjs` passed 9 tests. All web JavaScript modules passed syntax checks.
- WebKit exercised the Ideas strip, slide-deck draft, reminder approval, goal creation in Home and Chat, editing, check-ins, panel order and visibility, and Timeline Undo. The dark mobile runs used 390×844 and 375×667 viewports. The scoped checks found no page overflow or sub-44 px controls, and 93 sampled contrast pairs per viewport met WCAG AA. Playwright’s screenshot-only stylesheet warnings were isolated from application console checks.
- Ten screenshots with fictional data are under `/workspace/tmp/hearth-qa/run47/`.
