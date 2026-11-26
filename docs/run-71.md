# Run 71 — Workspace alignment and spacing

Run 71 fixed 39 layout defects and two dark-theme contrast defects on `main`, starting from `b9567ff1bf6bc3aea1f46d4d866b5f7dce12dffe`. The shared CSS uses a 4 px spacing scale, 16 px card insets, 12 px grid gaps, and 40 px desktop controls with 44 px mobile touch targets. The 390 px workspace uses the existing drawer, and 768 px and 1440 px use the sidebar.

## Defect audit

| # | Surface | Before | After |
| --- | --- | --- | --- |
| 1 | Workspace header | The desktop title began at the sidebar gutter while most page content was centered much farther in. | The page title and content use the same width and gutter. On mobile the content follows the menu button’s outer edge. |
| 2 | Page sections | Page top insets and gaps after introductory headings varied across views and breakpoints. | Pages share responsive insets and a section gap. |
| 3 | Cards | Similar cards had different top, side, and bottom insets and corner radii. | Cards share padding and radius tokens. List rows use the smaller spacing steps. |
| 4 | Sidebar | The brand and nav icons used different left insets and icon-to-label gaps. | Brand and nav controls sit on the same inset with consistent icon and row spacing. |
| 5 | Workspace drawer | The close control, nav rows, thread list, and Settings footer each used different offsets. | The shell uses a 16 px gutter, centered header controls, and regular row and column gaps. |
| 6 | Home greeting | “Happy Hacksgiving” inherited the date’s tight line height and letter spacing and sat directly beneath the date. | The greeting has its own text style and an 8 px gap below the date. |
| 7 | Home at 768 px | Two columns squeezed the Feed toolbar and wrapped short titles and reminder labels. | Grid columns respond to the available content width, with one column at the audited tablet size. |
| 8 | Weather & clock | The nonwrapping clock could extend across the weather divider. | The columns can shrink, the type scales within them, and the divider has a consistent inset. |
| 9 | Home lists | Checklist boxes sat on the text baseline, and file type labels used different offsets from their titles. | Checkboxes and file type labels center vertically. Checklist rows have larger touch areas. |
| 10 | Home card footers and Feed | Footer separators, links, editing controls, and Feed fields used irregular gaps. | Footer spacing follows the shared scale, and Feed controls and labels use consistent gaps. |
| 11 | Home workers | Stop inherited card button margin and sat below the worker summary. | The Stop control aligns with the summary row, including when the details are expanded. |
| 12 | Chat threads | The thread heading, list, selector, and New side chat used mismatched insets and control heights. | Thread controls use consistent gutters and heights in the sidebar, inline selector, and drawer. |
| 13 | Chat composer | The desktop Stop button was taller than Send, microphone, and attachment controls. The field and transcript used different mobile gutters. | The composer uses one control height, and its outer edges share the transcript gutter. |
| 14 | Chat transcript and prompts | Prompt SVGs relied on inline baseline spacing. Message bubbles and attachment cards used uneven side insets. | Prompt icons and text center in flex rows, with regular message and attachment spacing. |
| 15 | Chat dialogs | Message actions and Chat summary positioned close buttons independently of their headings. | Both use an in-flow header that keeps the title left and the close action centered on the right. |
| 16 | Call | The call title and Minimize control aligned at their top edges. Caption content had comparatively tight bottom padding. | Header controls center vertically, and the stage and caption panel use shared insets. |
| 17 | Timeline filters | Chips, desktop search, and thread select differed in height. The mobile Filter icon and count used uneven gaps. | Fields and filters share control sizing. The mobile count has consistent inset and centering. |
| 18 | Timeline summary and rail | Metric columns and timeline rows used unrelated insets and gaps. The rail markers sat at fixed offsets. | Summary cells and row gaps use the scale, and markers align to the new row center. |
| 19 | Timeline entry actions | Undo and Approve floated off-center, with different space reserved at desktop and mobile widths. | A shared row height and inset center actions and reserve room beside the entry title. |
| 20 | Timeline expanded rows | Mobile details began near the card edge while the summary copy began after its icon. | Expanded content starts under the summary text. Confirmation boxes share the card inset. |
| 21 | Artifacts header | Box status and Refresh hugged the bottom of the introduction on desktop. On mobile the action group wrapped to the left. | Status and Refresh share a center line, and the group stays right-aligned when it wraps. |
| 22 | Artifacts toolbar | Search and selects were different heights from the layout toggle. At tablet width labels could truncate, and mobile select columns were uneven. | Search and square toggle buttons share a row and height. The tablet and mobile selects get equal-width columns. |
| 23 | Artifact tiles and list | Two narrow phone tiles squeezed names and timestamps. List and grid cards used irregular internal and external gaps. | Tiles wrap by available width. List rows retain their compact layout with consistent insets. |
| 24 | Artifact metadata | File type badges, sync labels, timestamps, and links mixed baseline and center alignment. | Badges center within pills. Footer items center and wrap with regular gaps. |
| 25 | Artifact and file-question drawers | Header, close button, preview body, and form used different horizontal edges. Radio labels had uneven insets. | The drawers share a title and close grid, common header and body gutters, and centered radio labels. |
| 26 | Page preview | The header, preview, and history had different gutters on smaller screens. The device buttons were shorter than the header actions. | The preview and history align with the header, with matching device and action controls. |
| 27 | Reminders, Inbox, and recurring task headers | Actions could wrap to the left or sit higher than the title and description. | The shared header centers each row and keeps wrapped actions at the right edge. |
| 28 | New reminder form | Native controls had square edges and little inner padding. Labels and the urgent checkbox used uneven spacing. | Fields use the shared border, radius, and insets. Checkbox and label center together. |
| 29 | Reminder and Inbox cards | Delivery cards, mail address cards, and message source details had inconsistent padding and list gaps. | Cards use shared insets and gaps. Source text has room inside its expanded panel. |
| 30 | Reminder badges and counts | Count badges sat on the heading baseline, and channel chips had uneven space around their icons. | Counts and chips center vertically in consistent pills. |
| 31 | Memory tabs | Six tabs across the tablet content area squeezed labels and counts. | The tablet and phone use three columns with even gaps. |
| 32 | Memory search and cards | Search, note controls, profile fields, and lists used unrelated gaps, heights, and insets. | Search and its action share a row, and review and note controls use the shared scale. |
| 33 | Skills library | New skill sat on a separate row flush against the card grid. Narrow cards broke titles and descriptions into short lines. | The action joins the introduction. The cards wrap by available width with consistent gaps. |
| 34 | Skill editor | The title and close button aligned to different baselines. The editor, toolbar, and footer used separate offsets. | The close button centers beside the title, and the editor shell shares one gutter. |
| 35 | Settings accordion | Group labels were slightly indented relative to disclosures, and row spacing and body insets varied. | Group labels share the page edge, with consistent gaps between rows and groups and an inset for expanded content. |
| 36 | Settings forms | Model help text ran into the next label. Paired fields and action buttons used different heights. | Labels are separated from the preceding field’s help text. Fields and actions follow the shared sizing. |
| 37 | Automation and goal dialogs | Schedule and event controls had browser-default spacing. Approval headers and chips used top alignment and uneven padding. | Fields follow the shared form styling, and dialog and approval controls use regular gaps and centered labels. |
| 38 | Self-update approval | The title icon was nudged down manually. Action rows doubled their spacing by combining a grid gap and inherited button margins. | The title and file counts center, the PR link shares the card edge, and each action row uses one gap. |
| 39 | Empty states | Home’s removed-panel notice hugged the page edge. Empty cards and lists used different insets from nearby content. | The affected notices and empty cards share the card inset and align with the rest of the page. |
| 40 | Dark form fields | Native selects in scheduling and approval forms measured 4.39:1 for text. | Styled fields use the workspace surface and foreground and pass the sampled 4.5:1 threshold. |
| 41 | Dark self-update action | The approval button’s border measured 2.85:1 against the adjacent surface. | It uses the dark theme’s accessible control border and passes the sampled 3:1 threshold. |

## Captures and verification

The local Chromium fixture served all nine pages, all 15 Settings sections, both Connections tabs, populated and empty views, the Home panels and layout editor, the self-update card and its feedback and diff, and the workspace and artifact drawers and app dialogs. The workspace drawer and Timeline filter sheet were captured where their phone controls are available. The 768 px thread dialog was opened through its existing action for the visual check because the tablet presents the thread selector in its place.

The audit produced 508 matching screenshot pairs at 390×844, 768×1024, and 1440×900 in light and dark. Screenshot geometry checks found zero horizontal overflows in the workspace containers. Chromium sampled 26,042 dark text and control contrast pairs with zero failures against the applicable WCAG AA thresholds.

- Baseline in [before](/workspace/tmp/hearth-qa/run71/before) and release in [after](/workspace/tmp/hearth-qa/run71/after)
- [Home](/workspace/tmp/hearth-qa/run71/compare-home.png), [Artifacts](/workspace/tmp/hearth-qa/run71/compare-artifacts.png), [Reminders](/workspace/tmp/hearth-qa/run71/compare-reminder-form.png), [Timeline](/workspace/tmp/hearth-qa/run71/compare-timeline.png), [Settings](/workspace/tmp/hearth-qa/run71/compare-settings-brain.png), and [Self-update](/workspace/tmp/hearth-qa/run71/compare-self-update.png) comparisons

| Check | Result |
| --- | --- |
| Python unittest discovery | 330 passed with the repository’s CJK PDF font configured |
| Node test runner | 20 passed |
| Chromium workspace smoke | Passed, including new checks for gutters, header alignment, overflow, and toolbar sizing at all three widths |
| Chromium stream disconnect | Passed |
| Live Sprite smoke | HTTP 200 for the workspace HTML, all 10 CSS routes, Home data, and Chat workspace state. The HTML and CSS matched the release by SHA-256. |

`scripts/deploy.sh` deployed `f0d2051f0e5b1758bc0a54a51e41382de9b1baaa`. An independent `GET /health` returned HTTP 200 with that version and Sprite checkpoints. The commits are local to `main`.
