import { markdown } from "./artifacts.js";
import { icon } from "./icons.js";
import { timeFormatter } from "./time.js";

const get = (id) => document.getElementById(id);
const date = timeFormatter({ dateStyle: "medium", timeStyle: "short" });
const template = `---
name: ""
description: ""
when_to_use: ""
tools: []
---

1. Describe the first step.
`;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function skillChip(skill, label = "Using skill") {
  const chip = element(skill.id ? "a" : "span", "skill-chip");
  if (skill.id) chip.href = `#skills/${encodeURIComponent(skill.id)}`;
  chip.append(icon("skill", 15), element("span", "", `${label}: ${skill.name}`));
  return chip;
}

export function createSkills({ api, openChat, onLinkedClose }) {
  const library = get("skill-list");
  const status = get("skills-status");
  const editor = get("skill-editor");
  const form = get("skill-form");
  const title = get("skill-title");
  const source = get("skill-markdown");
  const preview = get("skill-preview");
  const history = get("skill-versions");
  const feedback = get("skill-feedback");
  const confirm = get("skill-delete-confirm");
  const close = get("skill-close");
  let current;
  let draft;
  let viewing;
  let mode;
  let pending = false;
  let listRequest = 0;
  let opener;
  let linkedRequest;

  const detail = (id, version) => api("/api/skills/detail?" + new URLSearchParams({ id, ...(version ? { version } : {}) }));
  const cardButton = (id) => [...library.querySelectorAll("[data-skill]")].find((button) => button.dataset.skill === id);

  function toggle(next) {
    mode = next;
    const showing = mode === "preview";
    get("skill-source").hidden = showing;
    preview.hidden = !showing;
    get("skill-source-mode").setAttribute("aria-pressed", String(!showing));
    get("skill-preview-mode").setAttribute("aria-pressed", String(showing));
    if (showing) {
      const body = source.value.replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/, "").trim();
      preview.replaceChildren(body ? markdown(body) : element("p", "meta", "Add instructions to preview the playbook."));
    }
  }

  function setVersion(version, content) {
    viewing = version;
    history.value = viewing || "";
    const historical = !!viewing && viewing !== current?.revision;
    source.value = content;
    source.readOnly = !!current?.builtin || historical;
    source.setAttribute("aria-readonly", String(source.readOnly));
    get("skill-save").hidden = source.readOnly;
    get("skill-delete").hidden = !current || source.readOnly;
    get("skill-try").hidden = !current || historical;
    confirm.hidden = true;
    toggle(mode);
  }

  function display(skill, nextMode) {
    current = skill;
    draft = skill?.markdown || template;
    mode = nextMode || (skill?.builtin ? "preview" : "source");
    title.textContent = skill?.name || "New skill";
    get("skill-description").textContent = skill?.builtin ? "Built-in playbook · Duplicate it to make changes."
      : skill?.description || "Write a Markdown playbook Hearth can load in chat.";
    get("skill-duplicate").hidden = !skill?.builtin;
    get("skill-history").hidden = !skill?.versions.length;
    history.replaceChildren(...(skill?.versions || []).map((version) => {
      const label = `Version ${version.number} · ${version.id === skill.revision ? "Current" : date.format(new Date(version.at))}`;
      return new Option(label, version.id);
    }));
    setVersion(skill?.revision, draft);
  }

  async function perform(action, target = feedback) {
    if (pending) return;
    pending = true;
    target.textContent = "";
    form.setAttribute("aria-busy", "true");
    try {
      await action();
    } catch (error) {
      target.textContent = error.message;
    } finally {
      pending = false;
      form.removeAttribute("aria-busy");
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

  function card(skill) {
    const article = element("article", "skill-card");
    const mark = element("span", "skill-mark");
    mark.append(icon("skill", 21));
    const text = element("div", "skill-card-body");
    const heading = element("h3");
    const link = element("button", "skill-card-link", skill.name);
    link.type = "button";
    link.dataset.skill = skill.id;
    link.setAttribute("aria-haspopup", "dialog");
    link.addEventListener("click", () => perform(async () => {
      const loaded = await detail(skill.id);
      if (link.checkVisibility()) open(loaded, link);
    }, status));
    heading.append(link);
    const stats = element("div", "skill-stats");
    const lastUsed = element("span", "", "Never used");
    if (skill.last_used) {
      const last = element("time", "", date.format(new Date(skill.last_used)));
      last.dateTime = skill.last_used;
      lastUsed.replaceChildren("Last used ", last);
    }
    stats.append(lastUsed, element("span", "", `${skill.use_count} ${skill.use_count === 1 ? "use" : "uses"}`));
    if (skill.builtin) stats.prepend(element("span", "skill-badge", "Built-in"));
    text.append(heading, element("p", "", skill.description), stats);
    article.append(mark, text);
    return article;
  }

  async function load() {
    const request = ++listRequest;
    if (!library.childElementCount) status.textContent = "Loading skills…";
    try {
      const { skills } = await api("/api/skills");
      if (request !== listRequest) return;
      library.replaceChildren(...skills.map(card));
      status.textContent = skills.length ? "" : "No skills yet.";
    } catch (error) {
      if (request === listRequest) status.textContent = error.message;
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
    confirm.hidden = false;
    get("skill-delete-cancel").focus();
  });
  get("skill-delete-cancel").addEventListener("click", () => {
    confirm.hidden = true;
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
  return { loadLinked, clearLink };
}
