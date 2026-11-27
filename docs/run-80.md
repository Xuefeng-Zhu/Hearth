# Run 80 · Motion design

Hearth uses three motion durations in `web/theme.css` (120, 200, and 320 ms) and shared easing curves. Workspace views crossfade with a 6 px rise through the View Transitions API. The navigation highlight moves independently, and browsers without the API switch views directly.

Thread actions, Add panel, searchable selects, and Chat search scale from the edge nearest their trigger. Bottom sheets rise with a fading backdrop. Close actions restore focus immediately while the surface fades out. Reduced motion keeps the surface fades and disables the view, position, and scale animations.

Home measures the old and new panel positions for FLIP reorder animations. The first six panels enter 32 ms apart on first load. Home panels, threads, reminders, and Inbox cards animate their visible height and opacity on insertion and removal. Chat animates newly arriving messages without replaying history or animating every streamed token. Buttons, toggles, feedback, the typing indicator, and loading placeholders use the same tokens.

## Verification

- Python unit tests, Node tests, and JavaScript syntax checks. Python (`/workspace/tmp/hearth-qa/run80/python.log`) · Node (`/workspace/tmp/hearth-qa/run80/node.log`)
- Both Chromium suites passed. The motion regression checks native view animations, rapid navigation, Home reorder, reduced-motion transforms, popover exit, and focus restoration. Workspace smoke (`/workspace/tmp/hearth-qa/run80/chromium-smoke.log`) · Stream disconnect (`/workspace/tmp/hearth-qa/run80/chromium-disconnect.log`) · Motion regression (`/workspace/tmp/hearth-qa/run80/chromium-motion.log`)
- Chromium checked every integer width from 390 to 1920 px for horizontal overflow in Home edit mode, Chat, Chat search, and the Reminders, Inbox, and Skills search views. The recorded desktop flow had zero layout-shift entries. Home and Chat (`/workspace/tmp/hearth-qa/run80/motion-widths.log`) · Chat search (`/workspace/tmp/hearth-qa/run80/chromium-chat-search.log`) · List search (`/workspace/tmp/hearth-qa/run80/chromium-list-search.log`) · Capture log (`/workspace/tmp/hearth-qa/run80/capture.log`)
- The settled contrast audit found zero WCAG AA failures. The minimum dark-mode ratios matched Run 79 at 5.224:1 for body text and 4.317:1 for large text and non-text controls. Run 80 audit (`/workspace/tmp/hearth-qa/run80/contrast.log`) · Run 79 baseline (`/workspace/tmp/hearth-qa/run80/contrast-baseline.log`)
- `scripts/deploy.sh` ships the tracked runtime. The release smoke checks HTTP 200 on `/health`, the deployed commit, and the motion asset hashes. Deploy log (`/workspace/tmp/hearth-qa/run80/deploy.log`) · Release smoke (`/workspace/tmp/hearth-qa/run80/live-smoke.log`)

## Capture

- 11-second Playwright recording (`/workspace/tmp/hearth-qa/run80/motion-demo.mp4`) shows a page switch, thread actions opening and closing, a Home reorder, and Chat search.
- Thread popover mid-entrance, 1440 px, light (`/workspace/tmp/hearth-qa/run80/popover-mid-1440-light.png`)
