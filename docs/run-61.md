# Run 61 — D16 test coverage

The deployment workflow requires an offline Chromium smoke alongside Python, Node, and JavaScript syntax checks. The browser test starts Hearth on loopback with temporary storage and a mock model. It opens Home and Chat, reads a streamed reply, stops a second reply, switches threads, opens Settings, and navigates from the 390×844 drawer.

The manual edge matrix checks anonymous GET and POST on private workspace routes and verifies active, missing, malformed, unknown, and revoked Page share tokens. Its parser and redirect handling are covered by the Python suite. The full matrix passed against local fixture origins and rejected a simulated unauthenticated 200 from `/health`. Live edge verification requires an operator to supply fixture URLs. [Testing guide](testing.md)

The separate Chromium disconnect regression cancels SSE after the first token. The server persists exactly one complete reply and the open transcript polls it successfully. Chromium still finds two assistant rows because the partial bubble remains alongside the saved reply. That duplicate assertion fails on the baseline and stays outside the deploy gate pending the frontend fix.

## Verification

- All 246 Python unit tests passed, including the 5 edge parsing and request tests.
- The offline Chromium smoke passed locally in 43 seconds.
- All 9 Node tests and the syntax checks for every `web/*.js` file passed.
- The workflow dependency, shell syntax, and edge fixture checks passed locally.
