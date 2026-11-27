import { render } from "preact";
import { chatSearchShortcut, groupChatResults, relativeChatTime } from "../chat-search.js";
import { anchorOrigin } from "../motion.js";
import { threadMenuIndex } from "../thread-menu.js";
import { html, Icon } from "../ui.js";

function SearchResult({ row, index, active, onChoose }) {
  const time = relativeChatTime(row.at);
  return html`
    <div role="option" aria-selected=${String(active)} id=${`chat-search-option-${index}`}
      class="chat-search-result" onClick=${() => onChoose(row)}>
      <span class="chat-search-snippet">${(row.snippet || []).map(({ text, match }) => match ? html`<mark>${text}</mark>` : text)}</span>
      <span class="chat-search-meta">${row.role === "user" ? "You" : "Ember"}${time && html` · <time datetime=${row.at}>${time}</time>`}</span>
    </div>
  `;
}

function SearchPanel({ bind, handlers, mode, groups, active, hasQuery, before, total, working, status, loading }) {
  const all = mode === "all";
  return html`
    <div class="chat-search-heading">
      <h2 id="chat-search-title">${all ? "Search chats" : "Find in chat"}</h2>
      <button type="button" id="close-chat-search" class="chat-search-icon" aria-label="Close search"
        title="Close search" onClick=${handlers.onClose}><${Icon} name="x" /></button>
    </div>
    <div class="chat-search-modes" role="group" aria-label="Search scope">
      <button type="button" id="search-all-chats" aria-pressed=${String(all)} onClick=${handlers.onAll}>All chats</button>
      <button type="button" id="search-this-chat" aria-pressed=${String(!all)} onClick=${handlers.onHere}>This chat</button>
    </div>
    <div class="chat-search-field">
      <label class="visually-hidden" for="chat-search-query">Search messages</label>
      <${Icon} name="search" size=${18} />
      <input type="search" id="chat-search-query" class="search-input" placeholder="Search messages…" maxlength="400"
        autocomplete="off" spellcheck=${false} ref=${bind.input} role=${all ? "combobox" : null}
        aria-autocomplete=${all ? "list" : null} aria-controls=${all ? "chat-search-results" : null}
        aria-expanded=${all ? String(!!groups.length) : null}
        aria-activedescendant=${active < 0 ? null : `chat-search-option-${active}`}
        onInput=${handlers.onInput} onCompositionEnd=${handlers.onCompositionEnd} onKeyDown=${handlers.onKeyDown} />
      <button type="button" id="clear-chat-search" class="chat-search-icon search-clear" aria-label="Clear search"
        title="Clear search" hidden=${!hasQuery} onClick=${handlers.onClear}><${Icon} name="x" size=${16} /></button>
    </div>
    <div class="chat-find-controls" id="chat-find-controls" hidden=${all}>
      <button type="button" id="chat-find-up" class="chat-search-icon" aria-label="Previous match"
        title="Previous match" disabled=${!total} onClick=${handlers.onPrevious}><${Icon} name="arrow-up" size=${18} /></button>
      <button type="button" id="chat-find-down" class="chat-search-icon" aria-label="Next match"
        title="Next match" disabled=${!total} onClick=${handlers.onNext}><${Icon} name="arrow-down" size=${18} /></button>
    </div>
    <p id="chat-search-status" class="chat-search-status" role="status">
      ${status}${loading && html`<span class="loading-skeleton" aria-hidden="true"></span>`}
    </p>
    <div id="chat-search-results" class="chat-search-results" role="listbox" aria-label="Matching messages"
      ref=${bind.results} hidden=${!groups.length}>
      ${groups.map(({ title, matches }, index) => html`
        <div key=${matches[0].row.thread_id} role="group" aria-labelledby=${`chat-search-group-${index}`}>
          <div id=${`chat-search-group-${index}`} class="chat-search-group-title">${title}</div>
          ${matches.map(({ row, index }) => html`
            <${SearchResult} key=${row.id} row=${row} index=${index} active=${index === active} onChoose=${handlers.onChoose} />
          `)}
        </div>
      `)}
    </div>
    <div class="chat-search-footer" id="chat-search-footer" ref=${bind.footer} hidden=${!all || !before}>
      <button type="button" id="chat-search-more" disabled=${working} onClick=${handlers.onMore}>Show more</button>
    </div>
  `;
}

export function createChatSearch({ api, thread, jump, reveal, prepareFind }) {
  const get = (id) => document.getElementById(id);
  const trigger = get("open-chat-search"), dialog = get("chat-search-dialog"), panel = get("chat-search");
  const find = get("chat-find");
  const sheet = matchMedia("(max-width: 760px)");
  const popover = typeof dialog.showPopover === "function";
  let mode, timer, request, focusBack;
  let rows = [], groups = [], options = [], before, total = 0, active = -1, match = -1, working = false;
  let status = "", loading = false;
  let input, results, footer;
  const bind = {
    input: (element) => { input = element; },
    results: (element) => { results = element; },
    footer: (element) => { footer = element; },
  };
  const handlers = {
    onClose: () => close(),
    onAll: () => open("all"),
    onHere: () => open("find"),
    onPrevious: () => step(-1),
    onNext: () => step(1),
    onMore: loadMore,
    onChoose: choose,
    onClear() {
      input.value = "";
      input.focus({ preventScroll: true });
      schedule();
    },
    onInput(event) { if (!event.isComposing) schedule(); },
    onCompositionEnd: schedule,
    onKeyDown: inputKeyDown,
  };

  function paint() {
    render(html`<${SearchPanel} bind=${bind} handlers=${handlers} mode=${mode || "all"}
      groups=${groups} active=${active} hasQuery=${!!input?.value} before=${before} total=${total}
      working=${working} status=${status} loading=${loading} />`, panel);
  }

  function setStatus(text) {
    status = text;
    loading = false;
    paint();
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
    anchorOrigin(dialog, anchor);
  }

  function showDialog() {
    dialog.hidden = false;
    dialog.inert = false;
    dialog.toggleAttribute("data-sheet", sheet.matches);
    if (sheet.matches) {
      dialog.removeAttribute("popover");
      dialog.showModal();
    } else if (popover) {
      dialog.setAttribute("popover", "manual");
      dialog.showPopover();
    } else dialog.setAttribute("data-motion-fallback", "");
    position();
  }

  function hideDialog() {
    if (dialog.open) dialog.close();
    if (popover && dialog.matches(":popover-open")) dialog.hidePopover();
    dialog.hidden = true;
    dialog.inert = true;
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
    find.inert = true;
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
    trigger.setAttribute("aria-expanded", String(global));
    if (global) {
      find.hidden = true;
      find.inert = true;
      if (panel.parentElement !== dialog) dialog.append(panel);
      showDialog();
    } else {
      hideDialog();
      prepareFind();
      if (panel.parentElement !== find) find.append(panel);
      find.hidden = false;
      find.inert = false;
    }
    schedule();
    input.focus({ preventScroll: true });
  }

  function select(index) {
    active = index;
    paint();
    if (options[index]) get(`chat-search-option-${index}`).scrollIntoView({ block: "nearest" });
  }

  function groupResults() {
    const selected = options[active];
    let index = 0;
    groups = mode === "all" ? groupChatResults(rows).map((group) => ({
      title: group.title,
      matches: group.results.map((row) => ({ row, index: index++ })),
    })) : [];
    options = groups.flatMap(({ matches }) => matches.map(({ row }) => row));
    active = selected ? options.indexOf(selected) : -1;
  }

  function schedule() {
    cancel();
    rows = [];
    before = undefined;
    total = 0;
    match = -1;
    groupResults();
    const q = input.value.trim(), length = [...q].length;
    if (length < 2 || length > 200) {
      setStatus(length > 200 ? "Use up to 200 characters." : "Enter at least 2 characters to search.");
      return;
    }
    status = "Searching…";
    loading = true;
    paint();
    const controller = new AbortController();
    request = controller;
    timer = setTimeout(() => firstPage(controller), 200);
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
        groupResults();
        showCount();
        results.scrollTop = 0;
      } else {
        total = data.total;
        paint();
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
    paint();
    try {
      const data = await page(controller, before);
      if (controller !== request) return;
      rows.push(...data.results);
      before = data.before;
      groupResults();
      showCount();
      results.scrollTop = top;
      if (footer.hidden) input.focus({ preventScroll: true });
    } catch {
      if (controller === request) setStatus("Couldn’t load more results. Try again.");
    } finally {
      if (controller === request) {
        working = false;
        paint();
      }
    }
  }

  async function choose(row) {
    if (working || !request) return;
    const controller = request;
    working = true;
    paint();
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
        paint();
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
  function inputKeyDown(event) {
    if (event.isComposing) return;
    const { key } = event;
    if (mode === "find" && ["ArrowUp", "ArrowDown", "Enter"].includes(key)) {
      event.preventDefault();
      step(key === "ArrowUp" || (key === "Enter" && event.shiftKey) ? -1 : 1);
    } else if (mode === "all" && ["ArrowUp", "ArrowDown", "Enter"].includes(key)) {
      event.preventDefault();
      if (key === "Enter") {
        const option = options[Math.max(0, active)];
        if (option) choose(option);
      } else select(threadMenuIndex(key, active, options.length));
    }
  }
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); close(); });
  function dismissOnOutsideInteraction(event) {
    // A pointer press on a result can focus the dialog before the click is delivered.
    if (mode === "all" && !sheet.matches && !dialog.contains(event.target) && !trigger.contains(event.target)) {
      close({ restoreFocus: false });
    }
  }
  document.addEventListener("pointerdown", dismissOnOutsideInteraction);
  document.addEventListener("focusin", dismissOnOutsideInteraction);
  sheet.addEventListener("change", () => {
    if (mode !== "all") return;
    hideDialog();
    showDialog();
    input.focus({ preventScroll: true });
  });
  window.addEventListener("resize", position);

  paint();
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
