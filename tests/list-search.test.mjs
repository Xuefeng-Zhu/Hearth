import assert from "node:assert/strict";
import test from "node:test";
import { listSearchHash, listSearchPath, listSearchRoute } from "../web/list-search.js";
import { slashSearchShortcut } from "../web/dom.js";

test("list search routes preserve literal queries and linked skill IDs", () => {
  const hash = listSearchHash("skills", "café & ? + /", "playbook/1");
  assert.deepEqual(listSearchRoute(hash), {
    view: "skills", query: "café & ? + /", target: "playbook/1", hash,
  });
  assert.equal(listSearchRoute("#inbox?q=%20%20").hash, "#inbox");
  assert.equal(listSearchRoute("#inbox?q=" + "🌻".repeat(201)).query, "🌻".repeat(200));
  assert.equal(listSearchRoute("#skills/%C3").hash, "#skills");
  assert.equal(listSearchRoute("#inbox/review?q=sample"), undefined);
  assert.equal(listSearchRoute("#timeline/errors"), undefined);
  assert.equal(listSearchPath("/api/inbox", "%_&"), "/api/inbox?q=%25_%26");
  assert.equal(listSearchPath("/api/inbox", ""), "/api/inbox");
});

test("slash focuses search only outside editing controls", () => {
  assert.equal(slashSearchShortcut({ key: "/" }), true);
  for (const key of ["defaultPrevented", "repeat", "isComposing", "altKey", "shiftKey", "metaKey", "ctrlKey"]) {
    assert.equal(slashSearchShortcut({ key: "/", [key]: true }), false);
  }
  assert.equal(slashSearchShortcut({ key: "/", target: { isContentEditable: true } }), false);
  assert.equal(slashSearchShortcut({ key: "/", target: { closest: () => ({}) } }), false);
  assert.equal(slashSearchShortcut({ key: "?" }), false);
});
