# Run 91 · Feed Ideas action buttons

Home → Feed → Ideas now shows the primary action, Dismiss (×), and Not interested (thumbs-down) in one right-aligned row. The two icons have distinct accessible names and hover titles. Both are square and match the primary button’s height. At viewport widths up to 760 px, all three controls have touch targets of at least 44 × 44 px.

Dismiss removes the current Idea. Not interested also saves a topic and action preference that suppresses similar Ideas. [Ideas and Goals guide](ideas-and-goals.md)

The Chromium regression checks the action row in single-card and multi-card layouts, including both sides of the 760 px breakpoint. It exercises keyboard dismissal, touch feedback, opening a draft, and reviewing a reminder. [Browser regression](../tests/feed_ideas_smoke.py)

## Verification

| Check | Result |
| --- | --- |
| Python unittest discovery with `HEARTH_CJK_FONT` | 343 passed |
| Node unit tests | 37 passed |
| `node --check` | All 63 frontend modules passed |
| Chromium | Default smoke, stream disconnect, Chat search, list search, motion, and focused Feed Ideas passed |
| WebKitGTK 27.2 | Focused Feed Ideas passed with reduced motion |

## Screenshots

The screenshots use fictional Ideas in a local workspace. To regenerate them from the worktree, run the focused Chromium smoke.

```sh
HEARTH_FEED_IDEAS_SCREENSHOTS=/workspace/tmp/hearth-qa/run91 \
  PYTHONPATH=. python tests/browser-smoke.py --feed-ideas
```

| Viewport | Theme | File |
| --- | --- | --- |
| 1440 × 900 | Light | `/workspace/tmp/hearth-qa/run91/feed-ideas-1440-light.png` |
| 1440 × 900 | Dark | `/workspace/tmp/hearth-qa/run91/feed-ideas-1440-dark.png` |
| 390 × 844 | Light | `/workspace/tmp/hearth-qa/run91/feed-ideas-390-light.png` |
