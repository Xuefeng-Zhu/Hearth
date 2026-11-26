# Run 75 · Thread actions

On desktop, the ellipsis appears on row hover, keyboard focus, and while the menu is open. The selected row follows the same rules. The button keeps its space in the row so titles stay in place. Touch devices and the mobile drawer keep the button visible with a 44 px target.

The thread menu uses the native Popover API and CSS anchor positioning where available. A JavaScript fallback positions it against the trigger and keeps it inside the viewport. The menu opens below the button when there is room and flips above it near the bottom. It uses the existing SVG icons and workspace theme tokens.

Arrow keys move between enabled actions, and Home and End jump to the first and last actions. Escape, an outside click, scrolling, and resizing dismiss the menu and restore focus. Tab dismisses it and continues through the thread list. Main shows Summary only. A working side chat keeps Delete disabled. Summary still opens the existing sheet, Rename uses the existing prompt, and Delete uses the existing confirmation.

## Verification

- All 330 Python tests passed with the installed Chinese PDF font. [Python results](/workspace/tmp/hearth-qa/run75/python-with-font.log)
- All 24 Node tests passed, including fallback placement, viewport clamping, and keyboard navigation. [Node results](/workspace/tmp/hearth-qa/run75/node.log)
- Chromium smoke covers desktop hover and focus, native anchoring and flipping, dark-mode contrast, mobile touch targets, the fallback, and the Summary, Rename, and Delete flows. [Workspace smoke](/workspace/tmp/hearth-qa/run75/chromium-smoke.log) · [Stream disconnect](/workspace/tmp/hearth-qa/run75/chromium-disconnect.log)
- The Sprite release smoke checks the exact commit in `GET /health`, verifies the served assets, and reads Chat state and the Main summary. [Deploy log](/workspace/tmp/hearth-qa/run75/deploy.log) · [Live smoke](/workspace/tmp/hearth-qa/run75/live-smoke.log)

## Screenshots

- [Desktop row hover, light](/workspace/tmp/hearth-qa/run75/thread-hover-1440-light.png)
- [Desktop menu, light](/workspace/tmp/hearth-qa/run75/thread-popover-1440-light.png)
- [Desktop menu, dark](/workspace/tmp/hearth-qa/run75/thread-popover-1440-dark.png)
- [Mobile drawer, light](/workspace/tmp/hearth-qa/run75/thread-mobile-390-light.png)
