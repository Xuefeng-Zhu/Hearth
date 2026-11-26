# Run 72 — Desktop controls and layout

Baseline `bc75f1c3743add25dbc28e18d8f667a8262741f6` matched the live workspace HTML and all ten CSS assets byte for byte. The baseline review used local disposable workspaces with bilingual planning notes, Main and 18 side chats, long email subjects, recurring tasks, reminders, versioned skills, and wide Markdown and workbook tables. Feed cards, the Box file picker, and pending background work used local fixture responses. Browser networking stayed on the local fixture servers.

## Defect audit

| # | Surface | Before | After |
| --- | --- | --- | --- |
| 1 | All dropdowns | Each native select relied on the platform arrow. The icon sat against the right border, and the caret shape and inset depended on the OS. | All single selects use one same-origin SVG chevron, a 12 px leading inset and 38 px trailing clearance. Forced colors restores the system indicator. |
| 2 | Chat avatar and tablet thread selects | The desktop avatar select used 12 px text and asymmetric 9/24 px insets. The tablet thread picker used separate font and padding rules from the button beside it. | The common select rule centers text at 40 px. The tablet picker and New side chat share a row and height. |
| 3 | Artifacts and Timeline selects | Fields had no explicit arrow clearance. Long thread labels competed with the arrow in the 130 px Timeline select. | The toolbar fields share 40 px sizing, and Timeline gives the thread picker a larger flex share with ellipsis. |
| 4 | Reminder, approval, and schedule selects | Native select text inherited bold form labels in some sections. Default-channel fields were 40 px and policy and schedule selects were 44 px. | The common control sizes fields at 40 px on desktop and 44 px on mobile with explicit regular-weight text. |
| 5 | Settings and skill selects | Settings selects ranged from 13 to 16 px. Skill history used 5/8 px padding and a smaller label than the mode buttons on the same row. | Settings and skill history use the same font, radius, leading inset, and chevron clearance as the other selects. |
| 6 | Settings approval policy rows | Each select started after the intrinsic width of its label. This produced six staggered left edges and short label columns that wrapped unnecessarily. | Policy rows share one label track and one field track across the form. |
| 7 | Appearance color row | The color field was 33 px beside a 40 px button, with a different radius. | The square color input matches the neighboring control in height and radius. |
| 8 | Chat composer | The mic glyph sat 2 px low because its wrapper still contributed an inline baseline. The transcript could run straight into the composer at the bottom of the pane. | The microphone wrapper centers as a flex item. The composer has an 8 px gap above it. |
| 9 | Chat thread header | The avatar selector hugged the far-right pane edge, while the composer and transcript ended much farther in at wide desktop sizes. | The thread header and Call action follow the 852 px transcript and composer measure. |
| 10 | Chat with dense content | A six-column Markdown table split words like “Volunteer” and “parking” midword. Rows were vertically centered against long cells, and the code preview wrapped long commands. | Tables keep a usable minimum width with local horizontal scrolling. Cells align at the top and code preserves long command lines. |
| 11 | Chat expansion | The Show more outline was about 27 px tall and looked undersized next to the 40 px message actions. | Show more uses a 40 px control with a hover surface. |
| 12 | Chat dialogs | The disabled Reset summary action filled the width of the summary dialog's menu row, even though it is a footer action. | Reset summary sits at the right of a separate action row. |
| 13 | Workspace shell | Home had 1,116 px of usable width, while most other pages had 906 px. Page titles jumped sideways on navigation. At 1920 px the cap created large gutters around data-heavy pages. | Workspace pages and their headers use one 1,200 px content cap with shared responsive gutters. |
| 14 | Home edit mode | Inline reorder and remove controls squeezed titles like “Inbox to review” and “Weather & clock” into two lines. The 30 px icon controls had separate square and radius rules. | The editor gives titles a full first row and places square reorder controls in a separate right-aligned row. |
| 15 | Home Feed | The options and steering actions sat left, while the settings icon floated away from its toolbar siblings. A tall Feed could stretch the adjacent Today panel into mostly blank space. | Feed toolbar, option, and submit controls align at the right. The Feed, Goals, and Checklist lists have bounded desktop scroll regions. |
| 16 | Home weather and panel footers | Link buttons and the weather refresh icon had different heights in footer rows. Footer text and tool groups lost the shared center line when contents wrapped. | The weather source and refresh icon share the control height. Link groups wrap and remain vertically centered. |
| 17 | Home approvals and workers | Approval controls stayed left when no separate metadata preceded them. Worker controls borrowed the larger touch sizing even on desktop and long text needed a shrinkable track. | Approval controls stay at the right. Worker stop shares the workspace control height and long titles can shrink within their track. |
| 18 | Timeline toolbar | When search and thread fields wrapped off the chip row, the fields restarted at the left instead of holding the right edge. | The field group keeps the right edge even when it wraps onto a second row. |
| 19 | Timeline entries | Titles were single-line ellipses, including expanded entries. The sticky day heading could cover the active row when it was scrolled into place. | Expanded titles wrap in full. Timeline reserves scroll clearance for sticky day headings. |
| 20 | Timeline undo | Confirm and Cancel started left, and the second button's individual margin produced different spacing from other confirmation rows. | Cancel and confirmation share an end-aligned action row with token spacing. |
| 21 | Artifacts header | Ask my files occupied a dedicated 44 px row below the Box status and 40 px refresh control. The split interrupted the heading-to-filter spacing. | Ask my files joins Box status and Refresh in the header action group at the same control height. |
| 22 | Artifact grid | Bilingual titles used five or more lines, delaying the next row. Short titles left metadata and actions at visibly different positions. | Desktop titles use a three-line preview with the full title in the drawer. Status and actions align within the grid row. |
| 23 | Artifact list | Status and action columns took too much width from the actual filename. Titles wrapped into tall blocks even on desktop. | The list allocates more space to the title while retaining aligned status, date, and action columns. |
| 24 | Artifact and file-question drawers | Download and destructive actions started on the left, below a close icon at the right. The workbook header and table competed for a narrow fixed-width drawer. File-picker submit also started on the left. | Drawer actions and file-picker submit align at the right. Document previews have more width on desktop. |
| 25 | Workbook preview | A wide workbook could only be scrolled horizontally at the bottom of a long table. Column headings scrolled out while reading rows. | The spreadsheet scrolls inside a bounded region with a sticky column header. |
| 26 | Page preview | The header action row started on the left, independent of Close and the right-aligned device buttons. | Page actions align with the right edge of the preview and Close button. |
| 27 | Reminders | The create form's submit occupied the left grid cell. Reminder Undo controls started at the left underneath notes, and long titles could push timestamps into separate rows. | The submit spans the form grid and aligns right. Undo is in an action row, and desktop card dates have a dedicated track. |
| 28 | Inbox | Long bilingual subjects and dates competed for width. Card decisions hugged the left edge and extended notes filled overly wide lines. | Long subjects wrap in their own column. Decision buttons align right and source text follows a readable measure. |
| 29 | Recurring tasks and automations | Task and form actions used standalone padding and sizing. The narrow event dialog sent the final controls below the fold at ordinary desktop heights. | Automation controls share the workspace height. Event dialogs use paired fields and a right-aligned action row. |
| 30 | Memory list | Long note titles turned the narrow navigation column into very tall buttons. Selected note actions and form actions started at the left. | The note list is wider on desktop and long labels show up to three lines with the full title available. Note actions align right. |
| 31 | Memory search and review | Forget used a browser-default button. Review actions, time input, and selects had separate sizing and alignment rules. | Forget uses the shared button styling. Review time and action controls use the same height and centered labels. |
| 32 | Skills library and editor | The two-column desktop library used little of a large display. Card usage details had uneven baselines. In-editor deletion confirmation had independent margins and alignment. | Skills gain a third column when space permits. Card metadata anchors at the bottom and delete confirmation uses the shared action row. |
| 33 | Settings groups | Brain, Voice, Search, Reminders, and other preference forms mixed left-aligned submit buttons and differently sized controls with the already right-aligned page headers. | Settings actions align to the right. Voice uses two columns when both forms fit. |
| 34 | Settings inline controls | Search test, filter, and connector rows mixed input fonts, button fonts, and label-driven sizes. Routing inputs and actions did not read as a single row. | Inline fields and actions share a height and text scale. Routing uses one prompt and action row. |
| 35 | Self-update | The PR link, main action row, and feedback confirmation all started left across multiple rows. Both action rows used 44 px buttons inside a 40 px desktop Chat UI. | PR, decision, and feedback actions align at the right. The card keeps its existing 44 px approval targets, including on desktop. |
| 36 | Focus and hover | Focus on a clipped message or table could run into its container edge. Compact and browser-default actions had weaker or inconsistent hover and focus feedback. | Message and table focus rings draw inside the clipping edge. Text and compact actions have explicit hover feedback. |
| 37 | Empty state alignment | Removed Home panels and a no-match Artifacts view used different width caps and unrelated inset edges from nearby nonempty views. | Empty states follow the same shared page gutter and content cap as populated states. |

## Capture and test results

The audit produced 1,430 matched screenshot pairs in Chromium. The 952 desktop pairs cover 1280×800, 1440×900, 1680×1050, and 1920×1080 in light and dark. The 478 phone and tablet pairs cover 390×844 and 768×1024 in both themes. The captures include all workspace pages, Settings disclosures, populated and empty states, enabled and disabled actions, keyboard focus, hover, drawers, and application dialogs. Chromium used the installed CJK font so bilingual fixture text rendered at its true width. The native PDF viewport appeared blank in headless Chromium. The captures cover its surrounding drawer and controls.

| Check | Result |
| --- | --- |
| Workspace geometry | Zero horizontal overflows in the audited workspace containers. Wide tables, code, and diffs retain their own scroll regions. |
| Dropdowns | All 1,412 rendered select observations used the same chevron and 12/38 px insets. Desktop and tablet heights were 40 px and phone heights were 44 px. |
| Dark contrast | All 122,651 sampled text, control boundary, icon, and focus pairs met their applicable thresholds. The SVG chevron measured 3.36:1 against the dark control surface. |
| Python unittest discovery | 330 passed with the CJK PDF font configured. |
| Node test runner | 20 passed. |
| Chromium workspace smoke | Passed, including 1920×1080 and keyboard selection, field heights, arrow clearance, and header alignment. |
| Chromium stream disconnect | Passed. |
| Live smoke | `GET /health` returned HTTP 200 with the deployed version. The workspace HTML and 17 static assets matched the release. Navigation order and the served SVG were verified. |

Chrome captures are in [before](/workspace/tmp/hearth-qa/run72/before) and [after](/workspace/tmp/hearth-qa/run72/after). The read-only baseline asset hashes are in [production parity](/workspace/tmp/hearth-qa/run72/before/production/parity.json).

- [Home](/workspace/tmp/hearth-qa/run72/compare-home.png)
- [Chat table and composer](/workspace/tmp/hearth-qa/run72/compare-chat-table.png)
- [Timeline filters](/workspace/tmp/hearth-qa/run72/compare-timeline.png)
- [Artifacts toolbar and grid](/workspace/tmp/hearth-qa/run72/compare-artifacts.png)
- [Reminder form](/workspace/tmp/hearth-qa/run72/compare-reminder-form.png)
- [Inbox actions and long subject](/workspace/tmp/hearth-qa/run72/compare-inbox.png)
- [Approval policy selects](/workspace/tmp/hearth-qa/run72/compare-settings-approvals.png)
- [Self-update feedback and actions](/workspace/tmp/hearth-qa/run72/compare-self-update.png)

`scripts/deploy.sh` deployed `4925a6d51a2a0f9c1972861d29a57173408785c5`. Production verification used GET requests. The commits remain local to `main`.
