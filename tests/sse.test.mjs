import assert from "node:assert/strict";
import test from "node:test";
import { createSSEParser } from "../web/sse.js";

const bytes = (text) => new TextEncoder().encode(text);

test("SSE handles every byte boundary, mixed line endings, and multiline data", () => {
  const wire = bytes("\uFEFF: heartbeat\r\nid: 1\r\nevent: token\r\ndata: {\r\ndata: \"text\":\"é🔥\"}\r\n\r\n" +
    "ignored: field\rdata:  leading space\r\r" + "event: no-data\n\ndata\n\n");
  const expected = [
    { event: "token", data: '{\n"text":"é🔥"}', id: "1", lastEventId: "1" },
    { event: "message", data: " leading space", id: undefined, lastEventId: "1" },
    { event: "message", data: "", id: undefined, lastEventId: "1" },
  ];
  for (let split = 0; split <= wire.length; split++) {
    const parser = createSSEParser();
    assert.deepEqual([...parser.push(wire.slice(0, split)), ...parser.push(wire.slice(split))], expected);
  }
  const parser = createSSEParser();
  assert.deepEqual([...wire].flatMap((value) => parser.push(Uint8Array.of(value))), expected);
});

test("SSE keeps the committed cursor across reconnect and drops an unfinished frame", () => {
  const first = createSSEParser();
  assert.equal(first.push(bytes("id: 18\nretry: 4000\ndata: complete\n\nid: 19\ndata: partial\n")).length, 1);
  assert.equal(first.lastEventId, "18");
  assert.equal(first.retry, 4000);
  const second = createSSEParser(first.lastEventId);
  assert.deepEqual(second.push(bytes("retry: invalid\nid: invalid\0id\ndata: fresh\n\nid:\n\ndata: default\n\n")), [
    { event: "message", data: "fresh", id: undefined, lastEventId: "18" },
    { event: "message", data: "default", id: undefined, lastEventId: "" },
  ]);
  assert.equal(second.lastEventId, "");
  assert.equal(second.retry, undefined);
});
