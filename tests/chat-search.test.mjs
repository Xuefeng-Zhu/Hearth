import assert from "node:assert/strict";
import test from "node:test";
import { chatSearchShortcut, groupChatResults, relativeChatTime } from "../web/chat-search.js";

test("chat search shortcuts only treat slash as a shortcut outside editing controls", () => {
  const editing = { closest: () => true };
  assert.equal(chatSearchShortcut({ key: "/", target: {} }), true);
  assert.equal(chatSearchShortcut({ key: "/", target: editing }), false);
  assert.equal(chatSearchShortcut({ key: "/", target: { isContentEditable: true } }), false);
  assert.equal(chatSearchShortcut({ key: "K", metaKey: true, target: editing }), true);
  assert.equal(chatSearchShortcut({ key: "k", ctrlKey: true, target: editing }), true);
  assert.equal(chatSearchShortcut({ key: "/", isComposing: true }), false);
  assert.equal(chatSearchShortcut({ key: "/", defaultPrevented: true }), false);
});

test("result groups keep the first-seen thread order and each thread's message order", () => {
  const row = (thread_id, id) => ({ id, thread_id, thread_title: thread_id.toUpperCase() });
  const source = [row("garden", 1), row("main", 2), row("garden", 3), row("travel", 4)];
  assert.deepEqual(groupChatResults(source), [
    { title: "GARDEN", results: [source[0], source[2]] },
    { title: "MAIN", results: [source[1]] },
    { title: "TRAVEL", results: [source[3]] },
  ]);
});

test("relative dates accept saved timestamps and omit invalid legacy values", () => {
  const now = Date.parse("2026-11-26T15:00:00Z");
  const format = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  assert.equal(relativeChatTime("2026-11-26T14:59:55Z", now), "Just now");
  assert.equal(relativeChatTime("2026-11-26T13:24:00Z", now), format.format(-1, "hour"));
  assert.equal(relativeChatTime("2026-11-19T15:00:00Z", now), format.format(-1, "week"));
  assert.equal(relativeChatTime("bad", now), "");
  assert.equal(relativeChatTime(null, now), "");
});
