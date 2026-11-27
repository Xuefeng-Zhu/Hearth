import { render } from "preact";
import { html } from "../ui.js";
import { listSearchPath } from "../list-search.js";
import { showLoading } from "../motion.js";
import { SkillEditor, SkillList, SkillsView } from "./view.js";

const get = (id) => document.getElementById(id);
const template = `---
name: ""
description: ""
when_to_use: ""
tools: []
---

1. Describe the first step.
`;

export function mountSkills(get) {
  render(html`<${SkillsView} />`, get("skills-view"));
  render(html`<${SkillEditor} />`, get("skill-editor"));
}

export function createSkills({ api, openChat, onLinkedClose, search }) {
  const library = get("skill-list");
  const status = get("skills-status");
  const editor = get("skill-editor");
  const form = get("skill-form");
  const source = get("skill-markdown");
  const history = get("skill-versions");
  const feedback = get("skill-feedback");
  const close = get("skill-close");
  let current;
  let draft;
  let viewing;
  let mode;
  let previewText;
  let confirming = false;
  let pending = false;
  let listRequest = 0;
  let opener;
  let linkedRequest;

  const detail = (id, version) => api("/api/skills/detail?" + new URLSearchParams({ id, ...(version ? { version } : {}) }));
  const cardButton = (id) => [...library.querySelectorAll("[data-skill]")].find((button) => button.dataset.skill === id);

  function paintEditor() {
    render(html`<${SkillEditor} skill=${current} ...${{ mode, previewText, viewing, pending, confirming }} />`, editor);
  }

  function toggle(next) {
    mode = next;
    if (mode === "preview") previewText = source.value.replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/, "").trim();
    paintEditor();
  }

  function setVersion(version, content) {
    viewing = version;
    source.value = content;
    confirming = false;
    toggle(mode);
    history.value = viewing || "";
  }

  function display(skill, nextMode) {
    current = skill;
    draft = skill?.markdown || template;
    mode = nextMode || (skill?.builtin ? "preview" : "source");
    setVersion(skill?.revision, draft);
  }

  async function perform(action, target = feedback) {
    if (pending) return;
    pending = true;
    target.textContent = "";
    paintEditor();
    try {
      await action();
    } catch (error) {
      target.textContent = error.message;
    } finally {
      pending = false;
      paintEditor();
    }
  }

  function open(skill, trigger) {
    opener = trigger;
    feedback.textContent = "";
    display(skill);
    editor.showModal();
    if (!skill) {
      source.focus();
      const start = source.value.indexOf('""') + 1;
      source.setSelectionRange(start, start);
    }
  }

  function openCard(id, trigger) {
    const sequence = listRequest;
    return perform(async () => {
      const loaded = await detail(id);
      if (sequence === listRequest && trigger.checkVisibility()) open(loaded, trigger);
    }, status);
  }

  async function load() {
    const request = ++listRequest;
    const { query } = search;
    if (!query && !library.childElementCount) showLoading(status, "Loading skills…");
    try {
      const { skills } = await api(listSearchPath("/api/skills", query));
      if (request !== listRequest || query !== search.query) return;
      render(html`<${SkillList} skills=${skills} open=${openCard} />`, library);
      search.count(skills.length);
      status.textContent = skills.length || query ? "" : "No skills yet.";
    } catch (error) {
      if (request === listRequest && query === search.query) {
        search.fail();
        status.textContent = error.message;
      }
    }
  }

  function clearLink() {
    linkedRequest = undefined;
    if (editor.open) editor.close();
  }

  async function loadLinked(id) {
    clearLink();
    const request = id ? { id } : undefined;
    linkedRequest = request;
    await load();
    if (!request || linkedRequest !== request) return;
    try {
      const skill = await detail(id);
      if (linkedRequest === request) {
        request.opened = true;
        open(skill, cardButton(id));
      }
    } catch (error) {
      if (linkedRequest === request) status.textContent = error.message;
    }
  }

  get("skill-new").addEventListener("click", (event) => { if (!pending) open(null, event.currentTarget); });
  close.addEventListener("click", () => { if (!pending) editor.close(); });
  editor.addEventListener("cancel", (event) => { if (pending) event.preventDefault(); });
  editor.addEventListener("close", () => {
    if (editor.open) return;
    if (linkedRequest?.opened) {
      onLinkedClose(linkedRequest.id);
      linkedRequest = undefined;
    }
    const replacement = opener?.dataset.skill && cardButton(opener.dataset.skill);
    const control = opener?.isConnected ? opener : replacement || get("skill-new");
    if (control.checkVisibility()) control.focus();
  });
  get("skill-source-mode").addEventListener("click", () => toggle("source"));
  get("skill-preview-mode").addEventListener("click", () => toggle("preview"));

  history.addEventListener("change", () => {
    if (pending) {
      history.value = viewing;
      return;
    }
    const version = history.value;
    if (viewing === current.revision) draft = source.value;
    perform(async () => {
      try {
        const content = version === current.revision ? draft : (await detail(current.id, version)).markdown;
        setVersion(version, content);
      } catch (error) {
        history.value = viewing;
        throw error;
      }
    });
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (source.readOnly) return;
    perform(async () => {
      const markdown = source.value;
      const saved = current
        ? await api("/api/skills/save", { id: current.id, revision: current.revision, markdown })
        : await api("/api/skills/create", { markdown });
      display(saved, mode);
      await load();
      feedback.textContent = "Skill saved.";
    });
  });

  get("skill-duplicate").addEventListener("click", () => perform(async () => {
    display(await api("/api/skills/duplicate", { id: current.id }), "source");
    await load();
    source.focus();
    feedback.textContent = "Copy created.";
  }));
  get("skill-delete").addEventListener("click", () => {
    confirming = true;
    paintEditor();
    get("skill-delete-cancel").focus();
  });
  get("skill-delete-cancel").addEventListener("click", () => {
    confirming = false;
    paintEditor();
    get("skill-delete").focus();
  });
  get("skill-delete-confirm-button").addEventListener("click", () => perform(async () => {
    await api("/api/skills/delete", { id: current.id, revision: current.revision });
    await load();
    editor.close();
    status.textContent = "Skill deleted. You can undo the deletion in Timeline.";
  }));
  get("skill-try").addEventListener("click", () => perform(async () => {
    const thread = await api("/api/skills/try", { id: current.id });
    editor.close();
    await openChat(thread);
  }));
  return { load, loadLinked, clearLink };
}
