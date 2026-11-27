import { render as paint } from "preact";
import { html, Icon } from "../ui.js";
import { Control, DetailLink, IconControl, Rows } from "./view.js";
import { panelRequestPrompt, panelRequestFeedback } from "./panel-request.js";
import { createGoals } from "../goals.js";
import { threadMenuPosition } from "../thread-menu.js";
import { anchorOrigin, arrive, fixedBounds, freezeAnchor, prepareListMotion } from "../motion.js";

const get = (id) => document.getElementById(id);
const demoPrompt = "Create the Thanksgiving countdown and shopping list Home panels";
const builtIns = {
  feed: { title: "Feed", icon: "sparkle" },
  goals: { title: "Goals", icon: "activity" },
  today: { title: "Today", icon: "bell", page: "reminders", link: "Open Reminders" },
  inbox: { title: "Inbox to review", icon: "inbox", page: "inbox", link: "Open Inbox" },
  weather: { title: "Weather & clock", icon: "cloud", page: "weather", link: "Weather settings" },
  files: { title: "Recent files", icon: "files", page: "artifacts", link: "Open Artifacts" },
  memory: { title: "Memory", icon: "book", page: "memory", link: "Open Memory" },
  activity: { title: "Activity", icon: "activity", page: "timeline", link: "Open Timeline" },
  connections: { title: "Connections health", icon: "plug" },
};
const kindIcons = { stat: "activity", list: "list", checklist: "check", countdown: "clock", note: "file-text",
  "web-summary": "monitor" };
const quickPanels = {
  countdown: "Ask me for the target date in Chat.",
  checklist: "Start with an empty checklist.",
  list: "Start with an empty list.",
  note: "Use “Write a note here.” as the starter text.",
  stat: "Start with a value of 0.",
  "web-summary": "Ask me for the public page URL in Chat.",
};
const calendar = { weekday: "long", month: "long", day: "numeric" };
const number = new Intl.NumberFormat();
const standardTime = { hour: "numeric", minute: "2-digit" };
const dailyDate = (zone) => new Intl.DateTimeFormat("en-CA", {
  timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit",
});

function Metric({ count, singular, plural = `${singular}s` }) {
  return html`<p class="home-metric"><strong>${number.format(count)}</strong><span>${count === 1 ? singular : plural}</span></p>`;
}

function Time({ at, formatter }) {
  return html`<time datetime=${at}>${formatter.format(new Date(at))}</time>`;
}

function Dot({ label, state, title }) {
  return html`<span class=${`home-status is-${state}`} title=${title}><span class="home-dot"></span><span>${label}</span></span>`;
}

function weatherLabel(code) {
  if (code === 0) return "Clear";
  if (code === 1) return "Mostly clear";
  if (code === 2) return "Partly cloudy";
  if (code === 3) return "Overcast";
  if (code <= 48) return "Fog";
  if (code <= 57) return "Drizzle";
  if (code <= 67) return "Rain";
  if (code <= 77 || [85, 86].includes(code)) return "Snow";
  if (code <= 82) return "Rain showers";
  return "Thunderstorms";
}

function updatedLabel(value) {
  const minutes = Math.max(0, Math.floor((Date.now() - Date.parse(value)) / 60000));
  if (!minutes) return "Updated just now";
  if (minutes < 60) return `Updated ${minutes} min ago`;
  if (minutes < 1440) return `Updated ${Math.floor(minutes / 60)} hr ago`;
  const days = Math.floor(minutes / 1440);
  return `Updated ${days} ${days === 1 ? "day" : "days"} ago`;
}

export function createHome({ api, refreshAPI, openView, openWeatherSettings, openConnections, openFile, openPanelChat,
  openDemo, sendPanelPrompt, openMainChat, feed, approvalCard, onData }) {
  const section = get("home-view");
  const grid = get("home-grid");
  const edit = get("home-edit");
  const feedback = get("home-feedback");
  const addPopover = get("home-add-popover");
  const restoreItems = get("home-add-restore-items");
  const description = get("home-add-description");
  const desktop = matchMedia("(min-width: 761px) and (pointer: fine)");
  const sheet = matchMedia("(max-width: 760px)");
  const viewport = window.visualViewport;
  const nativePopover = typeof addPopover.showPopover === "function";
  const cssAnchor = nativePopover && CSS.supports("position-area", "block-end span-inline-start")
    && CSS.supports("position-try-fallbacks", "flip-block, flip-inline");
  if (!nativePopover) addPopover.removeAttribute("popover");
  let snapshot;
  let editing = false;
  let request = 0;
  let settingsRequest = 0;
  let moving = false;
  let sendingPanel = false;
  let dragged;
  let hovered;
  let signature;
  let presented = false;
  let dayFormat, shortDayFormat, timeFormat, dateTimeFormat, compactDateTime, dateKey;
  const pending = new Set();

  const goals = createGoals({ api, approvalCard, reload: load });
  const titleFor = (id) => builtIns[id]?.title || snapshot.panels[id]?.title;
  const visible = () => snapshot.layout.order.filter((id) => !snapshot.layout.hidden.includes(id));
  function setFeedback(message = "", openChat = false) {
    paint(html`${message}${openChat ? html`${" "}<${Control} label="Open Chat" action=${openMainChat} />` : null}`, feedback);
    if (message) arrive([feedback]);
  }

  let add;
  const addRef = (node) => { add = node; };

  function positionAdd() {
    if (addPopover.hidden || !add) return;
    const left = viewport?.offsetLeft ?? 0;
    const top = viewport?.offsetTop ?? 0;
    const width = viewport?.width ?? document.documentElement.clientWidth;
    const height = viewport?.height ?? document.documentElement.clientHeight;
    const screen = { left, top, right: left + width, bottom: top + height };
    const styles = getComputedStyle(addPopover);
    const gap = parseFloat(styles.getPropertyValue("--home-add-gap"));
    const inset = parseFloat(styles.getPropertyValue("--home-add-inset"));
    const anchored = cssAnchor && !sheet.matches;
    addPopover.style.width = sheet.matches ? `${width}px` : "";
    addPopover.style.maxWidth = sheet.matches ? "" : `${width - 2 * inset}px`;
    addPopover.style.maxHeight = `${height - (sheet.matches ? inset : 2 * inset)}px`;
    addPopover.style.removeProperty("left");
    addPopover.style.removeProperty("top");
    addPopover.toggleAttribute("data-anchor", anchored);
    const bounds = fixedBounds(addPopover);
    const anchor = add.getBoundingClientRect();
    if (!anchored || bounds.left < left + inset || bounds.right > screen.right - inset
        || bounds.top < top + inset || bounds.bottom > screen.bottom - inset) {
      addPopover.removeAttribute("data-anchor");
      const position = sheet.matches ? { left, top: screen.bottom - bounds.height }
        : threadMenuPosition(anchor, bounds, screen, gap, inset);
      addPopover.style.left = `${position.left}px`;
      addPopover.style.top = `${position.top}px`;
    }
    anchorOrigin(addPopover, anchor);
  }

  function closeAdd({ restoreFocus = true } = {}) {
    if (addPopover.hidden) return;
    freezeAnchor(addPopover);
    if (nativePopover) addPopover.hidePopover();
    addPopover.hidden = true;
    addPopover.inert = true;
    add?.setAttribute("aria-expanded", "false");
    if (restoreFocus) add?.focus({ preventScroll: true });
  }

  function openAdd() {
    const hidden = snapshot.layout.hidden;
    paint(hidden.map((id) => html`<li class="home-add-restore-row" key=${id}>
      <span>${titleFor(id)}</span>
      <${Control} label="Restore" symbol="plus" className="home-add-action" accessibleName=${`Restore ${titleFor(id)}`}
        action=${() => {
          if (moving) return;
          closeAdd();
          adjust(id, "restore");
        }} />
    </li>`), restoreItems);
    get("home-add-restore-empty").hidden = !!hidden.length;
    add.setAttribute("aria-expanded", "true");
    addPopover.hidden = false;
    addPopover.inert = false;
    if (nativePopover) addPopover.showPopover();
    addPopover.scrollTop = 0;
    positionAdd();
    get("home-add-close").focus({ preventScroll: true });
  }

  async function requestPanel(prompt) {
    if (sendingPanel || !prompt) return;
    closeAdd();
    sendingPanel = true;
    add?.setAttribute("aria-busy", "true");
    setFeedback("Sending panel request to Chat…");
    try {
      const result = panelRequestFeedback(await sendPanelPrompt(prompt));
      setFeedback(result.message, result.openChat);
    } catch (error) {
      setFeedback(error.message);
    } finally {
      sendingPanel = false;
      add?.removeAttribute("aria-busy");
    }
  }

  paint(Object.entries(quickPanels).map(([kind, instruction]) => html`
    <${Control} key=${kind} label=${kind === "web-summary" ? "Web summary" : kind[0].toUpperCase() + kind.slice(1)}
      action=${() => requestPanel(`Create a starter ${kind} Home panel. ${instruction}`)}
      symbol=${kindIcons[kind]} className="home-add-action" />
  `), get("home-add-kinds"));
  get("home-add-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const prompt = panelRequestPrompt(description.value);
    if (!prompt || sendingPanel) return;
    description.value = "";
    requestPanel(prompt);
  });
  get("home-add-close").addEventListener("click", () => closeAdd());
  document.addEventListener("click", (event) => {
    if (addPopover.hidden || addPopover.contains(event.target) || add?.contains(event.target)) return;
    if (sheet.matches) {
      event.preventDefault();
      event.stopPropagation();
    }
    closeAdd();
  }, true);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || addPopover.hidden) return;
    event.preventDefault();
    event.stopPropagation();
    closeAdd();
  }, true);
  section.addEventListener("scroll", positionAdd, { passive: true });
  window.addEventListener("resize", positionAdd);
  viewport?.addEventListener("resize", positionAdd);
  viewport?.addEventListener("scroll", positionAdd);

  async function load({ background } = {}) {
    const sequence = ++request;
    try {
      const data = await refreshAPI("/api/home", { background, signal: AbortSignal.timeout(15000) });
      if (sequence !== request || section.hidden) return;
      const next = JSON.stringify(data);
      snapshot = data;
      onData(data);
      if (next === signature) {
        updateClocks();
        return;
      }
      signature = next;
      dayFormat = new Intl.DateTimeFormat(undefined, { ...calendar, timeZone: data.timezone });
      shortDayFormat = new Intl.DateTimeFormat(undefined, {
        weekday: "short", month: "short", day: "numeric", timeZone: data.timezone,
      });
      timeFormat = new Intl.DateTimeFormat(undefined, { ...standardTime, timeZone: data.timezone });
      dateTimeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: data.timezone });
      compactDateTime = new Intl.DateTimeFormat(undefined, {
        ...standardTime, month: "short", day: "numeric", timeZone: data.timezone,
      });
      dateKey = dailyDate(data.timezone);
      render();
    } catch (error) {
      if (!background && sequence === request && !section.hidden) setFeedback(error.message);
    }
  }

  const wallClock = new Intl.DateTimeFormat(undefined, { ...standardTime, timeZone: "UTC" });
  const quietTime = (value) => wallClock.format(new Date(`2000-01-01T${value}:00Z`));
  function BuiltinBody({ id, data }) {
    let content;
    if (id === "today") {
      const title = data.quiet_until ? "Quiet hours active" : data.quiet_enabled ? "Quiet hours off now" : "Quiet hours disabled";
      const quiet = data.quiet_until ? `Until ${timeFormat.format(new Date(data.quiet_until))}`
        : data.quiet_enabled ? `${quietTime(data.quiet_start)}–${quietTime(data.quiet_end)}` : "";
      content = html`
        <div class="home-quiet"><${Icon} name="moon" size=${18} /><strong>${title}</strong>${quiet && html`<span>${quiet}</span>`}</div>
        <p class="home-list-heading">Next reminders</p>
        <${Rows} items=${data.jobs} empty="No upcoming reminders." children=${(item) => html`
          <${Time} at=${item.at} formatter=${dateKey.format(new Date(item.at)) === dateKey.format(new Date()) ? timeFormat : compactDateTime} />
          <span>${item.message}</span>`} />
      `;
    } else if (id === "inbox") {
      content = html`<${Metric} count=${data.count} singular="item to review" plural="items to review" />
        <${Rows} items=${data.items} empty="You’re caught up."
          children=${(item) => html`<span class="home-bullet"></span><span>${item.title}</span>`} />`;
    } else if (id === "files") {
      content = html`<${Rows} items=${data.items} empty="No files saved yet." children=${(item) => html`
        <button type="button" class="home-file" aria-haspopup="dialog" data-control=${`file-${item.id}`}
          data-artifact-id=${item.id} onClick=${(event) => openFile(item, event.currentTarget)}>
          <span class="home-format">${item.kind === "page" ? "Page" : item.format.toUpperCase()}</span><span>${item.title}</span>
        </button>`} />`;
    } else if (id === "memory") {
      const tone = /error|failed|unavailable/i.test(data.pinecone) ? "error"
        : /^(ready|connected|synced)$/i.test(data.pinecone) ? "ok" : "neutral";
      content = html`
        <${Metric} count=${data.count} singular="saved note" />
        <p class="home-detail"><span>Pinecone</span><${Dot} label=${data.pinecone} state=${tone} /></p>
        ${data.record_count != null && html`<p class="home-detail"><span>Indexed chunks</span><span>${number.format(data.record_count)}</span></p>`}
        <p class="home-detail"><span>Last synced</span>${data.last_sync
          ? html`<${Time} at=${data.last_sync} formatter=${dateTimeFormat} />` : html`<span>Never</span>`}</p>`;
    } else if (id === "activity") {
      const dateOnly = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", timeZone: snapshot.timezone });
      content = html`
        <${Metric} count=${data.count} singular="event today" plural="events today" />
        ${data.errors ? html`<a class="home-link home-error" href="#timeline/errors">
          ${data.errors} ${data.errors === 1 ? "error" : "errors"} today</a>` : null}
        <${Rows} items=${data.items} empty="No activity yet." children=${(item) => html`
          <${Time} at=${item.at} formatter=${dateKey.format(new Date(item.at)) === dateKey.format(new Date()) ? timeFormat : dateOnly} />
          <span>${item.title}</span>`} />
      `;
    } else if (id === "connections") {
      content = html`${data.error && html`<p class="home-error">${data.error}</p>`}
        <${Rows} items=${data.items} empty="No configured connectors." children=${(item) => html`
          <span>${item.name}</span><${Dot} label=${{ ok: "OK", error: "Error", not_connected: "Not connected" }[item.status]}
            state=${item.status === "not_connected" ? "neutral" : item.status} title=${item.detail} />`} />`;
    } else if (id === "weather") {
      content = html`<div class="home-weather">
        <div><time class="home-weather-value" id="home-clock"></time><p class="home-meta">Pacific time</p></div>
        <div>
          <p class="home-location">${data.name}</p>
          ${data.value ? html`<p class="home-weather-value">${data.value.temperature}°F</p>
            <p class="home-meta">${weatherLabel(data.value.code)}</p>`
            : html`<p class="home-meta">${data.error ? "No weather data" : "Fetching weather…"}</p>`}
        </div>
      </div>`;
    }
    return html`<div class="home-card-body">${content}</div>`;
  }

  function CustomBody({ row }) {
    let content;
    if (row.value === null) {
      content = html`<p class="home-meta">${row.error ? "No saved value." : "Waiting for the first refresh…"}</p>`;
    } else if (row.kind === "stat") {
      content = html`<p class="home-stat">${typeof row.value === "number" ? number.format(row.value) : row.value}</p>`;
    } else if (row.kind === "countdown") {
      const formatter = row.value.length === 10
        ? new Intl.DateTimeFormat(undefined, { ...calendar, timeZone: "UTC" }) : dateTimeFormat;
      content = html`<p class="home-stat" data-countdown=${row.value}></p><p class="home-meta">${formatter.format(new Date(row.value))}</p>`;
    } else if (row.kind === "checklist") {
      content = html`<${Rows} items=${row.value} empty="No items yet." children=${(item, index) => html`
        <label class="home-check">
          <input type="checkbox" checked=${item.checked} disabled=${row.source.type !== "static"} data-control=${`check-${index}`}
            onClick=${(event) => { if (pending.has(row.id)) event.preventDefault(); }}
            onChange=${(event) => {
              const check = event.currentTarget;
              mutate(row.id, "checklist", { index, checked: check.checked, revision: row.revision }, check);
            }} />
          <span>${item.text}</span>
        </label>`} />`;
    } else if (row.kind === "list") {
      content = html`<${Rows} items=${row.value} empty="No items yet."
        children=${(item) => html`<span class="home-bullet"></span><span>${item}</span>`} />`;
    } else {
      content = html`<p class="home-note">${row.value}</p>`;
    }
    return html`<div class="home-card-body">${content}</div>`;
  }

  function updateClocks() {
    if (!snapshot || section.hidden) return;
    const now = new Date();
    for (const [id, format] of [["home-date-full", dayFormat], ["home-date-compact", shortDayFormat]]) {
      const day = get(id);
      day.textContent = format.format(now);
      day.dateTime = dateKey.format(now);
    }
    const clock = get("home-clock");
    if (clock) {
      clock.textContent = new Intl.DateTimeFormat(undefined, { ...standardTime, timeZone: snapshot.clock_zone }).format(now);
      clock.dateTime = now.toISOString();
    }
    for (const time of grid.querySelectorAll("[data-updated]")) time.textContent = updatedLabel(time.dateTime);
    for (const timer of grid.querySelectorAll("[data-countdown]")) {
      const target = timer.dataset.countdown;
      if (target.length === 10) {
        const days = Math.round((Date.parse(target) - Date.parse(dateKey.format(now))) / 86400000);
        timer.textContent = days < 0 ? "Passed" : days === 0 ? "Today" : `${days} ${days === 1 ? "day" : "days"}`;
      } else {
        const minutes = Math.ceil((Date.parse(target) - now.valueOf()) / 60000);
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);
        timer.textContent = minutes <= 0 ? "Passed" : days > 0 ? `${days}d ${hours % 24}h`
          : hours > 0 ? `${hours}h ${minutes % 60}m` : `${minutes} min`;
      }
    }
  }

  function SourceFooter({ id, row, kind }) {
    let link;
    if (id === "connections" || (!kind && row.source.type === "connector")) {
      link = html`<${Control} label="Open Connections" action=${openConnections} />`;
    } else if (kind) {
      link = html`<${Control} label=${kind.link} action=${() => kind.page === "weather" ? openWeatherSettings() : openView(kind.page)} />`;
    } else if (row.source.type === "url" && /^https?:\/\//.test(row.source.url)) {
      link = html`<${DetailLink} label="Open source" href=${row.source.url} />`;
    }
    async function ask(event) {
      const button = event.currentTarget;
      button.disabled = true;
      try { await openPanelChat(id); }
      catch (error) { setFeedback(error.message); }
      finally { button.disabled = false; }
    }
    return html`<footer class="home-footer">
      ${row.error && (id === "weather" || !kind) && html`<p class="home-error">
        ${row.value === null ? row.error : `Showing last value. ${row.error}`}</p>`}
      <div class="home-card-links">${link}<${Control} label="Ask about this" symbol="message" control="ask" action=${ask} /></div>
      ${(id === "weather" || !kind) && html`<div class="home-refresh-row">
        ${row.updated_at ? html`<time datetime=${row.updated_at} data-updated="" title=${dateTimeFormat.format(new Date(row.updated_at))}>
          ${updatedLabel(row.updated_at)}</time>` : html`<span>${row.error ? "Refresh failed" : "Waiting for update"}</span>`}
        ${id === "weather" && html`<${DetailLink} label="Open-Meteo" href="https://open-meteo.com/" />`}
        <${IconControl} label=${`Refresh ${titleFor(id)}`} symbol="refresh" control="refresh" disabled=${pending.has(id)}
          action=${(event) => mutate(id, "refresh", {}, event.currentTarget)} />
      </div>`}
    </footer>`;
  }

  function startDrag(id, event) {
    if (moving) return event.preventDefault();
    dragged = id;
    event.currentTarget.closest("[data-panel]").classList.add("is-dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", id);
  }

  function dragOver(id, event) {
    if (!dragged || dragged === id) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    const card = event.currentTarget;
    if (hovered !== card) {
      hovered?.classList.remove("is-drop-target");
      hovered = card;
      card.classList.add("is-drop-target");
    }
  }

  function drop(id, event) {
    if (!dragged || dragged === id) return;
    event.preventDefault();
    const source = dragged;
    const order = visible();
    clearDrag();
    adjust(source, "move", { target: id, position: order.indexOf(source) < order.indexOf(id) ? "after" : "before" });
  }

  function clearDrag() {
    grid.querySelector(".is-dragging")?.classList.remove("is-dragging");
    hovered?.classList.remove("is-drop-target");
    hovered = undefined;
    dragged = undefined;
  }

  function LayoutTools({ id, order }) {
    const at = order.indexOf(id);
    const title = titleFor(id);
    return html`<div class="home-order-tools">
      ${[["up", -1, "before"], ["down", 1, "after"]].map(([direction, offset, position]) => {
        const target = order[at + offset];
        return html`<${IconControl} key=${direction} label=${`Move ${title} ${direction}`} symbol=${`arrow-${direction}`}
          control=${direction} disabled=${!target} action=${() => adjust(id, "move", { target, position }, direction)} />`;
      })}
      <${IconControl} label=${`Remove ${title} from Home`} symbol="x" action=${() => adjust(id, "hide")} />
    </div>`;
  }

  function attachFeed(node) {
    if (node && feed.root.parentNode !== node) node.append(feed.root);
  }

  function Panel({ id, order }) {
    const kind = builtIns[id];
    const row = kind ? snapshot.builtin[id] : snapshot.panels[id];
    const title = titleFor(id);
    return html`<article class=${`home-card home-card-${kind ? id : row.kind}`} data-panel=${id} data-motion-key=${id}
      aria-labelledby=${`home-panel-${id}`} ref=${id === "feed" ? attachFeed : undefined}
      onDragOver=${desktop.matches ? (event) => dragOver(id, event) : undefined}
      onDrop=${desktop.matches ? (event) => drop(id, event) : undefined}>
      <header class="home-card-header">
        <span class="home-card-icon"><${Icon} name=${kind?.icon || kindIcons[row.kind]} size=${19} /></span>
        <h2 id=${`home-panel-${id}`}>${title}</h2>
        ${editing && html`<${LayoutTools} ...${{ id, order }} />`}
        ${desktop.matches && html`<span class="home-grip" draggable="true" aria-hidden="true" title=${`Drag ${title} to reorder`}
          onDragStart=${(event) => startDrag(id, event)} onDragEnd=${clearDrag}><${Icon} name="grip" size=${19} /></span>`}
      </header>
      ${id === "feed" ? null : id === "goals" ? html`<div class="home-card-body goal-body"
        ref=${(node) => { if (node) goals.render(row, snapshot.timezone, dateTimeFormat, node); }}></div>` : html`
        ${kind ? html`<${BuiltinBody} id=${id} data=${row} />` : html`<${CustomBody} row=${row} />`}
        <${SourceFooter} ...${{ id, row, kind }} />`}
    </article>`;
  }

  function render() {
    if (!snapshot || section.hidden) return;
    const active = document.activeElement;
    const panel = active.closest("[data-panel]")?.dataset.panel;
    const key = active.dataset.control;
    const order = visible();
    const play = prepareListMotion(grid, order, { stagger: !presented });
    if (!editing) closeAdd({ restoreFocus: false });
    const addFocused = active === add;
    paint(html`
      ${order.map((id) => html`<${Panel} key=${id} ...${{ id, order }} />`)}
      ${editing && html`<button type="button" class="home-card home-add-card" id="home-add" ref=${addRef} aria-haspopup="dialog"
        aria-controls=${addPopover.id} aria-expanded=${String(!addPopover.hidden)}
        aria-busy=${sendingPanel ? "true" : undefined} onClick=${() => addPopover.hidden ? openAdd() : closeAdd()}>
        <span class="home-card-icon"><${Icon} name="plus" size=${22} /></span><span>Add panel</span>
      </button>`}
    `, grid);
    if (feed.root.isConnected) feed.show();
    grid.classList.toggle("is-editing", editing);
    get("home-loading").hidden = true;
    get("home-empty").hidden = editing || order.length > 0;
    get("home-demo").hidden = editing || snapshot.model !== "mock" || Object.keys(snapshot.panels).length > 0;
    edit.disabled = false;
    edit.setAttribute("aria-pressed", String(editing));
    get("home-edit-label").textContent = editing ? "Done" : "Edit layout";
    presented = true;
    play();
    if (editing && addFocused) add.focus({ preventScroll: true });
    if (panel && key) grid.querySelector(`[data-panel="${CSS.escape(panel)}"] [data-control="${CSS.escape(key)}"]`)?.focus();
    positionAdd();
    updateClocks();
  }

  async function adjust(id, operation, extra = {}, focus) {
    if (moving) return;
    moving = true;
    setFeedback();
    try {
      snapshot.layout = await api("/api/home/layout", { id, operation, ...extra });
      signature = JSON.stringify(snapshot);
      render();
      if (operation === "hide") {
        edit.focus();
        setFeedback(`${titleFor(id)} removed from Home.`);
      } else if (operation === "restore") {
        setFeedback(`${titleFor(id)} restored.`);
      } else {
        const panel = grid.querySelector(`[data-panel="${CSS.escape(id)}"]`);
        const button = focus && panel && (panel.querySelector(`[data-control="${focus}"]:enabled`)
          || panel.querySelector(".home-order-tools button:enabled"));
        button?.focus();
        setFeedback(`${titleFor(id)} moved.`);
      }
    } catch (error) {
      setFeedback(error.message);
    } finally {
      moving = false;
    }
  }

  async function mutate(id, path, data, button) {
    if (pending.has(id)) return;
    pending.add(id);
    button.setAttribute("aria-busy", "true");
    setFeedback();
    try {
      const result = await api(`/api/home/${path}`, { id, ...data });
      pending.delete(id);
      await load();
      if (result?.error) setFeedback(`${titleFor(id)} refresh failed. ${result.error}`);
    } catch (error) {
      pending.delete(id);
      await load();
      setFeedback(error.message);
      if (path === "checklist") render();
    } finally {
      pending.delete(id);
      button.removeAttribute("aria-busy");
    }
  }

  let settingsForm, location, settingsStatus, settingsSave;
  async function settings() {
    if (!settingsForm) {
      settingsForm = get("weather-settings-form");
      location = get("weather-location");
      settingsStatus = get("weather-settings-status");
      settingsSave = get("weather-location-save");
      settingsForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const sequence = ++settingsRequest;
        settingsSave.disabled = true;
        settingsStatus.textContent = "Saving…";
        try {
          const data = await api("/api/home/settings", { location: location.value });
          if (sequence === settingsRequest) {
            location.value = data.location;
            settingsStatus.textContent = data.error || "Location saved. Home will refresh the forecast.";
          }
        } catch (error) {
          if (sequence === settingsRequest) settingsStatus.textContent = error.message;
        } finally {
          settingsSave.disabled = false;
        }
      });
    }
    const sequence = ++settingsRequest;
    settingsStatus.textContent = "";
    try {
      const data = await api("/api/home/settings");
      if (sequence !== settingsRequest) return;
      location.value = data.location;
      settingsStatus.textContent = data.error || "";
    } catch (error) {
      if (sequence === settingsRequest) settingsStatus.textContent = error.message;
    }
  }

  edit.addEventListener("click", () => {
    editing = !editing;
    setFeedback();
    render();
  });
  desktop.addEventListener("change", render);
  get("home-demo").addEventListener("click", () => openDemo(demoPrompt));
  setInterval(() => {
    if (!section.hidden && !document.hidden) updateClocks();
  }, 10000);
  setInterval(() => {
    if (!section.hidden && !document.hidden && !editing && !dragged && !pending.size && !document.querySelector("dialog[open]")) load();
  }, 30000);
  return { load, settings, closeAdd };
}
