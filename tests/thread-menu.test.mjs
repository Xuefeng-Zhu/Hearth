import assert from "node:assert/strict";
import { test } from "node:test";
import { threadMenuIndex, threadMenuPosition } from "../web/thread-menu.js";

const viewport = { top: 0, left: 0, right: 390, bottom: 844 };
const menu = { width: 200, height: 160 };

test("the fallback aligns the popover to the button's bottom and right edges", () => {
  const anchor = { top: 350, bottom: 394, left: 272, right: 316 };
  assert.deepEqual(threadMenuPosition(anchor, menu, viewport, 4, 8), { left: 116, top: 398 });
});

test("the fallback flips the popover above and to the right of a button near the edges", () => {
  const anchor = { top: 770, bottom: 814, left: 24, right: 68 };
  assert.deepEqual(threadMenuPosition(anchor, menu, viewport, 4, 8), { left: 24, top: 606 });
});

test("the fallback clamps to the inset when the zoomed viewport has no room to flip", () => {
  const zoomed = { top: 500, left: 60, right: 290, bottom: 750 };
  const anchor = { top: 601, bottom: 645, left: 237, right: 281 };
  assert.deepEqual(threadMenuPosition(anchor, menu, zoomed, 4, 8), { left: 81, top: 582 });
});

test("menu navigation wraps, jumps to the endpoints, and handles an empty menu", () => {
  for (const [key, current, count, expected] of [
    ["ArrowDown", 2, 3, 0], ["ArrowUp", 0, 3, 2], ["ArrowUp", -1, 3, 2],
    ["Home", 1, 3, 0], ["End", 1, 3, 2], ["ArrowDown", 0, 1, 0],
    ["ArrowDown", -1, 0, -1], ["Enter", 1, 3, -1],
  ]) assert.equal(threadMenuIndex(key, current, count), expected);
});
