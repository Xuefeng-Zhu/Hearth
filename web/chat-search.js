import { threadMenuIndex } from "./thread-menu.js";

const relativeDates = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

export function relativeChatTime(at, now = Date.now()) {
  if (!at) return "";
  const seconds = (Date.parse(at) - now) / 1000;
  if (!Number.isFinite(seconds)) return "";
  const units = [[31536000, "year"], [2592000, "month"], [604800, "week"], [86400, "day"],
    [3600, "hour"], [60, "minute"]];
  const [size, unit] = units.find(([size]) => Math.abs(seconds) >= size) || [1, "second"];
  return unit === "second" && Math.abs(seconds) < 10 ? "Just now" : relativeDates.format(Math.trunc(seconds / size), unit);
}

export function groupChatResults(results) {
  const groups = new Map();
  for (const result of results) {
    if (!groups.has(result.thread_id)) groups.set(result.thread_id, { title: result.thread_title, results: [] });
    groups.get(result.thread_id).results.push(result);
  }
  return [...groups.values()];
}

export function chatSearchShortcut(event) {
  if (event.defaultPrevented || event.repeat || event.isComposing || event.altKey || event.shiftKey) return false;
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") return true;
  const typing = event.target?.isContentEditable || event.target?.closest?.("input, textarea, select, [role=textbox]");
  return event.key === "/" && !event.metaKey && !event.ctrlKey && !typing;
}

export function createChatSearch({ api, thread, jump, reveal, prepareFind }) {
  const get = (id) => document.getElementById(id);
  const trigger = get("open-chat-search"), dialog = get("chat-search-dialog"), panel = get("chat-search");
  const find = get("chat-find"), title = get("chat-search-title"), input = get("chat-search-query");
  const all = get("search-all-chats"), here = get("search-this-chat"), controls = get("chat-find-controls");
  const up = get("chat-find-up"), down = get("chat-find-down"), status = get("chat-search-status");
  const results = get("chat-search-results"), footer = get("chat-search-footer"), more = get("chat-search-more");
  const clear = get("clear-chat-search");
  const sheet = matchMedia("(max-width: 760px)");
  const popover = typeof dialog.showPopover === "function";
  let mode, timer, request, focusBack;
  let rows = [], options = [], before, total = 0, active = -1, match = -1, working = false;

  function setStatus(text) {
    status.textContent = text;
  }

  function position() {
    if (mode !== "all" || sheet.matches) return;
    const anchor = trigger.getBoundingClientRect();
    const viewport = document.documentElement;
    const top = anchor.bottom + 8;
    dialog.style.setProperty("--chat-search-top", `${top}px`);
    dialog.style.setProperty("--chat-search-space", `${viewport.clientHeight - top - 8}px`);
    const left = Math.max(8, Math.min(anchor.right - dialog.offsetWidth, viewport.clientWidth - dialog.offsetWidth - 8));
    dialog.style.setProperty("--chat-search-left", `${left}px`);
  }

  function showDialog() {
    dialog.hidden = false;
    dialog.toggleAttribute("data-sheet", sheet.matches);
    if (sheet.matches) dialog.showModal();
    else if (popover) {
      dialog.setAttribute("popover", "manual");
      dialog.showPopover();
    }
    position();
  }

  function hideDialog() {
    if (dialog.open) dialog.close();
    if (dialog.hasAttribute("popover")) {
      dialog.hidePopover();
      dialog.removeAttribute("popover");
    }
    dialog.hidden = true;
  }

  function cancel() {
    clearTimeout(timer);
    request?.abort();
    request = undefined;
    working = false;
  }

  function close({ restoreFocus = true } = {}) {
    if (!mode) return false;
    mode = undefined;
    cancel();
    hideDialog();
    find.hidden = true;
    dialog.append(panel);
    trigger.setAttribute("aria-expanded", "false");
    if (restoreFocus) (focusBack?.getClientRects().length ? focusBack : trigger).focus({ preventScroll: true });
    return true;
  }

  function open(next = "all", opener = document.activeElement) {
    if (mode === next) {
      input.focus({ preventScroll: true });
      return;
    }
    if (!mode) focusBack = opener === document.body || opener === document.documentElement ? trigger : opener;
    mode = next;
    const global = mode === "all";
    title.textContent = global ? "Search chats" : "Find in chat";
    all.setAttribute("aria-pressed", String(global));
    here.setAttribute("aria-pressed", String(!global));
    trigger.setAttribute("aria-expanded", String(global));
    controls.hidden = global;
    if (global) {
      find.hidden = true;
      dialog.append(panel);
      input.setAttribute("role", "combobox");
      input.setAttribute("aria-autocomplete", "list");
      input.setAttribute("aria-controls", results.id);
      showDialog();
    } else {
      hideDialog();
      prepareFind();
      find.append(panel);
      find.hidden = false;
      for (const attr of ["role", "aria-autocomplete", "aria-controls", "aria-expanded"]) input.removeAttribute(attr);
    }
    schedule();
    input.focus({ preventScroll: true });
  }

  function select(index, scroll = true) {
    if (options[active]) options[active].item.setAttribute("aria-selected", "false");
    active = index;
    const option = options[index]?.item;
    if (!option) {
      input.removeAttribute("aria-activedescendant");
      return;
    }
    option.setAttribute("aria-selected", "true");
    input.setAttribute("aria-activedescendant", option.id);
    if (scroll) option.scrollIntoView({ block: "nearest" });
  }

  function renderResults() {
    const current = options[active]?.row;
    options = [];
    const global = mode === "all";
    const groups = global ? groupChatResults(rows) : [];
    results.replaceChildren(...groups.map(({ title, results: matches }, index) => {
      const group = document.createElement("div"), heading = document.createElement("div");
      group.setAttribute("role", "group");
      heading.id = `chat-search-group-${index}`;
      heading.className = "chat-search-group-title";
      heading.textContent = title;
      group.setAttribute("aria-labelledby", heading.id);
      group.append(heading);
      for (const row of matches) {
        const item = document.createElement("div"), excerpt = document.createElement("span");
        const meta = document.createElement("span"), time = document.createElement("time");
        item.setAttribute("role", "option");
        item.setAttribute("aria-selected", "false");
        item.id = `chat-search-option-${options.length}`;
        item.className = "chat-search-result";
        excerpt.className = "chat-search-snippet";
        for (const { text, match } of row.snippet) {
          if (match) {
            const mark = document.createElement("mark");
            mark.textContent = text;
            excerpt.append(mark);
          } else excerpt.append(text);
        }
        meta.className = "chat-search-meta";
        meta.textContent = row.role === "user" ? "You" : "Ember";
        if (row.at) time.dateTime = row.at;
        time.textContent = relativeChatTime(row.at);
        if (time.textContent) meta.append(" · ", time);
        item.append(excerpt, meta);
        options.push({ row, item });
        item.addEventListener("click", () => choose(row));
        group.append(item);
      }
      return group;
    }));
    active = -1;
    select(current ? options.findIndex(({ row }) => current === row) : -1, false);
    results.hidden = !options.length;
    footer.hidden = !global || !before;
    if (global) input.setAttribute("aria-expanded", String(!results.hidden));
  }

  function schedule() {
    cancel();
    clear.hidden = !input.value;
    rows = [];
    before = undefined;
    total = 0;
    match = -1;
    updateControls();
    renderResults();
    const q = input.value.trim(), length = [...q].length;
    if (length < 2 || length > 200) {
      setStatus(length > 200 ? "Use up to 200 characters." : "Enter at least 2 characters to search.");
      return;
    }
    setStatus("Searching…");
    const controller = new AbortController();
    request = controller;
    timer = setTimeout(() => firstPage(controller), 200);
  }

  function updateControls() {
    up.disabled = down.disabled = !total;
    more.disabled = working;
  }

  async function page(controller, cursor) {
    const params = new URLSearchParams({ q: input.value.trim(), limit: "50" });
    if (mode === "find") params.set("thread", thread());
    if (cursor) params.set("before", cursor);
    return api(`/api/chat/search?${params}`, undefined, AbortSignal.any([controller.signal, AbortSignal.timeout(6000)]));
  }

  function showCount() {
    setStatus(rows.length ? `${rows.length} ${rows.length === 1 ? "result" : "results"}${before ? " · more available" : ""}`
      : "No matching messages.");
  }

  async function firstPage(controller) {
    try {
      const data = await page(controller);
      if (controller !== request) return;
      rows = data.results;
      before = data.before;
      if (mode === "all") {
        renderResults();
        results.scrollTop = 0;
        showCount();
      } else {
        total = data.total;
        updateControls();
        if (total) await step(0);
        else setStatus("No matching messages in this chat.");
      }
    } catch {
      if (controller === request) setStatus("Couldn’t search messages. Try again.");
    }
  }

  async function loadMore() {
    if (!before || working || !request) return;
    const controller = request, top = results.scrollTop;
    working = true;
    updateControls();
    try {
      const data = await page(controller, before);
      if (controller !== request) return;
      rows.push(...data.results);
      before = data.before;
      renderResults();
      results.scrollTop = top;
      showCount();
      if (footer.hidden) input.focus({ preventScroll: true });
    } catch {
      if (controller === request) setStatus("Couldn’t load more results. Try again.");
    } finally {
      if (controller === request) {
        working = false;
        updateControls();
      }
    }
  }

  async function choose(row) {
    if (working || !request) return;
    const controller = request;
    working = true;
    updateControls();
    try {
      const item = await jump(row, controller.signal);
      if (controller !== request) return;
      close({ restoreFocus: false });
      reveal(item, { focus: true });
    } catch {
      if (controller === request) setStatus("Couldn’t open that message. Try again.");
    } finally {
      if (controller === request) {
        working = false;
        updateControls();
      }
    }
  }

  async function step(direction) {
    if (!total || working || !request) return;
    const controller = request;
    const index = match < 0 ? (direction < 0 ? total - 1 : 0) : (match + direction + total) % total;
    working = true;
    try {
      while (index >= rows.length && before) {
        const data = await page(controller, before);
        if (controller !== request) return;
        rows.push(...data.results);
        before = data.before;
        total = data.total;
      }
      const item = await jump(rows[index], controller.signal);
      if (controller !== request) return;
      match = index;
      reveal(item);
      setStatus(`${match + 1} of ${total}`);
    } catch {
      if (controller === request) setStatus("Couldn’t open that match. Try again.");
    } finally {
      if (controller === request) working = false;
    }
  }

  trigger.addEventListener("click", () => { if (!close()) open("all", trigger); });
  get("close-chat-search").addEventListener("click", () => close());
  all.addEventListener("click", () => open("all"));
  here.addEventListener("click", () => open("find"));
  up.addEventListener("click", () => step(-1));
  down.addEventListener("click", () => step(1));
  more.addEventListener("click", loadMore);
  clear.addEventListener("click", () => {
    input.value = "";
    input.focus({ preventScroll: true });
    schedule();
  });
  input.addEventListener("input", (event) => { if (!event.isComposing) schedule(); });
  input.addEventListener("compositionend", schedule);
  input.addEventListener("keydown", (event) => {
    if (event.isComposing) return;
    const { key } = event;
    if (mode === "find" && ["ArrowUp", "ArrowDown", "Enter"].includes(key)) {
      event.preventDefault();
      step(key === "ArrowUp" || (key === "Enter" && event.shiftKey) ? -1 : 1);
    } else if (mode === "all" && ["ArrowUp", "ArrowDown", "Enter"].includes(key)) {
      event.preventDefault();
      if (key === "Enter") {
        const option = options[Math.max(0, active)];
        if (option) choose(option.row);
      } else select(threadMenuIndex(key, active, options.length));
    }
  });
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); close(); });
  document.addEventListener("pointerdown", (event) => {
    if (mode === "all" && !sheet.matches && !panel.contains(event.target) && !trigger.contains(event.target)) {
      close({ restoreFocus: false });
    }
  });
  document.addEventListener("focusin", (event) => {
    if (mode === "all" && !sheet.matches && !panel.contains(event.target) && event.target !== trigger) {
      close({ restoreFocus: false });
    }
  });
  sheet.addEventListener("change", () => {
    if (mode !== "all") return;
    hideDialog();
    showDialog();
    input.focus({ preventScroll: true });
  });
  window.addEventListener("resize", position);

  return {
    close,
    threadChanged() { if (mode === "find") schedule(); },
    shortcut(event, canOpen) {
      if (event.defaultPrevented) return false;
      if (mode && event.key === "Escape") close();
      else if (canOpen && chatSearchShortcut(event)) open();
      else return false;
      event.preventDefault();
      return true;
    },
  };
}
