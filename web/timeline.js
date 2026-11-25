import { mascot, setPose } from "./avatar.js";
import { reconcileChildren } from "./dom.js";

const get = (id) => document.getElementById(id);
const categories = {
  all: "All", chat: "Chats", memory: "Memory", action: "Actions", connector: "Connectors", error: "Errors",
};
const kinds = {
  chat: ["Chat turn", "M4 4h16v12H9l-5 4zM8 8h8m-8 4h5"],
  recall: ["Memory recalled", "M3 5c3-1 6 0 9 2 3-2 6-3 9-2v14c-3-1-6 0-9 2-3-2-6-3-9-2zM12 7v14"],
  memory: ["Memory", "M5 3h11l3 3v15H5zM9 3v6h6V3M8 21v-7h8v7"],
  reminder: ["Reminder", "M18 8a6 6 0 0 0-12 0c0 6-2 7-2 8h16c0-1-2-2-2-8M10 20h4"],
  gateway: ["Connector", "m8 12 4-4m0 8 4-4M9 15l-2 2a3 3 0 0 1-4-4l4-4a3 3 0 0 1 4 0m2 6a3 3 0 0 0 4 0l4-4a3 3 0 0 0-4-4l-2 2"],
  search: ["Web search", "M16 10a6 6 0 1 1-12 0 6 6 0 0 1 12 0zm-2 4 6 6"],
  browse: ["Web browsing", "M3 5h18v14H3zM3 9h18m-15-2h1m2 0h1"],
  routing: ["Model routing", "M5 6h4m-2-2 2 2-2 2m8-2h4m-2-2 2 2-2 2M5 18h4l6-12m-2 12h6m-2-2 2 2-2 2"],
  brain: ["Model fallback", "M5 6h4m-2-2 2 2-2 2m8-2h4m-2-2 2 2-2 2M5 18h4l6-12m-2 12h6m-2-2 2 2-2 2"],
  voice: ["Voice", "M9 6a3 3 0 0 1 6 0v5a3 3 0 0 1-6 0zm-4 5a7 7 0 1 0 14 0M12 18v3m-3 0h6"],
  artifact: ["Artifact", "M5 3h9l5 5v13H5zM14 3v5h5M8 12h8m-8 4h8"],
  undo: ["Undo", "M9 5 4 10l5 5M4 10h10a5 5 0 0 1 0 10h-3"],
  inbox: ["Inbox", "M3 5h18v14H3zm0 1 9 7 9-7"],
  email: ["Email", "M3 5h18v14H3zm0 1 9 7 9-7"],
  checkpoint: ["Checkpoint", "M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18zm0 4v5l3 2"],
  thread: ["Side chat", "M4 4h16v12H9l-5 4zM8 8h8m-8 4h5"],
  tool: ["Tool", "M14 4a5 5 0 0 0-6 6L3 15a3 3 0 0 0 4 4l5-5a5 5 0 0 0 6-6l-3 3-3-3z"],
};
kinds.remember = kinds.memory;

const statusNames = {
  pending: "Awaiting approval", partial: "Partially applied", unknown: "Delivery unconfirmed",
  sending: "Delivery unconfirmed", changing: "Interrupted", request_unknown: "Request unconfirmed",
};
const undoKey = "hearth-timeline-undo";
const filterKey = "hearth-timeline-filter";
const relativeFormat = new Intl.RelativeTimeFormat(undefined, { numeric: "always", style: "short" });
const exactFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "full", timeStyle: "long" });
const dayFormat = new Intl.DateTimeFormat(undefined, { month: "long", day: "numeric", year: "numeric" });
const shortFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const stamp = (value) => Date.parse(value) || 0;

function element(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}

function control(label, handler, className) {
  const button = element("button", className, label);
  button.type = "button";
  button.addEventListener("click", handler);
  return button;
}

function icon(kind) {
  const namespace = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(namespace, "svg");
  const line = document.createElementNS(namespace, "path");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  line.setAttribute("d", (kinds[kind] || kinds.tool)[1]);
  svg.append(line);
  return svg;
}

function dayKey(value) {
  if (!value) return "";
  const day = new Date(value);
  return [day.getFullYear(), day.getMonth(), day.getDate()].join("-");
}

function dayLabel(value, now) {
  const key = dayKey(value);
  if (!key) return "Date unavailable";
  if (key === dayKey(now)) return "Today";
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  return key === dayKey(yesterday) ? "Yesterday" : dayFormat.format(value);
}

function relativeTime(value, now) {
  const seconds = Math.round((value - now) / 1000);
  if (Math.abs(seconds) < 60) return "Just now";
  for (const [unit, size] of [["day", 86400], ["hour", 3600], ["minute", 60]]) {
    if (Math.abs(seconds) >= size) return relativeFormat.format(Math.trunc(seconds / size), unit);
  }
}

function timeLabel(value) {
  const time = element("time");
  if (!stamp(value)) {
    time.hidden = true;
    return time;
  }
  time.dateTime = value;
  time.title = exactFormat.format(stamp(value));
  return time;
}

function flags(row) {
  return {
    all: true,
    chat: row.kind === "chat",
    memory: ["memory", "remember", "recall"].includes(row.kind),
    action: ["artifact", "browse", "checkpoint", "email", "gateway", "inbox", "memory", "remember", "reminder", "search", "thread", "tool", "undo", "voice"]
      .includes(row.kind),
    connector: !!row.connector,
    error: !!row.error,
  };
}

function searchText(row) {
  return [row.title, kinds[row.kind]?.[0], row.undone && "undone", row.thread_title, row.model, row.connector,
    ...Object.values(row.data || {}).flatMap((value) => typeof value === "string" ? [value] : []),
    row.data?.paths?.join(" "), row.data?.job?.message, row.data?.email?.subject, row.data?.request?.path,
    ...(row.data?.results || []).map((item) => [item.title, item.path, item.snippet, item.excerpt].join(" ")),
  ].filter(Boolean).join(" ").toLocaleLowerCase();
}

function routedModel(model) {
  return [model.name, model.model && model.provider !== "mock" ? model.model : ""].filter(Boolean).join(" · ");
}

function detailFields(row, gatewayResponse) {
  const data = row.data || {};
  const formatted = (value) => stamp(value) ? shortFormat.format(stamp(value)) : "";
  const join = (values) => values?.join("\n");
  const responseStatus = gatewayResponse?.status || data.http_status;
  const lines = [
    ["Request", data.prompt || data.query],
    ["Page URL", data.url],
    ["Session ID", data.session_id],
    ["Browse time", Number.isInteger(data.duration_ms) ? `${(data.duration_ms / 1000).toFixed(2)} s` : ""],
    ["Mode", row.kind === "browse" && data.mock && "Mock"],
    ["Reply", data.reply],
    ["Routing", data.reason || data.routing?.reason],
    ["Model order", join(data.order?.map(routedModel))],
    ["Notes", data.detail || join(data.notices)],
    ["Memory files", join(data.paths) || data.path],
    ["Excerpt", data.excerpt],
    ["Memory backend", data.backend && (row.connector || "Keyword")],
    ["Fact", data.fact],
    ["Reminder", data.job?.message || data.message],
    ["Due", formatted(data.job?.next_at || data.scheduled_at)],
    ["Next due", formatted(data.next_due)],
    ["Channel", { app: "In app", email: "Email", both: "Both" }[data.job?.channel]],
    ["Delivery", data.delivery_summary || join(Object.entries(data.delivery || {}).map(([channel, delivery]) =>
      `${channel === "app" ? "In app" : "Email"} · ${delivery.status}${delivery.reason ? ` · ${delivery.reason}` : ""}`))],
    ["Late", data.late_minutes ? `Late by ${data.late_minutes}m` : ""],
    ["Summary", data.summary],
    ["Proposed action", data.proposal],
    ["Event time", formatted(data.event_at)],
    ["Schedule", data.job?.cron && `${data.job.cron} UTC`],
    ["Recipients", data.email?.to.join(", ")],
    ["Subject", data.email?.subject],
    ["Message", data.email?.text],
    ["Connector request", data.request && `${data.request.method} ${data.request.path}`],
    ["Response", responseStatus && `HTTP ${responseStatus}`],
    ["Response preview", typeof gatewayResponse?.data === "string" && gatewayResponse.data.slice(0, 1200)],
    ["Checkpoint", data.checkpoint?.id],
    ["Original activity", formatted(data.original_at)],
    ["Duration", Number.isInteger(data.duration) ? `${Math.floor(data.duration / 60)}m ${data.duration % 60}s` : ""],
    ["Engine", data.engine],
    ["Transcript", join(data.lines?.map((line) => `${line.role === "user" ? "You" : "Agent"} — ${line.text}`))],
    ["Warnings", join(data.warnings)],
    ["Latency", Number.isInteger(data.latency_ms) ? `${data.latency_ms.toLocaleString()} ms` : ""],
  ];
  return lines.filter(([, value]) => value);
}

function expandedBody(row, gatewayResponse) {
  const body = element("div", "timeline-detail");
  const fields = element("dl", "timeline-detail-fields");
  for (const [label, content] of detailFields(row, gatewayResponse)) {
    const group = element("div");
    group.append(element("dt", "", label), element("dd", "", content));
    fields.append(group);
  }
  if (fields.children.length) body.append(fields);
  const results = row.data?.results;
  if (results?.length) {
    const list = element("ul", "timeline-results");
    for (const result of results) {
      const item = element("li");
      const label = result.title || [result.path, result.line && `line ${result.line}`].filter(Boolean).join(" · ");
      item.append(element("strong", "", label));
      const description = result.excerpt || result.snippet;
      if (description) item.append(element("p", "", description));
      list.append(item);
    }
    body.append(list);
  }
  const raw = element("details", "timeline-raw");
  const summary = element("summary", "", "Raw");
  summary.dataset.focus = "raw";
  raw.append(summary);
  raw.addEventListener("toggle", () => {
    if (raw.open && raw.children.length === 1) {
      raw.append(element("pre", "", JSON.stringify(gatewayResponse === undefined ? row.data
        : { ...row.data, response: gatewayResponse }, null, 2)));
    }
  });
  body.append(raw);
  return body;
}

function readReceipts() {
  try {
    const value = JSON.parse(localStorage.getItem(undoKey));
    return Array.isArray(value) ? value.filter((row) => row?.undone) : [];
  } catch {
    return [];
  }
}

export function createTimeline({ api, approve, undo, gatewayResults, isBusy }) {
  const feed = get("timeline");
  const filterBar = get("timeline-filters");
  const query = get("timeline-search");
  const threads = get("timeline-thread");
  const feedback = get("timeline-feedback");
  const announcer = get("timeline-announcer");
  const chips = {};
  const cards = new Map();
  const groups = new Map();
  const openCards = new Set();
  let receipts = readReceipts();
  let entries = [];
  let ready = false;
  let filter = localStorage.getItem(filterKey);
  if (!Object.hasOwn(categories, filter)) filter = "all";
  let stream;
  let revision = 0;
  let request;
  let pending;
  let queued = false;
  let timer;
  let clock;
  let today;
  let confirmation;
  let known = new Map();
  let highlight = new Set();
  let firstSnapshot = true;
  const sleeping = mascot("ember");
  sleeping.setAttribute("aria-hidden", "true");
  setPose(sleeping, { pose: "sleeping" });

  const selectFilter = (value) => {
    filter = value;
    localStorage.setItem(filterKey, value);
    render();
  };
  for (const [id, label] of Object.entries(categories)) {
    const chip = control(label, () => selectFilter(id));
    const count = element("span", "", "0");
    chip.append(count);
    chips[id] = { chip, count, label };
    filterBar.append(chip);
  }
  query.addEventListener("input", render);
  threads.addEventListener("change", render);

  function setConfirmation(card, row, action) {
    const target = card.querySelector(".timeline-confirm");
    target.hidden = confirmation !== row.id;
    const button = card.querySelector(".timeline-undo");
    button.setAttribute("aria-expanded", String(!target.hidden));
    if (!target.hidden && !target.firstElementChild) {
      const itemChange = ["artifact", "inbox", "reminder"].includes(row.kind) || action.memory_change;
      const message = row.redoable ? "Apply this memory change again?"
        : row.kind === "artifact" ? "Undo this artifact change?"
          : row.kind === "inbox" ? "Undo the changes from this email?"
          : row.kind === "reminder" ? "Cancel this reminder?"
          : action.memory_change ? "Undo this memory change?"
            : "Restore this checkpoint? Newer chats, notes, and reminders will roll back. Delivered email stays delivered.";
      target.append(element("p", "", message));
      const cancel = control("Cancel", () => {
        confirmation = undefined;
        setConfirmation(card, row, action);
        button.focus();
      });
      const label = row.redoable ? "Redo change" : itemChange ? "Undo change" : "Restore checkpoint";
      const restore = control(label, () => {
        confirmation = undefined;
        setConfirmation(card, row, action);
        return undo(action, { confirmed: true, timelineTitle: row.title, redo: !!row.redoable });
      }, "timeline-restore");
      restore.dataset.focus = "restore";
      target.append(cancel, restore);
    }
  }

  function buildCard(row) {
    const saved = cards.get(row.id);
    const response = gatewayResults.get(row.action_id);
    const signature = JSON.stringify(row);
    if (saved?.signature === signature && saved.response === response) return saved.card;
    const focused = saved?.card.contains(document.activeElement) && document.activeElement.dataset.focus;
    const rawOpen = saved?.card.querySelector(".timeline-raw")?.open;
    const kind = row.undone ? "undo" : row.kind;
    const card = element("li", `timeline-entry${row.undone ? " is-undone" : ""}${row.error ? " is-error" : ""}`);
    card.dataset.kind = kind;
    card.dataset.entry = row.id;
    if (highlight.has(row.id)) {
      card.classList.add("is-new");
      card.addEventListener("animationend", () => card.classList.remove("is-new"), { once: true });
    }
    if (row.kind === "reminder") {
      card.dataset.reminderId = row.data.job?.id || row.data.id;
      card.dataset.reminderMessage = row.data.job?.message || row.data.message;
    }
    const details = element("details", "timeline-card");
    const summary = element("summary", "timeline-card-head");
    summary.dataset.focus = "summary";
    const mark = element("span", "timeline-kind");
    const kindLabel = (kinds[kind] || kinds.tool)[0];
    mark.title = kindLabel;
    mark.append(icon(kind), element("span", "visually-hidden", kindLabel));
    const copy = element("span", "timeline-card-copy");
    const title = element("span", "timeline-title", row.title);
    title.title = row.title;
    const metadata = element("span", "timeline-meta");
    for (const [value, type] of [
      [row.thread_title, "thread"], [row.model?.split("/").at(-1), "model"], [row.connector, "connector"],
      [row.source === "voice-call" && row.kind !== "voice" && "Voice call", "source"],
      [row.undone ? "Undone" : statusNames[row.data?.status] || (row.error && "Error"), "status"],
    ]) {
      if (!value) continue;
      const chip = element("span", `timeline-tag timeline-tag-${type}`, value);
      chip.title = type === "model" ? row.model : value;
      metadata.append(chip);
    }
    copy.append(title, metadata);
    const time = timeLabel(row.at);
    time.className = "timeline-time";
    const chevron = element("span", "timeline-chevron");
    chevron.setAttribute("aria-hidden", "true");
    summary.append(mark, copy, time, chevron);
    details.append(summary);
    const expand = () => {
      if (details.childElementCount > 1) return;
      const body = expandedBody(row, response);
      details.append(body);
      if (rawOpen) body.querySelector(".timeline-raw").open = true;
    };
    details.open = openCards.has(row.id);
    if (details.open) expand();
    details.addEventListener("toggle", () => {
      if (details.open) {
        openCards.add(row.id);
        expand();
      } else {
        openCards.delete(row.id);
      }
    });

    const action = row.kind === "artifact" ? { ...row.data, id: row.action_id } : row.data;
    if ((row.undoable && !row.undone) || row.redoable) {
      card.classList.add("has-undo");
      const confirm = element("div", "timeline-confirm");
      confirm.id = "confirm-" + row.action_id;
      confirm.hidden = true;
      details.id = "activity-" + row.action_id;
      const button = control(row.redoable ? "Redo" : "Undo", () => {
        const old = confirmation;
        confirmation = confirmation === row.id ? undefined : row.id;
        if (old && old !== row.id) {
          const previous = cards.get(old)?.card;
          if (previous) {
            previous.querySelector(".timeline-confirm").hidden = true;
            previous.querySelector(".timeline-undo").setAttribute("aria-expanded", "false");
          }
        }
        setConfirmation(card, row, action);
        if (!confirm.hidden) confirm.querySelector("button").focus();
      }, "timeline-undo");
      button.prepend(icon("undo"));
      button.dataset.focus = "undo";
      button.setAttribute("aria-controls", confirm.id);
      card.append(details, button, confirm);
      setConfirmation(card, row, action);
    } else {
      card.append(details);
    }
    if (row.action_id && action.status === "pending" && !row.undone) {
      const button = control("Approve", () => approve(action), "timeline-approve");
      button.dataset.focus = "approve";
      card.append(button);
    }
    if (focused) queueMicrotask(() => {
      const target = card.querySelector(`[data-focus="${focused}"]`) || summary;
      (target.disabled ? summary : target).focus({ preventScroll: true });
    });
    cards.set(row.id, { signature, card, response });
    return card;
  }

  function emptyState(hasEntries) {
    const block = element("div", "timeline-empty");
    block.append(sleeping, element("h3", "", hasEntries ? "No matching activity" : "Hearth is quiet"),
      element("p", "", hasEntries ? "Try a different search or clear your filters." : "Start a chat to see Hearth’s activity here."));
    if (hasEntries) block.append(control("Clear filters", () => {
      threads.value = "";
      query.value = "";
      selectFilter("all");
      chips.all.chip.focus();
    }));
    return block;
  }

  function updateTimes(now = Date.now()) {
    for (const time of get("timeline-view").querySelectorAll("time")) {
      time.textContent = relativeTime(stamp(time.dateTime), now);
    }
  }

  function render() {
    if (!ready) return;
    const now = Date.now();
    today = dayKey(now);
    const restored = new Set(receipts.map((row) => row.data.checkpoint.id));
    const rows = [...entries.filter((row) => !(row.kind === "checkpoint" && !row.action_id
      && restored.has(row.data.checkpoint.id))), ...receipts]
      .sort((a, b) => stamp(b.at) - stamp(a.at) || Number(!!b.undone) - Number(!!a.undone)
        || Number(b.kind === "chat") - Number(a.kind === "chat"));

    const threadId = threads.value;
    const threadNames = new Map();
    for (const row of rows) if (row.thread_id && !threadNames.has(row.thread_id)) {
      threadNames.set(row.thread_id, row.thread_title);
    }
    const signature = JSON.stringify([...threadNames].sort(([a], [b]) => a.localeCompare(b)));
    if (threads.dataset.signature !== signature) {
      threads.dataset.signature = signature;
      threads.replaceChildren(new Option("All threads", ""), ...[...threadNames].sort(([, a], [, b]) =>
        a.localeCompare(b)).map(([id, title]) => new Option(title, id)));
      if (threadNames.has(threadId)) threads.value = threadId;
    }

    const text = query.value.trim().toLocaleLowerCase();
    const counts = Object.fromEntries(Object.keys(categories).map((key) => [key, 0]));
    const totals = { chat: 0, memory: 0, action: 0, connector: 0 };
    const days = new Map();
    for (const row of rows) {
      const matches = flags(row);
      const value = stamp(row.at);
      const key = dayKey(value);
      if (key === today && !row.undone) {
        if (matches.chat) totals.chat++;
        if (matches.memory && row.data?.status !== "pending") totals.memory++;
        if (matches.action && !matches.memory && row.data?.status !== "pending") totals.action++;
        if (matches.connector && row.kind !== "routing" && row.data?.status !== "pending") totals.connector++;
      }
      if ((threads.value && row.thread_id !== threads.value) || (text && !searchText(row).includes(text))) continue;
      for (const category of Object.keys(categories)) if (matches[category]) counts[category]++;
      if (!matches[filter]) continue;
      if (!days.has(key)) days.set(key, { value, items: [] });
      days.get(key).items.push(buildCard(row));
    }
    for (const [id, { chip, count, label }] of Object.entries(chips)) {
      count.textContent = counts[id];
      chip.setAttribute("aria-pressed", String(id === filter));
      chip.setAttribute("aria-label", `${label}, ${counts[id]}`);
    }
    for (const [id, value] of Object.entries({
      turns: totals.chat, memory: totals.memory, actions: totals.action, connectors: totals.connector,
    })) get(`timeline-${id}`).textContent = value.toLocaleString();
    const last = get("timeline-last-undo");
    const previousUndo = rows.filter((row) => row.undone)
      .sort((a, b) => stamp(b.undone_at || b.at) - stamp(a.undone_at || a.at))[0];
    if (previousUndo) {
      const timestamp = previousUndo.undone_at || previousUndo.at;
      if (last.firstElementChild?.dateTime !== timestamp) {
        last.replaceChildren(timeLabel(timestamp));
        last.title = previousUndo.title;
      }
    } else {
      last.textContent = "—";
      last.removeAttribute("title");
    }
    const sections = [];
    for (const [key, { value, items }] of days) {
      if (!groups.has(key)) {
        const section = element("section", "timeline-day");
        const label = element("h3", "timeline-day-label");
        label.id = `timeline-day-${key || "unknown"}`;
        const list = element("ol", "timeline-rail");
        list.setAttribute("role", "list");
        list.setAttribute("aria-labelledby", label.id);
        section.append(label, list);
        groups.set(key, { section, label, list });
      }
      const group = groups.get(key);
      const label = dayLabel(value, now);
      if (group.label.textContent !== label) group.label.textContent = label;
      reconcileChildren(group.list, items);
      sections.push(group.section);
    }
    reconcileChildren(feed, sections.length ? sections : [emptyState(rows.length > 0)]);
    for (const id of cards.keys()) if (!known.has(id) && !receipts.some((row) => row.id === id)) {
      cards.delete(id);
      openCards.delete(id);
    }
    for (const key of groups.keys()) if (!days.has(key)) groups.delete(key);
    setBusy();
    updateTimes(now);
  }

  function setBusy() {
    for (const button of feed.querySelectorAll(".timeline-undo, .timeline-approve, .timeline-confirm button")) {
      button.disabled = isBusy();
    }
  }

  function refresh() {
    if (pending) {
      queued = true;
      return pending;
    }
    pending = load().finally(() => {
      pending = undefined;
      if (queued && stream) {
        queued = false;
        refresh();
      }
    });
    return pending;
  }

  async function load() {
    const current = ++revision;
    const controller = new AbortController();
    request = controller;
    try {
      const data = await api("/api/timeline", undefined, AbortSignal.any([controller.signal, AbortSignal.timeout(9000)]));
      if (current !== revision) return;
      const next = new Map(data.entries.map((row) => [row.id,
        [row.at, row.data?.status, !!row.data?.reply].join("|")]));
      highlight = firstSnapshot ? new Set() : new Set([...next].filter(([id, state]) =>
        known.get(id) !== state).map(([id]) => id));
      known = next;
      entries = data.entries;
      ready = true;
      firstSnapshot = false;
      feedback.textContent = data.checkpoint_notice || "";
      feedback.hidden = !feedback.textContent;
      if (highlight.size) announcer.textContent = `${highlight.size} activity ${highlight.size === 1 ? "entry updated" : "entries updated"}.`;
      render();
    } catch (error) {
      if (current !== revision) return;
      feedback.hidden = false;
      feedback.textContent = error.message;
    } finally {
      if (request === controller) request = undefined;
    }
  }

  async function show() {
    if (stream) return refresh();
    firstSnapshot = true;
    stream = new EventSource("/api/timeline/events");
    stream.addEventListener("activity", () => {
      clearTimeout(timer);
      timer = setTimeout(refresh, 250);
    });
    clock = setInterval(() => {
      if (dayKey(Date.now()) !== today) render();
      else updateTimes();
    }, 30_000);
    await refresh();
  }

  function hide() {
    stream?.close();
    stream = undefined;
    clearInterval(clock);
    clearTimeout(timer);
    queued = false;
    ++revision;
    request?.abort();
  }

  function restored(action, title) {
    const original = entries.find((row) => row.action_id === action.id && row.undoable);
    const row = {
      id: `undo:${action.id}:${action.checkpoint.id}`, kind: "undo",
      title: title || original?.title || action.title, at: new Date().toISOString(), undone: true,
      thread_id: original?.thread_id || action.thread_id || "main",
      thread_title: original?.thread_title || action.thread_title || "Main",
      data: { checkpoint: { id: action.checkpoint.id }, original_at: action.updated_at || action.at },
    };
    receipts = [row, ...receipts.filter((item) => item.id !== row.id)].slice(0, 50);
    try {
      localStorage.setItem(undoKey, JSON.stringify(receipts));
    } catch {
      // The receipt remains available for the current page.
    }
    confirmation = undefined;
    entries = entries.filter((entry) => entry.action_id !== action.id);
    highlight = new Set([row.id]);
    if (stream) {
      render();
      const target = cards.get(row.id)?.card.querySelector("summary");
      if (target?.isConnected) target.focus({ preventScroll: true });
      else chips[filter].chip.focus({ preventScroll: true });
    }
  }

  function focusReminder(payload) {
    const find = () => [...feed.querySelectorAll("[data-reminder-id]")].find((item) =>
      item.dataset.reminderId === payload?.id || item.dataset.reminderMessage === payload?.message);
    let card = find();
    if (!card && entries.some((row) => row.kind === "reminder"
      && (row.data.job?.id === payload?.id || (row.data.job?.message || row.data.message) === payload?.message))) {
      threads.value = "";
      query.value = "";
      selectFilter("action");
      card = find();
    }
    if (card) card.querySelector("summary").focus();
    return !!card;
  }

  return { show, hide, refresh, setBusy, restored, focusReminder };
}
