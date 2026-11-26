# Run 44 — Event-triggered automations

**Settings → Automations** manages rules, their most recent status, and run history. Chat proposals show the trigger and ordered actions on a confirmation card. Rules can listen for new AgentMail messages, reminder firings, Feed cards, or scheduled times. [Automation guide](approvals-and-tasks.md#event-triggered-automations)

## Sprite verification

On November 26, 2026, at 03:58 UTC, the deployed Sprite returned HTTP 200 from `/health` with Sprite checkpoints enabled. The live check created an automation for a unique sender and subject, then sent one fictional email into the Hearth inbox through AgentMail. The inbox poll produced one completed run and its in-app reminder. Timeline showed the run and its Undo control. Undo canceled the reminder, and the test automation was deleted and confirmed absent from Settings.

After the final `scripts/deploy.sh` at 04:04 UTC, `/health` returned HTTP 200 again. The deployed automation runner and UI file checksums matched the workspace. The live check covered inbound AgentMail, run logging, local reminder creation, Undo, and rule deletion. Box uploads, outbound summary email, other trigger types, and chat prompt results were exercised with local fixtures and fakes.

## Local verification

- `python -m unittest discover -s tests` passed 225 tests, including 11 for event automations. The office tests used the WQY Micro Hei font.
- `node --test tests/*.test.mjs` passed eight tests. The app JavaScript modules also passed syntax checks.
- WebKit exercised Settings, creation, editing, pause and enable, run history, Timeline Undo, deletion approval, and chat confirmation on dark 390×844 and 375×667 viewports. The sampled controls met the 44 px target checks and WCAG AA contrast checks, with no horizontal overflow on the inspected surfaces.
- Eight fictional screenshots and the redacted Sprite check are in `/workspace/tmp/hearth-qa/run44/`. [Browser fixture](../tests/run44-browser.py)
