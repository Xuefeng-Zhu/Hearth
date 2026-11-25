import assert from "node:assert/strict";
import { test } from "node:test";
import { csvRows } from "../web/artifacts.js";

test("CSV preview preserves quoted commas, escaped quotes, and multiline cells", () => {
  assert.deepEqual(csvRows('Item,Note\r\n"Cranberries, fresh","Say ""hello"""\r\nPie,"First\nSecond"\r\n'), [
    ["Item", "Note"], ["Cranberries, fresh", 'Say "hello"'], ["Pie", "First\nSecond"],
  ]);
});

test("CSV preview preserves blank trailing fields and skips a final line break", () => {
  assert.deepEqual(csvRows('Name,Quantity,\nPie,,""'), [["Name", "Quantity", ""], ["Pie", "", ""]]);
  assert.deepEqual(csvRows(""), []);
  assert.deepEqual(csvRows("Pie\n"), [["Pie"]]);
});
