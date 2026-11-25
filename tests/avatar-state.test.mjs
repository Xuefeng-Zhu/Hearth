import assert from "node:assert/strict";
import { test } from "node:test";
import { avatarEvent, avatarPose, IDLE_MS, mouthFor, newAvatar } from "../web/avatar-state.js";

test("typing and recording wake only their own thread", () => {
  const first = newAvatar(0);
  const second = newAvatar(0);
  const typing = avatarEvent(first, { type: "typing", gaze: .5 }, IDLE_MS);
  assert.deepEqual(avatarPose(typing, IDLE_MS), { pose: "listening", gaze: .5 });
  assert.equal(avatarPose(second, IDLE_MS).pose, "sleeping");
  const recording = avatarEvent(typing, { type: "recording", active: true }, IDLE_MS);
  assert.equal(avatarPose(recording, IDLE_MS * 2).detail, "Microphone on");
  const stopped = avatarEvent(recording, { type: "recording", active: false }, IDLE_MS * 2);
  assert.equal(avatarPose(stopped, IDLE_MS * 2).pose, "idle");
});

test("a turn passes through tool work, speech, recall, celebration and scheduled sleep", () => {
  let ember = newAvatar(0);
  const signal = (type, now, fields) => {
    ember = avatarEvent(ember, { type, ...fields }, now);
    return avatarPose(ember, now);
  };
  assert.equal(signal("started", 10).pose, "thinking");
  assert.deepEqual(signal("tool_started", 20, { title: "Searching the web" }),
    { pose: "working", detail: "Searching the web" });
  assert.equal(signal("tool_finished", 30).pose, "thinking");
  assert.equal(signal("token", 40, { text: "Hello" }).mouth, mouthFor("Hello"));
  assert.deepEqual(avatarPose(ember, 201), { pose: "speaking", mouth: 0 });
  signal("reminder", 220, { until: 10_000 });
  assert.equal(signal("done", 300, { remembered: true }).pose, "remembering");
  assert.equal(avatarPose(ember, 2000).pose, "happy");
  assert.deepEqual(avatarPose(ember, 4000), { pose: "sleeping", detail: "Reminder scheduled" });
  assert.equal(avatarPose(ember, 10_000).pose, "idle");
});

test("warnings interrupt briefly, and a queued follow-up does not replace a working turn", () => {
  let ember = newAvatar(0);
  ember = avatarEvent(ember, { type: "tool_started", title: "Saving memory" }, 10);
  ember = avatarEvent(ember, { type: "queued" }, 20);
  assert.equal(avatarPose(ember, 20).pose, "working");
  ember = avatarEvent(ember, { type: "warning" }, 30);
  assert.equal(avatarPose(ember, 100).pose, "concerned");
  assert.equal(avatarPose(ember, 2000).pose, "working");
  ember = avatarEvent(ember, { type: "error" }, 2000);
  assert.equal(avatarPose(ember, 2100).pose, "concerned");
  ember = avatarEvent(ember, { type: "approval_started", title: "Email draft" }, 4000);
  assert.equal(avatarPose(ember, 4000).detail, "Email draft");
  ember = avatarEvent(ember, { type: "approval_done", success: true }, 4100);
  assert.equal(avatarPose(ember, 4100).pose, "happy");
  assert.ok(mouthFor("A whole phrase") > mouthFor("hi"));
  assert.ok(mouthFor("hello!") < mouthFor("hello,"));
  assert.equal(mouthFor(" "), 0);
});
