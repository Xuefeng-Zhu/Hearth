# Run 76 · Add panels from Home

Edit layout places a dashed **Add panel** tile after the visible panels. It opens an anchored popover on desktop and a bottom sheet at 760 px and below. Escape, an outside click, and selecting an action return focus to the tile. The Home header shows the date on its own.

**Restore** lists hidden built-in and custom panels. Restoring a panel preserves its saved position and the existing feedback message. **New panel** offers Countdown, Checklist, List, Note, Stat, and Web summary alongside the description field.

Requests go through Main in Chat and use Hearth’s existing panel tool. Saved panels appear at the end of the Home grid while edit mode stays active. Countdown and Web summary ask for a date or public URL when needed. Hearth’s mock brain supports the starter prompts. Custom descriptions use a connected brain, with a scripted response in the offline browser fixture.

## Verification

- All 332 Python tests and 27 Node tests passed, along with JavaScript syntax checks. The Python suite used the repository’s WenQuanYi Micro Hei font. [Python log](/workspace/tmp/hearth-qa/run76/python-final.log) · [Node log](/workspace/tmp/hearth-qa/run76/node.log)
- Chromium verified creation and restoration through Hearth, keyboard and touch focus, desktop anchoring and fallback placement, dark-mode contrast, and 44 px sheet targets. A separate sweep found zero horizontal overflow at all 1,531 integer widths from 390 through 1920 px. The browser tests used temporary workspaces and mocked responses. [Workspace smoke](/workspace/tmp/hearth-qa/run76/chromium-final.log) · [Stream disconnect](/workspace/tmp/hearth-qa/run76/chromium-disconnect.log) · [Home regression](/workspace/tmp/hearth-qa/run76/chromium-run22.log) · [Overflow sweep](/workspace/tmp/hearth-qa/run76/overflow-sweep.log)
- The Sprite release smoke compares the deployed `/health` version with the local commit and checks that `/api/home` returns 200. [Deploy log](/workspace/tmp/hearth-qa/run76/deploy.log) · [Live smoke](/workspace/tmp/hearth-qa/run76/live-smoke.log)

## Screenshots

- [Home edit layout, 1440 px light](/workspace/tmp/hearth-qa/run76/home-edit-add-1440-light.png)
- [Add panel popover, 1440 px light](/workspace/tmp/hearth-qa/run76/home-add-popover-1440-light.png)
- [Add panel popover, 1440 px dark](/workspace/tmp/hearth-qa/run76/home-add-popover-1440-dark.png)
- [Add panel sheet, 390 px light](/workspace/tmp/hearth-qa/run76/home-add-sheet-390-light.png)
- [Home date heading, 1440 px light](/workspace/tmp/hearth-qa/run76/home-no-greeting-1440-light.png)
