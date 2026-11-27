import { icon } from "./icons.js";
import { showLoading } from "./motion.js";

const labels = { reminders: "Search reminders", inbox: "Search inbox", skills: "Search skills" };
const limit = 200;

export function listSearchRoute(hash) {
  const [path, ...params] = hash.split("?");
  const [, view, target] = /^#(reminders|inbox|skills)(?:\/([^/]+))?$/.exec(path) || [];
  if (!view || (target && view !== "skills")) return;
  let id;
  if (target) {
    try { id = decodeURIComponent(target); } catch { /* A malformed link opens the library. */ }
  }
  const query = normalizeQuery(new URLSearchParams(params.join("?")).get("q") || "");
  return { view, target: id, query, hash: listSearchHash(view, query, id) };
}

export function listSearchHash(view, query = "", id) {
  const path = id ? `#${view}/${encodeURIComponent(id)}` : `#${view}`;
  return query ? `${path}?${new URLSearchParams({ q: query })}` : path;
}

export function listSearchPath(path, query) {
  return query ? `${path}?${new URLSearchParams({ q: query })}` : path;
}

function normalizeQuery(value) {
  return [...value.replaceAll("\0", "").trim()].slice(0, limit).join("").trim();
}

export function createListSearch(view, onChange) {
  const host = document.getElementById(`${view}-search`);
  const empty = document.getElementById(`${view}-search-empty`);
  const label = labels[view];
  const field = document.createElement("div");
  const input = document.createElement("input");
  const clear = document.createElement("button");
  const status = document.createElement("span");
  const reset = document.createElement("button");
  const message = document.createElement("p");
  let query = "";
  let timer;

  host.setAttribute("role", "search");
  host.setAttribute("aria-label", label);
  field.className = "chat-search-field";
  input.type = "search";
  input.className = "search-input";
  input.placeholder = `${label}…`;
  input.maxLength = limit * 2;
  input.setAttribute("aria-label", label);
  input.setAttribute("aria-keyshortcuts", "/");
  input.autocomplete = "off";
  clear.type = reset.type = "button";
  clear.className = "chat-search-icon search-clear";
  clear.setAttribute("aria-label", "Clear search");
  clear.title = "Clear search";
  clear.append(icon("x", 18));
  clear.hidden = true;
  status.className = "list-search-status";
  status.setAttribute("role", "status");
  message.textContent = "No matches found.";
  reset.textContent = "Clear search";
  field.append(icon("search", 18), input, clear);
  host.append(field, status);
  empty.append(message, reset);

  function apply(value) {
    if (query === value) return false;
    query = value;
    if (query) showLoading(status, "Searching…");
    else status.textContent = "";
    empty.hidden = true;
    return true;
  }

  function sync(value) {
    clearTimeout(timer);
    input.value = value;
    clear.hidden = !value;
    return apply(value);
  }

  function clearSearch() {
    input.focus();
    if (sync("")) onChange("");
  }

  function schedule(event) {
    clearTimeout(timer);
    if (event.isComposing) return;
    const characters = [...input.value];
    if (characters.length > limit) input.value = characters.slice(0, limit).join("");
    clear.hidden = !input.value;
    const value = normalizeQuery(input.value);
    timer = setTimeout(() => {
      // Keep spaces and the caret in the typed text so the user can continue a phrase.
      if (apply(value)) onChange(value);
    }, 150);
  }

  input.addEventListener("input", schedule);
  input.addEventListener("compositionend", schedule);
  clear.addEventListener("click", clearSearch);
  reset.addEventListener("click", clearSearch);

  return {
    get query() { return query; },
    cancel: () => clearTimeout(timer),
    sync,
    focus() {
      if (!input.getClientRects().length) return false;
      input.focus();
      return true;
    },
    count(total) {
      const text = `${total} ${total === 1 ? "result" : "results"}`;
      if (status.textContent !== text) status.textContent = text;
      empty.hidden = !query || total !== 0;
    },
    fail() {
      if (status.textContent === "Searching…") status.textContent = "";
    },
  };
}
