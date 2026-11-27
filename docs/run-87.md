# Run 87 · Documentation refresh

Updated the README and guides against `main` at `e50fe44`, using the implementation, tests, and run notes from 66–86.

- Rewrote the frontend architecture for the vendored Preact, hooks, and htm modules, the view folders, the shared store, and the Python HTTP server. Added instructions for wiring a view and updating the import-map CSP hash. [Architecture](architecture.md#frontend), [Development](development.md)
- Documented thread actions, Home panel restoration, searchable selects, Chat search and find-in-thread, list search, reduced motion, and the self-update merge guard. [README](../README.md), [Self-update](self-update.md)
- Updated the test commands and summarized the Run 85 engine coverage and Run 86 Chat search fix. The earlier voice and mobile checks used simulated audio, a mocked call SDK, and emulated phone viewports. [QA summary](testing.md#runs-85-and-86-verification)
- Fixed stale repository and public documentation links. Preserved workspace-only evidence paths and private GitHub run identifiers as text in the historical run notes.

## Screenshots

Captured the existing README filenames at 1440 × 900 in light mode using the offline browser-smoke workspace and fictional data. Home uses the date-only header and fixture weather. Chat uses the search fixture’s `orchid` results. Artifacts uses a seeded document, spreadsheet, and Page. [Home](screenshots/home.png), [Chat search](screenshots/chat-approval.png), [Artifacts](screenshots/artifacts-pages.png)

## Verification

| Check | Result |
| --- | --- |
| Python unittest discovery with `HEARTH_CJK_FONT` | 342 passed |
| Node unit tests | 37 passed |
| `node --check` | All 63 frontend JavaScript modules passed |
| Playwright Chromium | Default offline smoke and stream-disconnect regression passed |
| Screenshot capture | All three views rendered without console errors or warnings. Clicking a highlighted Chat search result focused the matched message. |
| Markdown links | Repository paths, heading fragments, and public URLs checked across README and the Markdown files in `docs/` |

The changes are limited to Markdown and the three README screenshots. Deployment and push were skipped.
