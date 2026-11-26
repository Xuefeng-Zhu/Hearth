# Run 72 — Desktop controls and layout

Baseline `bc75f1c3743add25dbc28e18d8f667a8262741f6` matched the live workspace HTML and all ten CSS assets byte for byte. The baseline review used local disposable workspaces with bilingual planning notes, 18 chat threads, long email subjects, recurring tasks, reminders, versioned skills, and wide Markdown and workbook tables. Feed cards, the Box file picker, and pending background work used local fixture responses. Browser networking stayed on the local fixture servers.

## Defects before implementation

| # | Surface | Before |
| --- | --- | --- |
| 1 | All dropdowns | Each native select relied on the platform arrow. The icon sat against the right border, and the caret shape and inset depended on the OS. |
| 2 | Chat avatar and tablet thread selects | The desktop avatar select used 12 px text and asymmetric 9/24 px insets. The tablet thread picker used a different height and text recipe from the button beside it. |
| 3 | Artifacts and Timeline selects | Fields had no explicit arrow clearance. Long thread labels competed with the arrow in the 130 px Timeline select. |
| 4 | Reminder, approval, and schedule selects | Native select text inherited bold form labels in some sections. Default-channel fields were 40 px and policy and schedule selects were 44 px. |
| 5 | Settings and skill selects | Settings selects ranged from 13 to 16 px. Skill history used 5/8 px padding and a smaller label than the mode buttons on the same row. |
| 6 | Settings approval policy rows | Each select started after the intrinsic width of its label. This produced six staggered left edges and short label columns that wrapped unnecessarily. |
| 7 | Appearance color row | The color field was 33 px beside a 40 px button, with a different radius. |
| 8 | Chat composer | The mic glyph sat 2 px low because its wrapper still contributed an inline baseline. The transcript could run straight into the composer at the bottom of the pane. |
| 9 | Chat thread header | The avatar selector hugged the far-right pane edge, while the composer and transcript ended much farther in at wide desktop sizes. |
| 10 | Chat with dense content | A six-column Markdown table split words like “Volunteer” and “parking” midword. Rows were vertically centered against long cells, and the code preview wrapped long commands. |
| 11 | Chat expansion | The Show more outline was about 27 px tall and looked undersized next to the 40 px message actions. |
| 12 | Chat dialogs | The disabled Reset summary action filled the width of the summary dialog's menu row, even though it is a footer action. |
| 13 | Workspace shell | Home had 1,116 px of usable width, while most other pages had 906 px. Page titles jumped sideways on navigation. At 1920 px the cap created large gutters around data-heavy pages. |
| 14 | Home edit mode | Inline reorder and remove controls squeezed titles like “Inbox to review” and “Weather & clock” into two lines. The 30 px icon controls had separate square and radius rules. |
| 15 | Home Feed | The options and steering actions sat left, while the settings icon floated away from its toolbar siblings. A tall Feed could stretch the adjacent Today panel into mostly blank space. |
| 16 | Home weather and panel footers | Link buttons and the weather refresh icon had different heights in footer rows. Footer text and tool groups lost the shared center line when contents wrapped. |
| 17 | Home approvals and workers | Approval controls stayed left when no separate metadata preceded them. Worker controls borrowed the larger touch sizing even on desktop and long text needed a shrinkable track. |
| 18 | Timeline toolbar | When search and thread fields wrapped off the chip row, the fields restarted at the left instead of holding the right edge. |
| 19 | Timeline entries | Titles were single-line ellipses, including expanded entries. The sticky day heading could cover the active row when it was scrolled into place. |
| 20 | Timeline undo | Confirm and Cancel started left, and the second button's individual margin produced different spacing from other confirmation rows. |
| 21 | Artifacts header | Ask my files occupied a dedicated 44 px row below the Box status and 40 px refresh control. The split interrupted the heading-to-filter spacing. |
| 22 | Artifact grid | Bilingual titles used five or more lines, delaying the next row. Short titles left metadata and actions at visibly different positions. |
| 23 | Artifact list | Status and action columns took too much width from the actual filename. Titles wrapped into tall blocks even on desktop. |
| 24 | Artifact and file-question drawers | Download and destructive actions started on the left, below a close icon at the right. The workbook header and table competed for a narrow fixed-width drawer. File-picker submit also started on the left. |
| 25 | Workbook preview | A wide workbook could only be scrolled horizontally at the bottom of a long table. Column headings scrolled out while reading rows. |
| 26 | Page preview | The header action row started on the left, independent of Close and the right-aligned device buttons. |
| 27 | Reminders | The create form's submit occupied the left grid cell. Reminder Undo controls started at the left underneath notes, and long titles could push timestamps into separate rows. |
| 28 | Inbox | Long bilingual subjects and dates competed for width. Card decisions hugged the left edge and extended notes filled overly wide lines. |
| 29 | Recurring tasks and automations | Task and form actions used standalone padding and sizing. The narrow event dialog sent the final controls below the fold at ordinary desktop heights. |
| 30 | Memory list | Long note titles turned the narrow navigation column into very tall buttons. Selected note actions and form actions started at the left. |
| 31 | Memory search and review | Forget used a browser-default button. Review actions, time input, and selects had separate sizing and alignment rules. |
| 32 | Skills library and editor | The two-column desktop library used little of a large display. Card usage details had uneven baselines. In-editor deletion confirmation had independent margins and alignment. |
| 33 | Settings groups | Brain, Voice, Search, Reminders, and other preference forms mixed left-aligned submit buttons and differently sized controls with the already right-aligned page headers. |
| 34 | Settings inline controls | Search test, filter, and connector rows mixed input fonts, button fonts, and label-driven sizes. Routing inputs and actions did not read as a single row. |
| 35 | Self-update | The PR link, main action row, and feedback confirmation all started left across multiple rows. Both action rows used 44 px buttons inside a 40 px desktop Chat UI. |
| 36 | Focus and hover | Focus on a clipped message or table could run into its container edge. Compact and browser-default actions had weaker or inconsistent hover and focus feedback. |
| 37 | Empty state alignment | Removed Home panels and a no-match Artifacts view used different width caps and unrelated inset edges from nearby nonempty views. |
