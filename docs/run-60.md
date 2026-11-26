# Run 60 · Chat reconciliation and accessibility

Run 60 started on `main` at `017828f`, with the D06 polling and paging work and the D16 Chromium smoke merged. The D16 disconnect regression reproduced two assistant bubbles on that baseline.

## Chat state

The pure model reconciles the selected transcript window, older pages, and in-flight turns scoped to each thread. The browser keeps its paged scroll anchor and hands decoded events to the same model as foreground polling. New replies carry the originating prompt's saved ID in `reply_to`. When polling finds that reply, the model replaces the partial and clears its interruption notice. This works with repeated prompt text and with a snapshot that arrives before the stream's completion event.

The SSE parser handles UTF-8 across chunk boundaries, line endings, comments, multiline data, and event IDs independently of the browser. The model ignores replayed event IDs and frames for completed turns. A dropped POST stream recovers from polling its saved reply, so sending the prompt remains a single request. [Reconciliation model](../web/chat-state.js), [SSE parser](../web/sse.js)

## Accessibility

When a reply completes in the open chat, the polite live region receives “Hearth replied” and an excerpt of up to 100 characters. Streamed tokens leave the region quiet. The Send button returns focus to the composer. Stop retains focus while the stop request is pending and returns focus to the composer when the button disappears. Desktop thread switching keeps focus on the selected thread button. Mobile drawer switching moves focus to the destination heading.

Playwright checked keyboard interaction and live-region updates, including consecutive replies with identical excerpts and a reply recovered by polling. The check measured browser accessibility behavior through focus and DOM updates.

## Verification

| Check | Result |
| --- | --- |
| Python | 315 passed |
| Node | 16 passed |
| JavaScript syntax | All `web/*.js` passed `node --check` |
| Offline Chromium | Keyboard smoke and disconnect recovery passed. Both gate CI deploy. |
| Visual comparison | Empty, streaming, and completed Chat matched at 375×667, 390×844, and 1440×1000 in light and dark. All measured layout rectangles matched the baseline. |
| WCAG AA contrast | 17,055 sampled pairs passed. Minimum body text contrast was 4.622:1. |

The Browser plugin was unavailable, so the checks used Playwright Chromium directly. [Browser smoke](../tests/browser-smoke.py), [Deploy workflow](../.github/workflows/deploy.yml)

## Deployment

`scripts/deploy.sh` succeeded. At 10:01 UTC on November 26, 2026, the running production service returned HTTP 200 from `/health` and served the five checked frontend assets with matching hashes. Its `/api/chat` endpoint streamed a non-Mock reply with one token event and one completion event. The saved transcript had one assistant reply linked to the prompt. The disposable side chat used for the smoke test was deleted.
