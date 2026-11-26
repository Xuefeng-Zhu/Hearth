# Run 52 — Agent tool calls

`hearth/agent.py` went from 2,676 lines before Run 52 to 2,379 after it, a reduction of 297 lines. Both tool loops now use the same helpers for argument decoding, object validation, availability checks, reminder normalization, and model-facing result construction. The static system prompts and tool schemas match the pre-extraction values, including tool order. [Agent](../hearth/agent.py) · [Tool-call helpers](../hearth/tool_calls.py) · [Prompts and schemas](../hearth/agent_definitions.py)

Seven new characterization tests passed before the extraction. Together with the existing chat and worker tests, they cover the behaviors below. [Characterization tests](../tests/test_tool_loops.py) · [Chat tests](../tests/test_hearth.py) · [Worker tests](../tests/test_workers.py)

| Behavior | Parent chat | Worker |
| --- | --- | --- |
| Tool budget | Rejects a batch larger than eight and stops after nine tool rounds. | Takes up to four calls and uses a text-only model call to synthesize at the limit. |
| Approval | Finishes the reply with a pending proposal. | Waits for interactive approval. A recurring run hands off its proposal. |
| Model failure | Tries the next model in the route and preserves already staged actions. | Keeps the assigned model. Failure before tools ends the worker. Failure after tools can lead to synthesis from recorded evidence. |
| Availability and arguments | Reports malformed JSON before checking availability. | Checks delegation before decoding the arguments. |
| Reminders | Derives delivery and urgency from the current user message sent to the model. | Derives delivery and urgency from the original user request. |
| Tool results | Sends full JSON with the tool-call ID. | Uses the same result message and caps large results with a preview. Both loops preserve Run 50’s untrusted marker. |

## Verification

- `python -m unittest discover -s tests` passed all 255 tests, including the Run 50 untrusted-content tests.
- `node --test tests/*.test.mjs` passed all 9 tests. `node --check` passed for all 25 `web/*.js` files.
- `scripts/deploy.sh` completed on November 26, 2026. At 08:41 UTC the deployed service returned HTTP 200 from `/health` with Sprite checkpoints enabled. The deployed agent sources matched the local files by SHA-256.
- A temporary workspace on the Sprite used the deployed runtime, the Chat API, and live connectors. A normal Hugging Face reply returned the expected arithmetic answer, a second reply cited a source after Exa returned results, and exactly one worker completed a delegated note read that the parent incorporated in its reply. The temporary workspace was removed after the smoke checks.
