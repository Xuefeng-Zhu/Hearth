import assert from "node:assert/strict";
import test from "node:test";
import { commitOption, filterOptions } from "../web/combobox.js";

const options = [
  { label: "All threads", value: "" },
  { label: "Café planning", value: "thread-alfa" },
  { label: "Résumé edits", value: "editorial" },
  { label: "Travel", value: "thread-café" },
];

test("filtering matches substrings in labels and values without accents or case", () => {
  assert.deepEqual(filterOptions(options, "  CaFe "), [options[1], options[3]]);
  assert.deepEqual(filterOptions(options, "SUME\u0301"), [options[2]]);
  assert.deepEqual(filterOptions(options, "ALFA"), [options[1]]);
  assert.deepEqual(filterOptions(options, " "), options);
  assert.deepEqual(filterOptions(options, "absent"), []);
});

function selectFixture(options) {
  const select = new EventTarget();
  select.options = options;
  select.selectedIndex = 0;
  select.matches = (selector) => selector === ":disabled" && !!select.disabled;
  Object.defineProperty(select, "value", { get: () => options[select.selectedIndex].value });
  return select;
}

test("committing sets native selection before bubbling input and change", () => {
  const select = selectFixture(options);
  const events = [];
  for (const type of ["input", "change"]) {
    select.addEventListener(type, (event) => events.push([event.type, event.bubbles, event.target.value]));
  }
  assert.equal(commitOption(select, 2), true);
  assert.equal(select.selectedIndex, 2);
  assert.deepEqual(events, [["input", true, "editorial"], ["change", true, "editorial"]]);
  assert.equal(commitOption(select, 2), false);
  assert.equal(events.length, 2);
});

test("commit skips disabled, hidden and missing options and respects a disabled select", () => {
  const select = selectFixture([
    options[0], { ...options[1], disabled: true }, { ...options[2], parentElement: { disabled: true } },
    { ...options[3], hidden: true }, { ...options[1], parentElement: { hidden: true } }, options[2],
  ]);
  select.addEventListener("change", () => assert.fail("Unavailable choices must never emit a change"));
  for (const index of [-1, 1, 2, 3, 4, 6]) assert.equal(commitOption(select, index), false);
  select.disabled = true;
  assert.equal(commitOption(select, 5), false);
  assert.equal(select.selectedIndex, 0);
});

test("duplicate option values keep the chosen native index without a value change event", () => {
  const select = selectFixture([options[0], options[1], { ...options[1], label: "Other label" }]);
  assert.equal(commitOption(select, 1), true);
  select.addEventListener("change", () => assert.fail("The value did not change"));
  assert.equal(commitOption(select, 2), false);
  assert.equal(select.selectedIndex, 2);
});
