# Run 73 · Artifacts and workspace border alignment

The before captures use the deployed Run 72 commit `4925a6d`. Both stages use the Run 72 dense fixture and the same file ordering, dates, and bilingual titles.

## Artifacts

- Grid tiles use the same small file-type icon for documents and Pages. A two-line title area reserves the same space on every tile and exposes the full title on hover and in the preview. Chips and file sizes use a shared baseline. Status, modified date, and actions use one footer row with an edge-to-edge divider.
- List view uses one bordered surface and five aligned columns for icon, name and chips, status, modified date, and actions. Separators run across the list, and the desktop header stays visible when scrolling. A compact two-row layout keeps metadata and actions visible on smaller screens.
- The Box status, Refresh, and Ask my files controls share a height. Search, sort, and the layout toggle use the same control sizing. The chips replace the kind select and still support combined format and kind filters. The empty result state offers Clear filters.
- Retry sync is available for failed items while Box is connected. A local file can be saved to Box from its drawer. Imported files can be downloaded directly from either view. Preview and version-history surfaces share their edges. Trash confirmation uses a single action row.
- The design review used file columns and the view switcher in Google Drive, consistent card structure and preview in Notion, and sticky headers and compact metadata in Linear. [Google Drive Help](https://support.google.com/drive/answer/2375177) · [Notion Gallery](https://www.notion.com/help/galleries) · [Linear Display options](https://linear.app/docs/display-options)

## Workspace borders

| Page | Alignment change |
| --- | --- |
| Home | Panel footers reach the panel edges. Feed and Goal entries use tinted surfaces inside their panels. |
| Chat | The thread divider follows the composer column. File cards inside replies use a tinted surface. |
| Timeline | The summary, filter divider, day headings, and event cards share the page column. The event icons convey activity type within the cards. |
| Artifacts | The connection banner, toolbar, collection, and empty state share the same page edges. |
| Reminders | The expanded form and its summary share one card frame with a full-width divider. The date and channel controls align in their row. |
| Inbox | Proposal and source surfaces use the same control radius and card inset. |
| Memory | The search row, tabs, and content use the same column. Address fields align with the other profile fields inside the card. |
| Skills | Playbook tiles use the shared surface border and card radius. |
| Settings | One border encloses each accordion. Single forms share the body inset. Multiple sections use tinted surfaces with a consistent gutter. |

The workspace header and sidebar meet at a shared one-pixel border. Panels and dividers use the structural border token, and controls use the field outline token for contrast.

## Verification

- Python unittest discovery passed all 330 tests. Node passed all 20 tests. JavaScript syntax checks passed.
- Both offline Chromium suites passed. Browser regressions check grid footer positions, list row height and action centering, the sticky list header, filter interaction, Box retry gating, Ask my files selection and submission, and sibling column edges within one pixel.
- Artifacts was captured in light and dark at 1280×800, 1440×900, 1680×1050, and 1920×1080, followed by 390×844 and 768×1024. All nine workspace views were audited at 1440 and 1920 in both themes. The 240 captured states showed zero workspace horizontal overflows and zero failures among 16,330 sampled dark contrast pairs. Chromium checked the PDF iframe and its controls. Native PDF rendering was outside the headless check.
- A separate fixture check downloaded the original file, moved it to Hearth Trash, and restored it through Timeline. Trash verification (`/workspace/tmp/hearth-qa/run73/trash.log`)

## Visual evidence

The comparison sheets contain 1440 light, 1440 dark, and 1920 light at their original screenshot dimensions.

- Artifacts grid Comparison (`/workspace/tmp/hearth-qa/run73/compare-artifacts-grid.png`) · Full-resolution 1440 light after (`/workspace/tmp/hearth-qa/run73/artifacts-grid-1440-light.png`)
- Artifacts list Comparison (`/workspace/tmp/hearth-qa/run73/compare-artifacts-list.png`) · Full-resolution 1440 light after (`/workspace/tmp/hearth-qa/run73/artifacts-list-1440-light.png`)
- Borders Settings Approvals (`/workspace/tmp/hearth-qa/run73/compare-borders-settings.png`) · Home (`/workspace/tmp/hearth-qa/run73/compare-borders-home.png`) · Timeline (`/workspace/tmp/hearth-qa/run73/compare-borders-timeline.png`) · Memory (`/workspace/tmp/hearth-qa/run73/compare-borders-memory.png`)
- Additional captures Before (`/workspace/tmp/hearth-qa/run73/before`) · After (`/workspace/tmp/hearth-qa/run73/after`)

## Deployment

`scripts/deploy.sh` deployed `41c93bdeedf67d5e75e3148b39058772dce734a8`. The live smoke verified HTTP 200 from `/health` with that SHA, HTTP 200 and a valid Artifacts inventory from `/api/artifacts`, the workspace HTML and 19 assets against the release, and navigation order. The commits are local to `main`.

## Run 74 · Artifacts list title spacing

- Desktop list rows stay 76 px high and center the name cell vertically. Titles take their natural height, clamp at two lines, and leave 4 px between the last line and the chips. Grid tiles keep their two-line title area and aligned footers.
- The Box status, Refresh, and Ask my files controls already share the vertical center of **Saved work** on desktop. At 390 and 768 px the controls stack below the intro. The 390 px list keeps its 44 px title touch target.
- The Run 73 capture scripts were reused with the same stabilized fixture ordering. Both views were checked at 1280, 1440, 1920, 390, and 768 px in light and dark. The grid captures were pixel-identical to the baseline. 1440 light list (`/workspace/tmp/hearth-qa/run74/artifacts-list-1440-light.png`) · 1440 light grid (`/workspace/tmp/hearth-qa/run74/artifacts-grid-1440-light.png`) · Full capture matrix (`/workspace/tmp/hearth-qa/run74`)
- All 330 Python tests and 20 Node tests passed, along with JavaScript syntax checks and both Chromium suites. Chromium smoke now checks the gap between the rendered list title and the chips, and the vertical center of the name cell.
- The release uses `scripts/deploy.sh`. The live smoke checks HTTP 200 and the release SHA from `/health` and compares the served assets against the commit. Deployment verification (`/workspace/tmp/hearth-qa/run74/live-smoke.log`)
