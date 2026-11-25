import assert from "node:assert/strict";
import { test } from "node:test";
import { artifactFilterFromHash, csvRows } from "../web/artifacts.js";

test("artifact route accepts type filters and the legacy Pages hash", () => {
  assert.equal(artifactFilterFromHash("#artifacts"), "all");
  assert.equal(artifactFilterFromHash("#artifacts/documents"), "documents");
  assert.equal(artifactFilterFromHash("#artifacts/pages"), "pages");
  assert.equal(artifactFilterFromHash("#pages"), "pages");
  assert.equal(artifactFilterFromHash("#artifacts/unknown"), undefined);
  assert.equal(artifactFilterFromHash("#connections/configured"), undefined);
});

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
