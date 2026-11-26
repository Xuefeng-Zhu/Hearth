import { test } from "node:test";
import assert from "node:assert/strict";
import { proposalPresentation } from "../web/self-update.js";

test("a self-update card offers approval once and allows revision while waiting", () => {
  assert.deepEqual(proposalPresentation({ status: "review", checks: "none" }), {
    stage: "Ready for review", checks: "No checks reported", approve: true, revise: true, discard: true, complete: false,
  });
  for (const [status, checks, labels, controls] of [
    ["review", "failed", ["Ready for review", "Tests failed"], [false, true, true]],
    ["waiting", "pending", ["Waiting for tests", "Tests running"], [false, true, true]],
    ["stale", "passed", ["Needs a fresh proposal", "Tests passed"], [false, false, true]],
    ["updating", "passed", ["Updating Hearth…", "Tests passed"], [false, false, false]],
    ["discarded", "checking", ["Proposal discarded", "Checking CI…"], [false, false, false]],
  ]) {
    const view = proposalPresentation({ status, checks });
    assert.deepEqual([view.stage, view.checks], labels);
    assert.deepEqual([view.approve, view.revise, view.discard], controls);
  }
});

test("completion names the deployed short SHA", () => {
  const view = proposalPresentation({ status: "updated", checks: "passed", merge_sha: "abcdef01234567" });
  assert.equal(view.stage, "Hearth updated to abcdef0");
  assert.equal(view.complete, true);
  assert.equal(view.approve || view.revise || view.discard, false);
});
