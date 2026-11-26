import assert from "node:assert/strict";
import { test } from "node:test";
import { panelRequestFeedback, panelRequestPrompt } from "../web/home.js";

test("the description is sent as one Home panel request and preserves line breaks", () => {
  const description = "A checklist for the camping trip\nPack a tent and flashlight.";
  assert.equal(panelRequestPrompt(`  ${description}  `),
    `Create one Home panel from this description. Ask me in Chat for any required details.\n\n${description}`);
  assert.equal(panelRequestPrompt(" \n "), "");
});

test("Home reports confirmed panel creation even if the rest of the turn was interrupted", () => {
  const actions = new Map([
    ["unrelated", { kind: "worker", status: "complete" }],
    ["panel", { kind: "panel", status: "complete", panel_titles: ["Trip list"] }],
  ]);
  assert.deepEqual(panelRequestFeedback({ actions, error: "Interrupted." }),
    { message: "Trip list added to Home." });
});

test("Home sends users back to Chat for approvals or follow-up details", () => {
  const actions = new Map([["pending", { kind: "panel", status: "pending" }]]);
  assert.deepEqual(panelRequestFeedback({ actions }), { message: "Review the panel request in Chat.", openChat: true });
  assert.deepEqual(panelRequestFeedback({ actions: new Map() }),
    { message: "Continue the panel request in Chat.", openChat: true });
  assert.deepEqual(panelRequestFeedback({ error: "Server unavailable." }), { message: "Server unavailable." });
  assert.deepEqual(panelRequestFeedback({ stopped: true }), { message: "Panel request stopped." });
});
