import { icon, iconButton } from "./icons.js";
import { DEFAULT_TIME_ZONE, timeFormatter } from "./time.js";

const get = (id) => document.getElementById(id);
const policyOptions = [["ask", "Always ask"], ["allow", "Allow without asking"]];
const labels = { send: "Send messages", spend: "Spend money", public: "Publish publicly", destructive: "Delete items" };
const marks = { send: "mail", spend: "clock", public: "share", destructive: "trash" };
const statuses = {
  pending: "Needs approval", expired: "Expired", declined: "Declined", changing: "Execution unconfirmed",
  complete: "Completed", sent: "Sent", simulated: "Simulated", failed: "Failed", request_unknown: "Outcome unconfirmed",
  partial: "Partially applied", running: "Running", retrying: "Retry scheduled", approval_needed: "Needs approval",
};
const delivery = [["app", "In app"], ["email", "Email"], ["both", "Both"]];
const scheduleTypes = ["Once", "Daily", "Weekly", "Interval", "Cron"];
const weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const editLabels = { subject: "Subject", text: "Message", body: "Request body (JSON)" };

function el(tag, className = "", content) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (content !== undefined) element.textContent = content;
  return element;
}

function button(label, glyph, handler, className = "") {
  const item = iconButton(glyph, label, handler, `automation-button ${className}`);
  item.append(el("span", "", label));
  return item;
}

let labelId = 0;

function label(text, input, className = "") {
  const element = el("label", className);
  const caption = el("span", "", text);
  caption.id = `automation-label-${++labelId}`;
  input.setAttribute("aria-labelledby", caption.id);
  element.append(caption, input);
  return element;
}

function select(name, options, value) {
  const input = el("select");
  input.name = name;
  for (const [key, text] of options) {
    const option = el("option", "", text);
    option.value = key;
    input.append(option);
  }
  input.value = value;
  return input;
}

function input(name, type, value, limit) {
  const element = el("input");
  element.name = name;
  element.type = type;
  element.value = value;
  if (limit) element.maxLength = limit;
  return element;
}

const dateOptions = { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" };
const workspaceDate = timeFormatter(dateOptions);

function date(value, zone) {
  const formatter = zone ? new Intl.DateTimeFormat(undefined, { ...dateOptions, timeZone: zone }) : workspaceDate;
  return formatter.format(new Date(value));
}

function dateInput(value, zone) {
  if (!value) return "";
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: zone, hourCycle: "h23",
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
    .formatToParts(new Date(value));
  const pieces = Object.fromEntries(parts.map(({ type, value: field }) => [type, field]));
  return `${pieces.year}-${pieces.month}-${pieces.day}T${pieces.hour}:${pieces.minute}`;
}

function times(values, zone) {
  const list = el("ol", "automation-times");
  for (const value of values) {
    const time = el("time", "", date(value, zone));
    time.dateTime = value;
    const item = el("li");
    item.append(time);
    list.append(item);
  }
  return list;
}

function dataField(list, name, value) {
  if (value === null || value === undefined || value === "") return;
  list.append(el("dt", "", name), el("dd", "", value));
}

function pill(status, text = statuses[status] || status) {
  return el("span", `automation-state automation-state-${status}`, text);
}

function summary(title, glyph, status) {
  const head = el("div", "automation-card-heading");
  const mark = el("span", "automation-mark");
  mark.append(icon(glyph, 19));
  head.append(mark, el("h3", "", title), status);
  return head;
}

export function createAutomation({ api, refresh, openThread, undo }) {
  const dialog = get("automation-dialog");
  let dialogTrigger;
  let activeTab = "reminders";
  let selected;
  let taskSignature;
  let taskRequest = 0;
  let deleting;
  let inboxSignature;
  let homeSignature;
  const takingAction = new Set();

  dialog.addEventListener("close", () => {
    if (dialogTrigger?.isConnected) dialogTrigger.focus();
    else if (get("new-task").checkVisibility()) get("new-task").focus();
    dialogTrigger = undefined;
  });

  function openDialog(title, trigger) {
    dialogTrigger = trigger;
    const head = el("header", "automation-dialog-header");
    const heading = el("h2", "", title);
    heading.id = "automation-dialog-title";
    head.append(heading, iconButton("x", "Close", () => dialog.close()));
    dialog.replaceChildren(head);
    dialog.showModal();
  }

  async function decision(row, verb, card, changes) {
    if (takingAction.has(row.id)) return;
    takingAction.add(row.id);
    const feedback = card.querySelector("[role=status]");
    const controls = [...card.querySelectorAll("button")];
    for (const control of controls) control.disabled = true;
    try {
      const result = await api(`/api/approvals/${verb}`, { id: row.id, ...(changes ? { changes } : {}) });
      if (deleting?.id === row.id) deleting = result;
      if (dialog.open) dialog.close();
      if (card.isConnected) card.replaceWith(approvalCard(result, card.dataset.surface));
      await refresh();
    } catch (error) {
      feedback.textContent = error.message;
      throw error;
    } finally {
      takingAction.delete(row.id);
      for (const control of controls) control.disabled = false;
      for (const updated of document.querySelectorAll(`[data-approval-id="${row.id}"] button`)) updated.disabled = false;
    }
  }

  function edit(row, card, trigger) {
    openDialog("Edit approval", trigger);
    const form = el("form", "automation-editor");
    const feedback = el("p", "meta", "");
    feedback.setAttribute("role", "status");
    for (const [key, value] of Object.entries(row.editable)) {
      const field = key === "subject" ? input(key, "text", value, 240) : el("textarea");
      field.name = key;
      field.value = value;
      field.required = true;
      form.append(label(editLabels[key], field));
    }
    const save = el("button", "primary-setting", "Save changes");
    save.type = "submit";
    form.append(save, feedback);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      save.disabled = true;
      try {
        await decision(row, "edit", card, Object.fromEntries(new FormData(form)));
      } catch (error) {
        feedback.textContent = error.message;
      } finally {
        save.disabled = false;
      }
    });
    dialog.append(form);
    form.elements[0].focus();
  }

  function approvalCard(row, surface = "chat") {
    const article = el("article", "card automation-approval");
    article.dataset.approvalId = row.id;
    article.dataset.surface = surface;
    const confirmation = row.tool === "create_recurring_task";
    const status = row.status === "pending" && Date.parse(row.expires_at) <= Date.now() ? "expired" : row.status;
    const category = row.categories[0];
    article.append(summary(row.title, confirmation ? "clock" : marks[category] || "shield",
      pill(status, status === "pending" && confirmation ? "Confirm schedule" : undefined)));
    const fields = el("dl", "automation-fields");
    if (row.email) {
      dataField(fields, "To", row.email.to.join(", "));
      dataField(fields, "Subject", row.email.subject);
      dataField(fields, "Message", row.email.text);
    } else if (!confirmation) {
      dataField(fields, "Target", row.target);
      if (row.categories.includes("spend")) dataField(fields, "Estimated cost", row.amount);
      if (row.steps?.length) dataField(fields, "Steps", row.steps.map(({ action, target, text }) =>
        [action, target, text].filter(Boolean).join(" ")).join("\n"));
      if (row.request?.body != null) dataField(fields, "Request", JSON.stringify(row.request.body, null, 2));
    }
    if (fields.childElementCount) article.append(fields);
    if (confirmation) {
      article.append(el("p", "automation-instruction", row.args.instruction),
        el("p", "automation-label", "Upcoming runs"), times(row.upcoming, row.args.timezone));
    }
    const result = row.result;
    if (result?.message || result?.error) article.append(el("p", "automation-result", result.message || result.error));
    if (result?.response || result?.message_id || result?.text) {
      const details = el("details", "automation-result-details");
      details.append(el("summary", "", "Tool result"), el("pre", "", result.response ?
        JSON.stringify(result.response, null, 2) : result.text || result.message_id));
      article.append(details);
    }
    const footer = el("div", "automation-card-footer");
    footer.append(el("span", "meta", status === "pending" ? `Expires ${date(row.expires_at)}` : ""));
    const controls = el("div", "automation-controls");
    if (status === "pending") {
      controls.append(button(confirmation ? "Confirm" : "Approve", "check",
        () => decision(row, "approve", article).catch(() => {}), "primary-setting"));
      if (Object.keys(row.editable || {}).length) {
        controls.append(button("Edit", "edit", (event) => edit(row, article, event.currentTarget)));
      }
      controls.append(button("Decline", "x", () => decision(row, "decline", article).catch(() => {})));
    }
    if (row.undo_task && !row.undone) controls.append(button("Undo", "history", () => undo(row)));
    if (row.effect_action && ["memory_write", "delete_memory"].includes(row.tool) && !row.effect_undone) {
      controls.append(button("Undo", "history", () => undo({ id: row.effect_action, memory_change: true })));
    }
    if (surface !== "chat" && row.thread_id) {
      controls.append(button("Open chat", "message", () => openThread(row.thread_id)));
    }
    footer.append(controls);
    article.append(footer);
    const feedback = el("p", "meta automation-feedback", "");
    feedback.setAttribute("role", "status");
    article.append(feedback);
    return article;
  }

  function approvalGroup(target, items, surface) {
    target.hidden = !items.length;
    target.replaceChildren();
    if (!items.length) return;
    const count = items.filter((item) => item.status === "pending").length;
    const title = el("div", "automation-section-heading");
    title.append(icon("shield", 20), el("h2", "", surface === "home" ? "Pending approvals" : "Approvals"), pill("pending", String(count)));
    target.append(title);
    const list = el("div", "automation-approval-list");
    list.append(...items.map((row) => approvalCard(row, surface)));
    target.append(list);
  }

  function home(items) {
    const signature = JSON.stringify(items);
    if (signature === homeSignature) return;
    homeSignature = signature;
    approvalGroup(get("home-approvals"), items, "home");
  }

  function inbox(items, approvals) {
    const signature = JSON.stringify([approvals, items]);
    if (signature === inboxSignature) return;
    inboxSignature = signature;
    approvalGroup(get("inbox-approvals"), approvals, "inbox");
    const target = get("inbox-runs");
    target.hidden = !items.length;
    target.replaceChildren();
    if (!items.length) return;
    const title = el("div", "automation-section-heading");
    title.append(icon("clock", 20), el("h2", "", "Recurring task updates"));
    const list = el("div", "automation-approval-list");
    for (const row of items) {
      const card = el("article", "card automation-approval");
      card.append(summary(row.title, "clock", pill(row.status)), el("p", "automation-result", row.text),
        el("p", "meta", date(row.created_at)));
      if (row.email_state === "failed") card.append(el("p", "meta", row.email_reason));
      card.append(button("Open chat", "message", () => openThread(row.thread_id)));
      list.append(card);
    }
    target.append(title, list);
  }

  const policies = get("approval-policies");
  for (const [key, phrase] of Object.entries(labels)) policies.append(label(phrase, select(key, policyOptions, "ask")));
  const settingsForm = get("approval-settings-form");
  const settingsStatus = get("approval-settings-feedback");
  async function settings() {
    try {
      const policy = await api("/api/approvals/settings");
      for (const key of Object.keys(labels)) settingsForm.elements[key].value = policy[key];
    } catch (error) {
      settingsStatus.textContent = error.message;
    }
  }
  settingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/approvals/settings", Object.fromEntries(new FormData(settingsForm)));
      settingsStatus.textContent = "Settings saved.";
    } catch (error) {
      settingsStatus.textContent = error.message;
    }
  });

  function scheduleText(schedule) {
    if (schedule.type === "weekly") return `${schedule.days.map((day) => weekdays[day]).join(", ")} at ${schedule.time}`;
    if (schedule.type === "daily") return `Daily at ${schedule.time}`;
    if (schedule.type === "interval") return `Every ${schedule.minutes} min`;
    if (schedule.type === "cron") return schedule.cron;
    return "One time";
  }

  function editor(task, trigger) {
    openDialog(task ? "Edit recurring task" : "New recurring task", trigger);
    const form = el("form", "automation-editor");
    const name = input("name", "text", task?.name || "", 80);
    name.required = true;
    const instruction = el("textarea");
    instruction.name = "instruction";
    instruction.value = task?.instruction || "";
    instruction.maxLength = 4000;
    instruction.required = true;
    const zone = input("timezone", "text", task?.timezone || DEFAULT_TIME_ZONE, 80);
    zone.required = true;
    const type = select("type", scheduleTypes.map((type) => [type.toLowerCase(), type]), task?.schedule.type || "daily");
    const channel = select("delivery", delivery, task?.delivery || "app");
    const fields = el("div", "automation-editor-fields");
    const dynamic = el("div", "automation-schedule-fields");
    const schedule = task?.schedule || {};
    const at = input("at", "datetime-local", dateInput(schedule.at, zone.value));
    const time = input("time", "time", schedule.time || "08:00");
    const minutes = input("minutes", "number", schedule.minutes || 60);
    minutes.min = 1;
    minutes.max = 525600;
    const cron = input("cron", "text", schedule.type === "cron" ? schedule.cron : "", 100);
    cron.placeholder = "0 8 * * 1-5";
    const days = el("fieldset", "automation-weekdays");
    days.append(el("legend", "", "Days"));
    const toggles = weekdays.map((day, index) => {
      const checkbox = input("days", "checkbox", index);
      checkbox.checked = (schedule.days || [1, 2, 3, 4, 5]).includes(index);
      days.append(label(day, checkbox));
      return checkbox;
    });
    const enabled = input("enabled", "checkbox", "true");
    enabled.checked = task?.enabled ?? true;
    const preview = el("div", "automation-preview");
    const feedback = el("p", "meta");
    feedback.setAttribute("role", "status");
    const controls = el("div", "automation-controls");
    const submit = el("button", "primary-setting", "Preview schedule");
    submit.type = "submit";
    controls.append(submit);
    let reviewed = false;
    function showFields() {
      const mode = type.value;
      const [text, field] = { once: ["Date and time", at], daily: ["Local time", time], weekly: ["Local time", time],
        interval: ["Minutes between runs", minutes], cron: ["Five-field cron", cron] }[mode];
      field.required = true;
      dynamic.replaceChildren(label(text, field));
      if (mode === "weekly") dynamic.append(days);
    }
    form.addEventListener("input", () => {
      reviewed = false;
      preview.replaceChildren();
      feedback.textContent = "";
      submit.textContent = "Preview schedule";
    });
    type.addEventListener("change", showFields);
    showFields();
    fields.append(label("Schedule", type), label("Time zone", zone), dynamic, label("Delivery", channel));
    form.append(label("Name", name), label("Instruction", instruction), fields, label("Enabled", enabled, "automation-enabled"),
      preview, controls, feedback);
    dialog.append(form);
    name.focus();
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const mode = type.value;
      const details = {
        once: { at: at.value }, daily: { time: time.value },
        weekly: { time: time.value, days: toggles.flatMap((item, index) => item.checked ? [index] : []) },
        interval: { minutes: Number(minutes.value) }, cron: { cron: cron.value },
      }[mode];
      if (mode === "once" && schedule.at && at.value === dateInput(schedule.at, task.timezone) && zone.value === task.timezone) {
        details.at = schedule.at;
      }
      const data = { ...(task ? { id: task.id } : {}), name: name.value, instruction: instruction.value,
        timezone: zone.value, enabled: enabled.checked, delivery: channel.value, schedule: { type: mode, ...details } };
      submit.disabled = true;
      try {
        if (!reviewed) {
          const result = await api("/api/tasks/preview", data);
          preview.replaceChildren(el("p", "automation-label", "Upcoming runs"),
            result.upcoming.length ? times(result.upcoming, result.timezone) : el("p", "meta", "No upcoming runs."));
          reviewed = true;
          submit.textContent = "Save task";
        } else {
          const result = await api(`/api/tasks/${task ? "update" : "create"}`, data);
          selected = result.id;
          dialog.close();
          await loadTasks();
        }
      } catch (error) {
        feedback.textContent = error.message;
      } finally {
        submit.disabled = false;
      }
    });
  }

  function taskDetail(task) {
    const article = el("article", "card automation-task-detail");
    const running = task.manual_due || task.runs.some((run) => ["running", "retrying"].includes(run.status));
    const controls = el("div", "automation-controls automation-task-controls");
    const run = button("Run now", "play", () => taskAction(task, "run"), "primary-setting");
    run.disabled = !!running;
    controls.append(run, button(task.enabled ? "Pause" : "Resume", task.enabled ? "pause" : "play",
      () => taskAction(task, task.enabled ? "pause" : "update", task.enabled ? {} : { enabled: true })),
    button("Edit", "edit", (event) => editor(task, event.currentTarget)),
    button("Delete", "trash", () => taskAction(task, "delete")));
    article.append(summary(task.name, "clock", pill(task.enabled ? "complete" : "changing", task.enabled ? "Enabled" : "Paused")),
      el("p", "automation-instruction", task.instruction), controls);
    const fields = el("dl", "automation-fields");
    dataField(fields, "Schedule", scheduleText(task.schedule));
    dataField(fields, "Next run", task.next_run ? date(task.next_run, task.timezone) : "—");
    dataField(fields, "Time zone", task.timezone);
    dataField(fields, "Delivery", delivery.find(([key]) => key === task.delivery)?.[1]);
    article.append(fields);
    const history = el("div", "automation-history");
    const header = el("div", "automation-section-heading");
    header.append(el("h4", "", "Run history"));
    if (task.chat_id) header.append(button("Open chat", "message", () => openThread(task.chat_id)));
    history.append(header);
    if (task.runs.length === 0) history.append(el("p", "meta", running ? "Run queued." : "No runs yet."));
    for (const run of task.runs) {
      const item = el("details", "automation-run");
      const heading = el("summary");
      heading.append(icon("chevron", 15), el("span", "automation-run-time", date(run.started_at, task.timezone)), pill(run.status));
      const details = el("div", "automation-run-body");
      if (run.output) details.append(el("p", "automation-result", run.output));
      if (run.reason) details.append(el("p", "automation-result", run.reason));
      const metadata = [run.duration_ms !== undefined ? `${(run.duration_ms / 1000).toFixed(1)} s` : "",
        `${run.attempts} attempt${run.attempts === 1 ? "" : "s"}`].filter(Boolean);
      details.append(el("p", "meta", metadata.join(" · ")));
      if (run.tools?.length) details.append(el("p", "meta", run.tools.map((tool) => `${tool.tool} · ${statuses[tool.status]}`).join(", ")));
      item.append(heading, details);
      history.append(item);
    }
    article.append(history);
    return article;
  }

  async function taskAction(task, verb, extra = {}) {
    const feedback = get("tasks-feedback");
    try {
      const result = await api(`/api/tasks/${verb}`, { id: task.id, ...extra });
      feedback.textContent = verb === "run" ? "Run requested." : "";
      if (verb === "delete") {
        deleting = result.action;
        get("task-approval").replaceChildren(approvalCard(deleting, "tasks"));
      }
      await loadTasks();
    } catch (error) {
      feedback.textContent = error.message;
    }
  }

  async function loadTasks() {
    const request = ++taskRequest;
    try {
      const result = await api("/api/tasks");
      if (request !== taskRequest || activeTab !== "tasks") return;
      if (deleting?.undo_task && !deleting.undone && result.tasks.some((row) => row.id === deleting.undo_task)) {
        deleting = { ...deleting, undone: true };
        get("task-approval").replaceChildren(approvalCard(deleting, "tasks"));
      }
      const task = result.tasks.find(({ id }) => id === selected) || result.tasks[0];
      selected = task?.id;
      const signature = JSON.stringify([selected, result.tasks.map(({ upcoming, ...row }) => row)]);
      if (signature === taskSignature) return;
      taskSignature = signature;
      const host = get("tasks-content");
      const expanded = new Set([...host.querySelectorAll(".automation-run[open] .automation-run-time")].map((row) => row.textContent));
      const list = el("div", "automation-task-list");
      for (const row of result.tasks) {
        const entry = button(row.name, "clock", () => { selected = row.id; loadTasks(); }, "automation-task-selector");
        entry.setAttribute("aria-pressed", String(row.id === selected));
        entry.append(el("small", "meta", row.enabled ? scheduleText(row.schedule) : "Paused"));
        list.append(entry);
      }
      host.replaceChildren(list);
      if (task) host.append(taskDetail(task));
      else host.append(el("p", "meta", "No recurring tasks yet."));
      for (const row of host.querySelectorAll(".automation-run")) {
        row.open = expanded.has(row.querySelector(".automation-run-time").textContent);
      }
    } catch (error) {
      get("tasks-feedback").textContent = error.message;
    }
  }

  function chooseTab(tab, focus = false) {
    activeTab = tab;
    for (const name of ["reminders", "tasks"]) {
      const control = get(`${name}-tab`);
      control.setAttribute("aria-selected", String(name === tab));
      control.tabIndex = name === tab ? 0 : -1;
      get(`${name}-panel`).hidden = name !== tab;
      if (focus && name === tab) control.focus();
    }
    refresh();
  }

  for (const name of ["reminders", "tasks"]) {
    const tab = get(`${name}-tab`);
    tab.addEventListener("click", () => chooseTab(name));
    tab.addEventListener("keydown", (event) => {
      const target = { ArrowLeft: name === "tasks" ? "reminders" : "tasks",
        ArrowRight: name === "tasks" ? "reminders" : "tasks", Home: "reminders", End: "tasks" }[event.key];
      if (!target) return;
      event.preventDefault();
      chooseTab(target, true);
    });
  }
  get("new-task").addEventListener("click", (event) => editor(null, event.currentTarget));
  return { approvalCard, home, inbox, settings, loadTasks, tasksActive: () => activeTab === "tasks" };
}
