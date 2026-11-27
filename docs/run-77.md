# Run 77 · Searchable dropdowns

Single-choice selects become searchable at nine options, or when marked `data-searchable`. The picker rechecks that threshold as options change. The native select still owns the value, form submission, and input and change events. The picker matches labels and values without regard to case or accents, retains matching option groups, and marks the current value with a check.

Timeline has a Category picker for individual activity types alongside the existing broad activity chips. On mobile, both pickers are in **Filter** and take effect when the user taps **Apply**. Settings → Memory refreshes its thread list when opened directly so **Test recall** can filter by side chat.

The desktop thread action sits inside the full-width row. It appears on hover, focus within the row, or while its menu is open. A hovered side-chat title gets a tooltip if it is truncated. Main has no title tooltip. The touch drawer keeps its actions visible. The thread fix is in commit `34bcb23`.

## Runtime coverage

| Select | Options in the offline fixture | Result |
| --- | ---: | --- |
| Timeline thread `#timeline-thread` | 11 | Searchable |
| Timeline category `#timeline-category` | 31 | Searchable |
| Connections category, including both tab panels | 10 each | Searchable |
| Chat thread `#thread-select` | 12 | Searchable in the compact Chat header at 761–780 px |
| Test recall thread `#memory-test-thread` | 13 | Searchable |
| Brain model `#brain-model` | 11 | Searchable |
| Pool model `#pool-model` | 11 | Searchable |
| Memory model `#memory-model` | 10 | Searchable |
| Call language `#call-language` | 3 | Native |
| Dictation language `#voice-language` | 12 | Searchable |
| Skill versions `#skill-versions` | 9 | Searchable |
| Artifact sort and Search recency | 2 and 5 | Native |

## Verification

- `python -m unittest discover -s tests` passed all 332 tests with the project’s Chinese PDF font. `node --test tests/*.test.mjs` passed all 31 tests. All `web/*.js` passed syntax checks. Python log (`/workspace/tmp/hearth-qa/run77/python-final.log`) · Node log (`/workspace/tmp/hearth-qa/run77/node.log`) · JavaScript syntax log (`/workspace/tmp/hearth-qa/run77/js-syntax.log`)
- `PYTHONPATH=. python tests/browser-smoke.py`, its `--disconnect` run, and the Run 22 Home regression use temporary workspaces and offline fixtures. The Browser plugin was unavailable, so Playwright ran Chromium. Workspace smoke (`/workspace/tmp/hearth-qa/run77/chromium-smoke.log`) · Disconnect smoke (`/workspace/tmp/hearth-qa/run77/chromium-disconnect.log`) · Home regression (`/workspace/tmp/hearth-qa/run77/chromium-run22.log`)
- Full Chromium verified Timeline filtering, label activation, keyboard focus, form reset and submission, option mutations, disabled controls, dark-mode contrast, and 44 px touch targets at 390 px. Timeline and the open thread picker had zero horizontal overflow at every integer width from 390 through 1920 px. Thread row hover and active states were checked at 1280, 1440, and 1920 px. Combobox smoke (`/workspace/tmp/hearth-qa/run77/combobox-chromium.log`) · Overflow sweep (`/workspace/tmp/hearth-qa/run77/overflow-sweep.log`) · Thread row smoke (`/workspace/tmp/hearth-qa/run77/thread-row.log`)
- `scripts/deploy.sh` ships the committed release. The loopback smoke checks the exact SHA in `GET /health`, validates the `GET /api/timeline` response shape, and verifies the served combobox assets. Deploy log (`/workspace/tmp/hearth-qa/run77/deploy.log`) · Release smoke (`/workspace/tmp/hearth-qa/run77/live-smoke.log`)

## Screenshots

- Thread row hover, 1440 px light (`/workspace/tmp/hearth-qa/run77/thread-row-hover-1440-light.png`)
- Active thread row, 1440 px light (`/workspace/tmp/hearth-qa/run77/thread-row-active-1440-light.png`)
- Timeline thread search, 1440 px light (`/workspace/tmp/hearth-qa/run77/timeline-thread-search-1440-light.png`)
- Timeline thread search, 1440 px dark (`/workspace/tmp/hearth-qa/run77/timeline-thread-search-1440-dark.png`)
- Timeline category search, 1440 px light (`/workspace/tmp/hearth-qa/run77/timeline-category-search-1440-light.png`)
- Brain model search, 1440 px light (`/workspace/tmp/hearth-qa/run77/brain-model-search-1440-light.png`)
- Timeline search, 390 px light (`/workspace/tmp/hearth-qa/run77/timeline-search-390-light.png`)
