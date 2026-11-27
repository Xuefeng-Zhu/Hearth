import { render as paint } from "preact";
import { html } from "../chat/view.js";
import { setTimeZone } from "../time.js";
import { selectPlacement } from "../combobox.js";
import { categories, kinds, stamp, dayKey, Filters, TimelineFeed, Time, ThreadOptions } from "./view.js";

const get = (id) => document.getElementById(id);
const undoKey = "hearth-timeline-undo";
const filterKey = "hearth-timeline-filter";

function flags(row) {
  return {
    all: true,
    chat: row.kind === "chat",
    memory: ["memory", "remember", "recall"].includes(row.kind),
    action: ["approval", "task", "automation", "proactivity", "goal", "artifact", "browse", "checkpoint", "email", "feed", "gateway", "inbox", "memory", "panel", "remember", "reminder", "search", "thread", "tool", "undo", "upload", "voice", "page", "page_share", "skill", "worker", "self_update"]
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

function readReceipts() {
  try {
    const value = JSON.parse(localStorage.getItem(undoKey));
    return Array.isArray(value) ? value.filter((row) => row?.undone) : [];
  } catch {
    return [];
  }
}

export function createTimeline({ refreshAPI, approve, undo, gatewayResults, isBusy, onFilter }) {
  const feed = get("timeline");
  const filterBar = get("timeline-filters");
  const query = get("timeline-search");
  const threads = get("timeline-thread");
  const categorySelect = get("timeline-category");
  const mobileFilter = matchMedia("(max-width: 760px)");
  const filterOpen = get("timeline-filter-open");
  const filterSheet = get("timeline-filter-sheet");
  const errorCount = get("timeline-error-count");
  const activeChip = get("timeline-active-filter");
  const clearFilters = get("timeline-filter-clear");
  const compactSummary = get("timeline-compact-summary");
  const threadLabel = get("timeline-thread-label");
  const categoryLabel = get("timeline-category-label");
  const desktopControls = filterBar.parentElement;
  let draftFilter;
  let threadFilter = "";
  let categoryFilter = "";
  const feedback = get("timeline-feedback");
  const announcer = get("timeline-announcer");
  const cardStates = new Map();
  let counts = Object.fromEntries(Object.keys(categories).map((id) => [id, 0]));
  let days = new Map();
  let hasEntries = false;
  let receipts = readReceipts();
  let entries = [];
  let ready = false;
  let filter = localStorage.getItem(filterKey);
  if (!Object.hasOwn(categories, filter)) filter = "all";
  let todayErrors = false;
  let stream;
  let revision = 0;
  let request;
  let pending;
  let queued = false;
  let timer;
  let clock;
  let confirmation;
  let known = new Map();
  let highlight = new Set();
  let firstSnapshot = true;

  const selectFilter = (value) => {
    if (todayErrors) onFilter();
    todayErrors = false;
    filter = value;
    localStorage.setItem(filterKey, value);
    render();
  };
  function chooseFilter(id) {
    if (filterSheet.open) {
      draftFilter = id;
      showSelection(id);
    } else selectFilter(id);
  }
  const chip = (id) => filterBar.querySelector(`[data-filter="${id}"]`);
  query.addEventListener("input", render);
  threads.addEventListener("change", () => {
    if (!filterSheet.open) {
      threadFilter = threads.value;
      render();
    }
  });
  categorySelect.addEventListener("change", () => {
    if (!filterSheet.open) {
      categoryFilter = categorySelect.value;
      render();
    }
  });

  function showSelection(active) {
    paint(html`<${Filters} counts=${counts} active=${active} choose=${chooseFilter} />`, filterBar);
  }

  function placeFilters() {
    const fields = [threadLabel, selectPlacement(threads), categoryLabel, selectPlacement(categorySelect)];
    if (mobileFilter.matches) {
      get("timeline-filter-options").append(filterBar);
      get("timeline-filter-thread").append(...fields);
    } else {
      if (filterSheet.open) filterSheet.close();
      desktopControls.prepend(filterBar);
      filterOpen.before(...fields);
    }
    threadLabel.classList.toggle("visually-hidden", !mobileFilter.matches);
    categoryLabel.classList.toggle("visually-hidden", !mobileFilter.matches);
    threads.value = threadFilter;
    categorySelect.value = categoryFilter;
  }

  filterOpen.addEventListener("click", () => {
    draftFilter = todayErrors ? "error" : filter;
    threads.value = threadFilter;
    categorySelect.value = categoryFilter;
    showSelection(draftFilter);
    filterSheet.showModal();
    chip(draftFilter).focus();
  });
  get("timeline-filter-close").addEventListener("click", () => filterSheet.close());
  get("timeline-filter-reset").addEventListener("click", () => {
    draftFilter = "all";
    threads.value = "";
    categorySelect.value = "";
    showSelection(draftFilter);
  });
  get("timeline-filter-apply").addEventListener("click", () => {
    threadFilter = threads.value;
    categoryFilter = categorySelect.value;
    filterSheet.close();
    selectFilter(draftFilter);
  });
  filterSheet.addEventListener("click", (event) => {
    const bounds = filterSheet.getBoundingClientRect();
    if (event.target === filterSheet && (event.clientY < bounds.top || event.clientX < bounds.left
      || event.clientX > bounds.right || event.clientY > bounds.bottom)) filterSheet.close();
  });
  filterSheet.addEventListener("close", () => {
    threads.value = threadFilter;
    categorySelect.value = categoryFilter;
    showSelection(todayErrors ? "error" : filter);
    if (mobileFilter.matches && !get("timeline-view").hidden) filterOpen.focus({ preventScroll: true });
  });
  clearFilters.addEventListener("click", () => {
    threadFilter = "";
    threads.value = "";
    categoryFilter = categorySelect.value = "";
    selectFilter("all");
    filterOpen.focus({ preventScroll: true });
  });
  mobileFilter.addEventListener("change", placeFilters);
  showSelection(filter);
  placeFilters();

  function clearSearch() {
    threads.value = "";
    query.value = "";
    selectFilter("all");
    chip("all").focus();
  }

  function confirm(id, focus) {
    confirmation = id;
    renderFeed();
    focus?.();
  }

  function renderFeed(now = Date.now(), restoreFocus = false) {
    const active = document.activeElement;
    const focusedCard = restoreFocus && active.closest("[data-entry]");
    paint(html`<${TimelineFeed} ...${{
      days, now, hasEntries, clearSearch, busy: isBusy(), approve, undo,
      confirmation, confirm, cardStates, gatewayResults, highlight,
    }} />`, feed);
    if (focusedCard && active !== document.activeElement) {
      const card = feed.querySelector(`[data-entry="${CSS.escape(focusedCard.dataset.entry)}"]`);
      const control = card?.querySelector(`[data-focus="${active.dataset.focus}"]`);
      (control && !control.disabled ? control : card?.querySelector("summary"))?.focus({ preventScroll: true });
    }
  }

  function render() {
    if (!ready) return;
    const now = Date.now();
    const today = dayKey(now);
    const activeFilter = todayErrors ? "error" : filter;
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
      paint(html`<${ThreadOptions} names=${threadNames} />`, threads);
      threads.value = threadNames.has(threadId) ? threadId : "";
      if (!threadNames.has(threadFilter)) threadFilter = "";
    }

    const text = query.value.trim().toLocaleLowerCase();
    counts = Object.fromEntries(Object.keys(categories).map((key) => [key, 0]));
    const totals = { chat: 0, memory: 0, action: 0, connector: 0 };
    days = new Map();
    let allErrors = 0;
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
      if (matches.error) allErrors++;
      if ((threadFilter && row.thread_id !== threadFilter) || (text && !searchText(row).includes(text))) continue;
      if (categoryFilter && (row.kind === "remember" ? "memory" : row.kind) !== categoryFilter) continue;
      if (todayErrors && key !== today) continue;
      for (const category of Object.keys(categories)) if (matches[category]) counts[category]++;
      if (!matches[activeFilter]) continue;
      if (!days.has(key)) days.set(key, { value, items: [] });
      days.get(key).items.push(row);
      if (!cardStates.has(row.id)) cardStates.set(row.id, {});
    }
    showSelection(filterSheet.open ? draftFilter : activeFilter);
    errorCount.hidden = allErrors === 0;
    errorCount.textContent = `${allErrors.toLocaleString()} ${allErrors === 1 ? "error" : "errors"}`;
    const filterName = [activeFilter !== "all" ? (todayErrors ? "Today’s errors" : categories[activeFilter]) : "",
      threadNames.get(threadFilter), kinds[categoryFilter]?.[0]].filter(Boolean).join(" · ");
    activeChip.hidden = !filterName;
    get("timeline-filter-name").textContent = filterName;
    clearFilters.setAttribute("aria-label", `Remove filter ${filterName}`);
    for (const [id, value] of Object.entries({
      turns: totals.chat, memory: totals.memory, actions: totals.action, connectors: totals.connector,
    })) get(`timeline-${id}`).textContent = value.toLocaleString();
    const previousUndo = rows.filter((row) => row.undone)
      .sort((a, b) => stamp(b.undone_at || b.at) - stamp(a.undone_at || a.at))[0];
    const undoAt = previousUndo?.undone_at || previousUndo?.at;
    const last = get("timeline-last-undo");
    if (previousUndo) last.title = previousUndo.title;
    else last.removeAttribute("title");
    paint(undoAt ? html`<${Time} at=${undoAt} now=${now} />` : "—", last);
    const compactDetails = [
      `${totals.chat.toLocaleString()} ${totals.chat === 1 ? "turn" : "turns"}`,
      `${totals.action.toLocaleString()} ${totals.action === 1 ? "action" : "actions"}`,
    ].join(" · ");
    paint(html`${compactDetails}${undoAt ? html`${" · last undo "}<${Time} at=${undoAt} now=${now} />`
      : " · no undo yet"}`, compactSummary);
    hasEntries = rows.length > 0;
    renderFeed(now, true);
    for (const id of cardStates.keys()) if (!known.has(id) && !receipts.some((row) => row.id === id)) cardStates.delete(id);
  }

  function setBusy() {
    if (ready) renderFeed();
  }

  function refresh(options) {
    if (pending) {
      queued = options || {};
      return pending;
    }
    pending = load(options).finally(() => {
      pending = undefined;
      if (queued && stream) {
        const next = queued;
        queued = false;
        refresh(next);
      }
    });
    return pending;
  }

  async function load({ background } = {}) {
    const current = ++revision;
    const controller = new AbortController();
    request = controller;
    try {
      const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(9000)]);
      const data = await refreshAPI("/api/timeline", { background, signal });
      if (current !== revision) return;
      if (data.timezone) setTimeZone(data.timezone);
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
      if (background || current !== revision) return;
      feedback.hidden = false;
      feedback.textContent = error.message;
    } finally {
      if (request === controller) request = undefined;
    }
  }

  async function show(options) {
    if (stream) return refresh(options);
    firstSnapshot = true;
    stream = new EventSource("/api/timeline/events");
    stream.addEventListener("activity", () => {
      clearTimeout(timer);
      timer = setTimeout(() => refresh({ background: true }), 250);
    });
    clock = setInterval(render, 30_000);
    await refresh(options);
  }

  function hide() {
    if (filterSheet.open) filterSheet.close();
    stream?.close();
    stream = undefined;
    clearInterval(clock);
    clearTimeout(timer);
    queued = false;
    ++revision;
    request?.abort();
  }

  function setTodayErrors(enabled) {
    todayErrors = enabled;
    if (enabled) {
      threadFilter = "";
      threads.value = "";
      categoryFilter = categorySelect.value = "";
      query.value = "";
    }
    render();
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
      const target = feed.querySelector(`[data-entry="${CSS.escape(row.id)}"] summary`);
      if (target?.isConnected) target.focus({ preventScroll: true });
      else (mobileFilter.matches ? filterOpen : chip(filter)).focus({ preventScroll: true });
    }
  }

  function focusReminder(payload) {
    const find = () => [...feed.querySelectorAll("[data-reminder-id]")].find((item) =>
      item.dataset.reminderId === payload?.id || item.dataset.reminderMessage === payload?.message);
    let card = find();
    if (!card && entries.some((row) => row.kind === "reminder"
      && (row.data.job?.id === payload?.id || (row.data.job?.message || row.data.message) === payload?.message))) {
      threadFilter = "";
      threads.value = "";
      query.value = "";
      selectFilter("action");
      card = find();
    }
    if (card) card.querySelector("summary").focus();
    return !!card;
  }

  return { show, hide, refresh, setBusy, restored, focusReminder, setTodayErrors };
}
