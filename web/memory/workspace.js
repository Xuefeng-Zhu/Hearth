import { render as paint } from "preact";
import { html, Icon } from "../ui.js";
import { areas, Loading, MemoryNote, MemoryTabs, MemoryView, NoteLayout, Profile, RecallResults } from "./view.js";
import { Review } from "./review.js";

const get = (id) => document.getElementById(id);

function sectionFor(path) {
  if (path === "USER.md" || path === "APPROVAL_PREFERENCES.md" || path.startsWith("chat/")) return "profile";
  return ({ people: "people", locations: "places", daily: "daily" })[path.split("/")[0]] || "topics";
}

export function createMemory({ api, approvals, openSource, isBusy, setBusy, showNotice }) {
  paint(html`<${MemoryView} />`, get("memory-view"));
  const tabs = get("memory-tabs");
  const area = get("memory-area");
  const status = get("memory-status");
  const query = get("memory-query");
  const results = get("memory-find-results");
  let data;
  let section = "profile";
  let selected;
  let source;
  let digest;
  let request = 0;
  let findRequest = 0;

  const records = (category) => (data?.index || []).filter((row) => sectionFor(row.path) === category
    && !["USER.md", "APPROVAL_PREFERENCES.md"].includes(row.path));
  const announce = (message) => { status.textContent = message; };

  function choose(category, path) {
    section = category;
    selected = path;
    source = digest = undefined;
    announce("");
    return render();
  }

  tabs.addEventListener("keydown", (event) => {
    const index = areas.findIndex((item) => item.id === section);
    const next = { ArrowLeft: (index + areas.length - 1) % areas.length, ArrowRight: (index + 1) % areas.length,
      Home: 0, End: areas.length - 1 }[event.key];
    if (next == null) return;
    event.preventDefault();
    const item = areas[next];
    choose(item.id);
    get(`memory-tab-${item.id}`)?.focus();
  });

  async function mutate(control, endpoint, body, message, next, focus) {
    if (control.disabled) return;
    control.disabled = true;
    try {
      await api(endpoint, body);
      selected = next;
      source = undefined;
      if (next) section = sectionFor(next);
      await load();
      announce(message);
      area.querySelector(focus || ".memory-note h3")?.focus();
    } catch (error) {
      announce(error.message);
    } finally {
      control.disabled = false;
    }
  }

  function saveProfile(control, body) {
    return mutate(control, "/api/memory/profile", body, "Profile saved.", undefined, ".memory-primary");
  }

  async function open(row) {
    await choose(sectionFor(row.path), row.path);
    area.querySelector(".memory-note h3, .memory-card h3")?.focus();
  }

  async function render() {
    if (!data) return;
    const version = ++request;
    paint(html`<${MemoryTabs} profile=${data.profile} ...${{ section, records, choose }} />`, tabs);
    area.setAttribute("aria-labelledby", `memory-tab-${section}`);
    if (section === "review") {
      paint(html`<${Review} key=${version} api=${api} initialDigest=${digest} />`, area);
      digest = undefined;
      return;
    }
    if (section === "profile" && !source && (!selected || selected === "USER.md")) {
      paint(html`<${Profile} key=${version} ...${{ data, approvals, saveProfile, open }} />`, area);
      return;
    }
    const group = areas.find((item) => item.id === section);
    const rows = records(section);
    if (section === "daily") rows.reverse();
    const row = data.index.find((row) => row.path === selected) || rows[0];
    const hit = source;
    const path = selected = hit?.path || row?.path;
    const layout = (children) => paint(html`<${NoteLayout} ...${{ group, rows, selected: path }}
      choose=${(path) => {
        choose(section, path);
        area.querySelector('[aria-pressed="true"]')?.focus();
      }}>${children}</${NoteLayout}>`, area);
    if (!path) {
      layout(html`<${Icon} name=${group.icon} size=${26} /><h3>${group.label}</h3><p class="meta">${group.empty}</p>`);
      return;
    }
    layout(html`<${Loading}>Loading note…</${Loading}>`);
    try {
      const file = hit?.message_id
        ? await api(`/api/memory/chat?thread=${encodeURIComponent(hit.thread_id)}&message=${encodeURIComponent(hit.message_id)}`)
        : await api(`/api/memory?path=${encodeURIComponent(path)}`);
      if (version !== request) return;
      layout(html`<${MemoryNote} ...${{ path, row, hit, file, approvals, forget, choose, open, mutate }}
        index=${data.index} cancel=${render} />`);
    } catch (error) {
      if (version === request) layout(html`<p class="meta">${error.message}</p>`);
    }
  }

  async function load() {
    data = await api("/api/memory");
    return render();
  }

  function renderRecall(container, result, allowForget = false) {
    paint(html`<${RecallResults} result=${result} open=${openSource} forget=${allowForget ? forget : undefined} />`, container);
  }

  async function find() {
    const text = query.value.trim();
    const current = ++findRequest;
    results.hidden = !text;
    if (!text) return;
    paint(html`<${Loading}>Searching memory…</${Loading}>`, results);
    try {
      const result = await api("/api/memory/search", { query: text });
      if (current === findRequest) renderRecall(results, result, true);
    } catch (error) {
      if (current === findRequest) paint(html`<p class="meta">${error.message}</p>`, results);
    }
  }

  async function forget(hit, excerpt = false) {
    const question = hit.message_id ? "Forget this message from recall?" : excerpt
      ? `Remove this excerpt from ${hit.path}?` : `Delete the note ${hit.path}?`;
    if (isBusy() || !window.confirm(`${question} Hearth will save a checkpoint first.`)) return;
    setBusy(true);
    try {
      const body = { path: hit.path };
      if (hit.message_id) body.message_id = hit.message_id;
      else if (excerpt) body.item_id = hit.id;
      else if (hit.revision) body.revision = hit.revision;
      await api("/api/memory/forget", body);
      selected = source = undefined;
      await load();
      if (query.value.trim()) await find();
      showNotice("Memory forgotten. Undo is available in Timeline.");
    } catch (error) {
      showNotice(error.message);
    } finally {
      setBusy(false);
    }
  }

  get("memory-find").addEventListener("submit", (event) => {
    event.preventDefault();
    find();
  });
  query.addEventListener("input", () => { if (!query.value) find(); });

  return {
    load, renderRecall,
    selectReview(id) {
      section = "review";
      selected = source = undefined;
      digest = id;
    },
    selectSource(hit) {
      section = sectionFor(hit.path);
      selected = hit.path;
      source = hit;
    },
  };
}
