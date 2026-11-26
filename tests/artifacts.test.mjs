import assert from "node:assert/strict";
import { test } from "node:test";
import { artifactFilterFromHash, csvRows } from "../web/artifacts.js";
import { fileAnswerSources } from "../web/file-questions.js";

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

test("file citations turn only exact Box file destinations into links", (t) => {
  function element(tag) {
    return {
      tag, children: [], attributes: {},
      append(...children) { this.children.push(...children); },
      setAttribute(name, value) { this.attributes[name] = value; },
    };
  }
  const previous = globalThis.document;
  globalThis.document = { createElement: element, createElementNS: (_, tag) => element(tag) };
  t.after(() => {
    if (previous === undefined) delete globalThis.document;
    else globalThis.document = previous;
  });
  const filename = "Museum <schedule>.docx";
  const boxURL = "https://app.box.com/file/123";
  const view = fileAnswerSources({ source: "Answered by Hearth from your Box files", citations: [
    { filename, box_url: boxURL },
    { filename: "Other host", box_url: "https://app.box.com.example.invalid/file/123" },
    { filename: "Redirect", box_url: boxURL + "?redirect=elsewhere" },
    { filename: "Unsafe scheme", box_url: "javascript:void(0)" },
  ] });
  const list = view.children.find((child) => child.tag === "ul");
  assert.equal(list.children.length, 1);
  const [name, link] = list.children[0].children;
  assert.equal(name.textContent, filename);
  assert.equal(link.href, boxURL);
  assert.equal(link.rel, "noopener noreferrer");
  assert.equal(link.attributes["aria-label"], `Open ${filename} in Box`);
});
