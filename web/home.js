import { icon, iconButton } from "./icons.js";

const get = (id) => document.getElementById(id);
const demoPrompt = "Create the Thanksgiving countdown and shopping list Home panels";
const builtIns = {
  today: { title: "Today", icon: "bell", page: "reminders", link: "Open Reminders" },
  inbox: { title: "Inbox to review", icon: "inbox", page: "inbox", link: "Open Inbox" },
  weather: { title: "Weather & clock", icon: "cloud", page: "weather", link: "Weather settings" },
  files: { title: "Recent files", icon: "files", page: "artifacts", link: "Open Artifacts" },
  memory: { title: "Memory", icon: "book", page: "memory", link: "Open Memory" },
  activity: { title: "Activity", icon: "activity", page: "timeline", link: "Open Timeline" },
  connections: { title: "Connections health", icon: "plug", page: "connections", link: "Open Connections" },
};
const kindIcons = { stat: "activity", list: "list", checklist: "check", countdown: "clock", note: "file-text",
  "web-summary": "monitor" };
const calendar = { weekday: "long", month: "long", day: "numeric" };
const number = new Intl.NumberFormat();
const standardTime = { hour: "numeric", minute: "2-digit" };
const dailyDate = (zone) => new Intl.DateTimeFormat("en-CA", {
  timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit",
});

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function control(label, handler, symbol, className = "home-link") {
  const element = node("button", className);
  element.type = "button";
  if (symbol) element.append(icon(symbol, 15));
  element.append(node("span", "", label));
  element.addEventListener("click", handler);
  return element;
}

function timeElement(value, text) {
  const element = node("time", "", text);
  element.dateTime = value;
  return element;
}

function labelCount(count, singular, plural = `${singular}s`) {
  const row = node("p", "home-metric");
  row.append(node("strong", "", number.format(count)), node("span", "", count === 1 ? singular : plural));
  return row;
}

function rows(items, empty, render) {
  if (!items.length) return node("p", "home-meta", empty);
  const list = node("ul", "home-rows");
  for (const item of items) {
    const row = node("li");
    row.append(...render(item));
    list.append(row);
  }
  return list;
}

function detailLink(label, href) {
  const link = node("a", "home-link", label);
  link.href = href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
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

export function createHome({ api, openView, openWeatherSettings, openFile, openPanelChat, openDemo, onData }) {
  const section = get("home-view");
  const grid = get("home-grid");
  const edit = get("home-edit");
  const feedback = get("home-feedback");
  const restored = get("home-removed");
  const removedItems = get("home-removed-items");
  const settingsForm = get("weather-settings-form");
  const location = get("weather-location");
  const settingsStatus = get("weather-settings-status");
  const settingsSave = get("weather-location-save");
  const desktop = matchMedia("(min-width: 761px) and (pointer: fine)");
  let snapshot;
  let editing = false;
  let request = 0;
  let settingsRequest = 0;
  let moving = false;
  let dragged;
  let hovered;
  let signature;
  let dayFormat, timeFormat, dateTimeFormat, compactDateTime, dateKey;
  const pending = new Set();

  const titleFor = (id) => builtIns[id]?.title || snapshot.panels[id]?.title;
  const visible = () => snapshot.layout.order.filter((id) => !snapshot.layout.hidden.includes(id));
  const setFeedback = (message = "") => { feedback.textContent = message; };

  async function load() {
    const sequence = ++request;
    try {
      const data = await api("/api/home", undefined, AbortSignal.timeout(15000));
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
      timeFormat = new Intl.DateTimeFormat(undefined, { ...standardTime, timeZone: data.timezone });
      dateTimeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: data.timezone });
      compactDateTime = new Intl.DateTimeFormat(undefined, {
        ...standardTime, month: "short", day: "numeric", timeZone: data.timezone,
      });
      dateKey = dailyDate(data.timezone);
      render();
    } catch (error) {
      if (sequence === request && !section.hidden) setFeedback(error.message);
    }
  }

  const wallClock = new Intl.DateTimeFormat(undefined, { ...standardTime, timeZone: "UTC" });
  const quietTime = (value) => wallClock.format(new Date(`2000-01-01T${value}:00Z`));
  const pendingTime = (value) => timeElement(value, dateTimeFormat.format(new Date(value)));
  const reminderTime = (value) => {
    const stamp = new Date(value);
    const formatter = dateKey.format(stamp) === dateKey.format(new Date()) ? timeFormat : compactDateTime;
    return timeElement(value, formatter.format(stamp));
  };
  const activityTime = (value) => {
    const stamp = new Date(value);
    const label = dateKey.format(stamp) === dateKey.format(new Date()) ? timeFormat.format(stamp)
      : new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", timeZone: snapshot.timezone }).format(stamp);
    return timeElement(value, label);
  };

  function dotLabel(label, state) {
    const badge = node("span", `home-status is-${state}`);
    badge.append(node("span", "home-dot"), node("span", "", label));
    return badge;
  }

  function builtinBody(id, data) {
    const body = node("div", "home-card-body");
    if (id === "today") {
      const quiet = node("div", "home-quiet");
      const title = data.quiet_until ? "Quiet hours active" : data.quiet_enabled ? "Quiet hours off now" : "Quiet hours disabled";
      quiet.append(icon("moon", 18), node("strong", "", title));
      if (data.quiet_until) quiet.append(node("span", "", `Until ${timeFormat.format(new Date(data.quiet_until))}`));
      else if (data.quiet_enabled) quiet.append(node("span", "", `${quietTime(data.quiet_start)}–${quietTime(data.quiet_end)}`));
      body.append(quiet, node("p", "home-list-heading", "Next reminders"),
        rows(data.jobs, "No upcoming reminders.", (item) => [reminderTime(item.at), node("span", "", item.message)]));
    } else if (id === "inbox") {
      body.append(labelCount(data.count, "item to review", "items to review"),
        rows(data.items, "You’re caught up.", (item) => [node("span", "home-bullet"), node("span", "", item.title)]));
    } else if (id === "files") {
      body.append(rows(data.items, "No files saved yet.", (item) => {
        const open = node("button", "home-file");
        open.type = "button";
        open.setAttribute("aria-haspopup", "dialog");
        open.dataset.control = `file-${item.id}`;
        open.append(node("span", "home-format", item.format.toUpperCase()), node("span", "", item.title));
        open.addEventListener("click", () => openFile(item.id, open));
        return [open];
      }));
    } else if (id === "memory") {
      body.append(labelCount(data.count, "note in memory", "notes in memory"));
      const status = node("p", "home-detail");
      const pinecone = data.pinecone;
      const tone = /error|failed|unavailable/i.test(pinecone) ? "error" : /^(ready|connected|synced)$/i.test(pinecone) ? "ok" : "neutral";
      status.append(node("span", "", "Pinecone"), dotLabel(pinecone, tone));
      body.append(status);
      if (data.record_count != null) {
        const records = node("p", "home-detail");
        records.append(node("span", "", "Indexed records"), node("span", "", data.record_count.toLocaleString()));
        body.append(records);
      }
      const sync = node("p", "home-detail");
      sync.append(node("span", "", "Last synced"), data.last_sync ? pendingTime(data.last_sync) : node("span", "", "Never"));
      body.append(sync);
    } else if (id === "activity") {
      body.append(labelCount(data.count, "event today", "events today"));
      if (data.errors) body.append(node("p", "home-error", `${data.errors} ${data.errors === 1 ? "error" : "errors"} today`));
      body.append(rows(data.items, "No activity yet.", (item) => [activityTime(item.at), node("span", "", item.title)]));
    } else if (id === "connections") {
      if (data.error) body.append(node("p", "home-error", data.error));
      body.append(rows(data.items, "No configured connectors.", (item) => [
        node("span", "", item.name),
        dotLabel(item.ok ? item.state || "OK" : "Error", item.state === "Connecting" ? "neutral" : item.ok ? "ok" : "error"),
      ]));
    } else if (id === "weather") {
      const pair = node("div", "home-weather");
      const clock = node("div", "");
      const now = node("time", "home-weather-value");
      now.id = "home-clock";
      clock.append(now, node("p", "home-meta", "Pacific time"));
      const forecast = node("div", "");
      forecast.append(node("p", "home-location", data.name));
      if (data.value) forecast.append(node("p", "home-weather-value", `${data.value.temperature}°F`),
        node("p", "home-meta", weatherLabel(data.value.code)));
      else forecast.append(node("p", "home-meta", data.error ? "No weather data" : "Fetching weather…"));
      pair.append(clock, forecast);
      body.append(pair);
    }
    return body;
  }

  function checklist(row) {
    const canCheck = row.source.type === "static";
    return rows(row.value, "No items yet.", (item) => {
      const label = node("label", "home-check");
      const check = node("input");
      const index = row.value.indexOf(item);
      check.type = "checkbox";
      check.checked = item.checked;
      check.disabled = !canCheck;
      check.dataset.control = `check-${index}`;
      check.addEventListener("click", (event) => {
        if (pending.has(row.id)) event.preventDefault();
      });
      check.addEventListener("change", () => {
        mutate(row.id, "checklist", { index, checked: check.checked, revision: row.revision }, check);
      });
      label.append(check, node("span", "", item.text));
      return [label];
    });
  }

  function customBody(row) {
    const body = node("div", "home-card-body");
    if (row.value === null) {
      body.append(node("p", "home-meta", row.error ? "No saved value." : "Waiting for the first refresh…"));
    } else if (row.kind === "stat") {
      body.append(node("p", "home-stat", typeof row.value === "number" ? number.format(row.value) : row.value));
    } else if (row.kind === "countdown") {
      const timer = node("p", "home-stat");
      timer.dataset.countdown = row.value;
      body.append(timer, node("p", "home-meta", row.value.length === 10
        ? new Intl.DateTimeFormat(undefined, { ...calendar, timeZone: "UTC" }).format(new Date(row.value))
        : dateTimeFormat.format(new Date(row.value))));
    } else if (row.kind === "checklist") {
      body.append(checklist(row));
    } else if (row.kind === "list") {
      body.append(rows(row.value, "No items yet.", (item) => [node("span", "home-bullet"), node("span", "", item)]));
    } else {
      body.append(node("p", "home-note", row.value));
    }
    return body;
  }

  function updateClocks() {
    if (!snapshot || section.hidden) return;
    const now = new Date();
    get("home-date").textContent = dayFormat.format(now);
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

  function sourceFooter(id, row, kind) {
    const footer = node("footer", "home-footer");
    if (row.error && (id === "weather" || !kind)) {
      footer.append(node("p", "home-error", row.value === null ? row.error : `Showing last value. ${row.error}`));
    }
    const links = node("div", "home-card-links");
    if (kind) {
      links.append(control(kind.link, () => kind.page === "weather" ? openWeatherSettings() : openView(kind.page)));
    } else if (row.source.type === "url" && /^https?:\/\//.test(row.source.url)) {
      links.append(detailLink("Open source", row.source.url));
    } else if (row.source.type === "connector") {
      links.append(control("Open Connections", () => openView("connections")));
    }
    const ask = control("Ask about this", async () => {
      ask.disabled = true;
      try { await openPanelChat(id); }
      catch (error) { setFeedback(error.message); }
      finally { ask.disabled = false; }
    }, "message");
    ask.dataset.control = "ask";
    links.append(ask);
    footer.append(links);
    if (id === "weather" || !kind) {
      const status = node("div", "home-refresh-row");
      const stamp = row.updated_at ? timeElement(row.updated_at, updatedLabel(row.updated_at))
        : node("span", "", row.error ? "Refresh failed" : "Waiting for update");
      if (row.updated_at) {
        stamp.dataset.updated = "";
        stamp.title = dateTimeFormat.format(new Date(row.updated_at));
      }
      const refresh = iconButton("refresh", `Refresh ${titleFor(id)}`, () => mutate(id, "refresh", {}, refresh), "home-icon-button");
      refresh.dataset.control = "refresh";
      refresh.disabled = pending.has(id);
      status.append(stamp);
      if (id === "weather") status.append(detailLink("Open-Meteo", "https://open-meteo.com/"));
      status.append(refresh);
      footer.append(status);
    }
    return footer;
  }

  function dragHandle(id, card) {
    const handle = node("span", "home-grip");
    handle.append(icon("grip", 19));
    handle.draggable = true;
    handle.title = `Drag ${titleFor(id)} to reorder`;
    handle.setAttribute("aria-hidden", "true");
    handle.addEventListener("dragstart", (event) => {
      if (moving) return event.preventDefault();
      dragged = id;
      card.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", id);
    });
    handle.addEventListener("dragend", clearDrag);
    card.addEventListener("dragover", (event) => {
      if (!dragged || dragged === id) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      if (hovered !== card) {
        hovered?.classList.remove("is-drop-target");
        hovered = card;
        card.classList.add("is-drop-target");
      }
    });
    card.addEventListener("drop", (event) => {
      if (!dragged || dragged === id) return;
      event.preventDefault();
      const source = dragged;
      const order = visible();
      clearDrag();
      adjust(source, "move", { target: id, position: order.indexOf(source) < order.indexOf(id) ? "after" : "before" });
    });
    return handle;
  }

  function clearDrag() {
    grid.querySelector(".is-dragging")?.classList.remove("is-dragging");
    hovered?.classList.remove("is-drop-target");
    hovered = undefined;
    dragged = undefined;
  }

  function layoutTools(id, order) {
    const tools = node("div", "home-order-tools");
    const at = order.indexOf(id);
    for (const [direction, offset, position] of [["up", -1, "before"], ["down", 1, "after"]]) {
      const target = order[at + offset];
      const move = iconButton(`arrow-${direction}`, `Move ${titleFor(id)} ${direction}`,
        () => adjust(id, "move", { target, position }, direction), "home-icon-button");
      move.dataset.control = direction;
      move.disabled = !target;
      tools.append(move);
    }
    const remove = iconButton("x", `Remove ${titleFor(id)} from Home`, () => adjust(id, "hide"), "home-icon-button");
    tools.append(remove);
    return tools;
  }

  function card(id, order) {
    const kind = builtIns[id];
    const row = kind ? snapshot.builtin[id] : snapshot.panels[id];
    const element = node("article", `home-card home-card-${kind ? id : row.kind}`);
    element.dataset.panel = id;
    const header = node("header", "home-card-header");
    const mark = node("span", "home-card-icon");
    mark.append(icon(kind?.icon || kindIcons[row.kind], 19));
    const heading = node("h2", "", titleFor(id));
    heading.id = `home-panel-${id}`;
    element.setAttribute("aria-labelledby", heading.id);
    header.append(mark, heading);
    if (editing) header.append(layoutTools(id, order));
    if (desktop.matches) header.append(dragHandle(id, element));
    element.append(header, kind ? builtinBody(id, row) : customBody(row), sourceFooter(id, row, kind));
    return element;
  }

  function render() {
    if (!snapshot || section.hidden) return;
    const active = document.activeElement;
    const panel = active.closest("[data-panel]")?.dataset.panel;
    const key = active.dataset.control;
    const order = visible();
    grid.replaceChildren(...order.map((id) => card(id, order)));
    grid.classList.toggle("is-editing", editing);
    get("home-loading").hidden = true;
    get("home-empty").hidden = order.length > 0;
    get("home-demo").hidden = snapshot.model !== "mock" || Object.keys(snapshot.panels).length > 0;
    edit.disabled = false;
    edit.setAttribute("aria-pressed", String(editing));
    get("home-edit-label").textContent = editing ? "Done" : "Edit layout";
    restored.hidden = !editing || !snapshot.layout.hidden.length;
    removedItems.replaceChildren(...snapshot.layout.hidden.map((id) => {
      const row = node("li", "home-removed-row");
      row.append(node("span", "", titleFor(id)), control("Restore", () => adjust(id, "restore"), "plus"));
      return row;
    }));
    if (panel && key) grid.querySelector(`[data-panel="${CSS.escape(panel)}"] [data-control="${CSS.escape(key)}"]`)?.focus();
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
        edit.focus();
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

  async function settings() {
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
  return { load, settings };
}
