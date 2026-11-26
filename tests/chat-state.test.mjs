import assert from "node:assert/strict";
import test from "node:test";
import { conversationView, newConversation, reconcile } from "../web/chat-state.js";

const user = (id) => ({ id, role: "user", content: "Same prompt" });
const reply = (id, prompt) => ({ id, role: "assistant", content: "The final answer", reply_to: prompt.id });
const snapshot = (messages, fields = {}) => ({ thread_id: "main", messages, actions: [], workers: [],
  history_revision: "a", message_artifacts: {}, message_uploads: {}, ...fields });

function fixture() {
  let state = newConversation("main");
  const apply = (update) => {
    const result = reconcile(state, update);
    state = result.state;
    return result.completed.map(({ reply }) => reply);
  };
  return {
    get state() { return state; },
    view: () => conversationView(state),
    apply,
    poll: (messages, fields) => apply({ type: "snapshot", snapshot: snapshot(messages, fields) }),
    begin: (key, threadId = "main") => apply({ type: "begin", key, source: threadId,
      turn: { threadId, prompt: "Same prompt", attachments: [] } }),
    stream: (key, name, payload, eventId) => apply({ type: "stream", key, name, payload, eventId }),
  };
}

test("an optimistic prompt is replaced by its stored row and a dropped stream by its own saved reply", () => {
  const f = fixture();
  const prompt = user("u1"), nextPrompt = user("u2"), answer = reply("a1", prompt);
  f.begin("first");
  assert.equal(f.view().local[0].showPrompt, true);
  assert.equal(f.view().local[0].showReply, false);
  f.stream("first", "queued", { thread: { id: "main" }, reply_id: "stop-one", prompt: "Same prompt" });
  f.stream("first", "started", { message: prompt });
  const optimistic = f.state;
  f.stream("first", "token", { text: "The" });
  assert.equal(optimistic.turns.get("first").text, "");
  f.apply({ type: "finish", key: "first", error: "SSE closed" });
  f.poll([prompt]);
  assert.equal(f.view().local[0].showPrompt, false);
  assert.equal(f.view().local[0].text, "The");

  f.poll([prompt, nextPrompt, reply("a2", nextPrompt)]);
  assert.equal(f.view().local.length, 1);
  assert.deepEqual(f.poll([prompt, nextPrompt, reply("a2", nextPrompt), answer]), [answer]);
  assert.deepEqual(f.view().local, []);
  assert.equal(f.view().transcript.messages.filter((message) => message.id === answer.id).length, 1);
  assert.deepEqual(f.stream("first", "done", { message: answer }), []);
  assert.deepEqual(f.stream("first", "token", { text: " late" }), []);
  assert.deepEqual(f.poll([prompt, nextPrompt, reply("a2", nextPrompt), answer]), []);
});

test("replayed SSE IDs are ignored, including deltas after completion", () => {
  const f = fixture();
  const prompt = user("u"), answer = reply("a", prompt);
  f.begin("local");
  f.stream("local", "started", { message: prompt }, "1");
  f.stream("local", "token", { text: "ha" }, "2");
  f.stream("local", "token", { text: "ha" }, "2");
  f.stream("local", "token", { text: "ha" }, "3");
  assert.equal(f.view().local[0].text, "haha");
  f.stream("local", "reset", {}, "4");
  f.stream("local", "token", { text: "The final" });
  assert.deepEqual(f.stream("local", "done", { message: answer }, "5"), [answer]);
  assert.deepEqual(f.stream("local", "done", { message: answer }, "5"), []);
  f.stream("local", "token", { text: " late" }, "6");
  assert.equal(f.view().local[0].text, "The final");
  assert.deepEqual(f.poll([prompt, answer]), []);
  assert.deepEqual(f.view().local, []);
});

test("a snapshot that beats the started frame settles the optimistic turn when its ID arrives", () => {
  const f = fixture();
  const prompt = user("user"), answer = reply("answer", prompt);
  f.begin("local");
  assert.deepEqual(f.poll([prompt, answer]), []);
  assert.deepEqual(f.stream("local", "started", { message: prompt }), [answer]);
  assert.deepEqual(f.view().local, []);
});

test("streaming, stopping, and late snapshots stay isolated across a thread switch", () => {
  const f = fixture();
  const prompt = user("u"), answer = reply("a", prompt);
  f.begin("local");
  f.stream("local", "started", { message: prompt });
  f.stream("local", "token", { text: "one" });
  f.apply({ type: "select", threadId: "side" });
  f.begin("side-turn", "side");
  f.poll([prompt, answer]);
  f.stream("local", "token", { text: " two" });
  assert.deepEqual(f.view().local.map((turn) => turn.key), ["side-turn"]);
  assert.deepEqual(f.view().transcript, {});
  f.stream("side-turn", "stopped", {});
  assert.deepEqual(f.stream("side-turn", "done", { message: answer }), []);

  f.apply({ type: "select", threadId: "main" });
  assert.deepEqual(f.view().local.map((turn) => turn.text), ["one two"]);
  assert.deepEqual(f.stream("local", "done", { message: answer }), [answer]);
  f.poll([prompt, answer]);
  assert.deepEqual(f.view().local, []);
});

test("paged rows merge by ID and refresh without losing history as the latest window moves", () => {
  const f = fixture();
  const first = user("u1"), second = user("u2"), third = user("u3"), fourth = user("u4");
  const previous_prompt = { content: "An older prompt", attachment_ids: [] };
  f.poll([second, third], { before: "cursor-b", actions: [{ id: "action", status: "complete" }] });
  const older = snapshot([first, second], { previous_prompt,
    actions: [{ id: "action", status: "pending" }], message_artifacts: { u1: ["keep"], u2: ["stale"] } });
  f.apply({ type: "page", page: older, cursor: "cursor-b" });
  assert.deepEqual(f.view().transcript.messages, [first, second, third]);
  assert.deepEqual(f.view().transcript.actions, [{ id: "action", status: "complete" }]);
  assert.deepEqual(f.view().transcript.message_artifacts, { u1: ["keep"] });
  assert.equal(f.view().transcript.previous_prompt, previous_prompt);
  f.poll([third, fourth], { before: "cursor-c" });
  assert.deepEqual(f.view().transcript.messages, [first, second, third, fourth]);
  const archive = f.state.pages.at(-1);
  f.apply({ type: "page", previous: archive, page: snapshot([first, second], { record_revision: "latest" }) });
  assert.deepEqual(f.state.pages.at(-1).messages, [second]);
  assert.equal(f.state.pages.at(-1).record_revision, "latest");
  f.poll([fourth], { history_revision: "b" });
  f.apply({ type: "page", page: older, cursor: "cursor-b" });
  assert.deepEqual(f.state.pages, []);
  assert.deepEqual(f.view().transcript.messages, [fourth]);
});

test("a proposal keeps its card and accepts status changes on an older transcript page", () => {
  const f = fixture();
  const message = { ...reply("proposal-message", user("request")), self_update_id: "proposal" };
  const proposal = { id: "proposal", status: "waiting" };
  f.poll([user("recent")], { before: "older" });
  f.apply({ type: "page", cursor: "older", page: snapshot([message], { self_updates: [proposal] }) });
  assert.deepEqual(f.view().transcript.self_updates, [proposal]);
  const updated = { ...proposal, status: "updated" };
  f.apply({ type: "page", previous: f.state.pages[0], page: snapshot([message], { self_updates: [updated] }) });
  assert.deepEqual(f.view().transcript.self_updates, [updated]);
});
