import { test } from "node:test";
import assert from "node:assert/strict";
import { proposalPresentation } from "../web/self-update.js";

test("a self-update card offers approval once and allows revision while waiting", () => {
  assert.deepEqual(proposalPresentation({ status: "review", checks: "none" }), {
    stage: "Ready for review", checks: "No checks reported", guard: "",
    approve: true, revise: true, refresh: false, discard: true, complete: false,
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

test("the card names the guard and offers refresh only when main moved", () => {
  for (const [state, stage, guard, approve, refresh] of [
    [{ status: "review", checks: "pending", guard: "hearth" }, "Waiting for tests", "Hearth's own checks", true, false],
    [{ status: "review", checks: "missing", guard: "hearth" }, "Ready for review", "Hearth's own checks", false, false],
    [{ status: "review", checks: "passed", guard: "hearth", ready: true },
      "Ready to merge", "Hearth's own checks: tests passed on an up-to-date branch", true, false],
    [{ status: "review", checks: "passed", guard: "github", ready: true }, "Ready to merge", "GitHub branch protection", true, false],
    [{ status: "behind", checks: "passed", guard: "hearth" }, "Proposal is behind main", "Hearth's own checks", false, true],
  ]) {
    const view = proposalPresentation(state);
    assert.deepEqual([view.stage, view.guard, view.approve, view.refresh], [stage, guard, approve, refresh]);
  }
});

test("completion names the deployed short SHA", () => {
  const view = proposalPresentation({ status: "updated", checks: "passed", merge_sha: "abcdef01234567" });
  assert.equal(view.stage, "Hearth updated to abcdef0");
  assert.equal(view.complete, true);
  assert.equal(view.approve || view.revise || view.discard, false);
});
