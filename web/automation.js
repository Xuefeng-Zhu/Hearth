import { icon, iconButton } from "./icons.js";
import { DEFAULT_TIME_ZONE, timeFormatter } from "./time.js";

const get = (id) => document.getElementById(id);
const policyOptions = [["ask", "Always ask"], ["allow", "Allow without asking"]];
const labels = { send: "Send messages", spend: "Spend money", public: "Publish publicly", destructive: "Delete items", skills: "Skills", goals: "Create goals" };
const marks = { send: "mail", spend: "clock", public: "share", destructive: "trash", skills: "skill", goals: "activity" };
const statuses = {
  pending: "Needs approval", expired: "Expired", declined: "Declined", cancelled: "Stopped", changing: "Execution unconfirmed",
  complete: "Completed", sent: "Sent", simulated: "Simulated", failed: "Failed", request_unknown: "Outcome unconfirmed",
  partial: "Partially applied", skipped: "Skipped", queued: "Queued", rate_limited: "Hourly limit reached", running: "Running", retrying: "Retry scheduled", approval_needed: "Needs approval",
};
const delivery = [["app", "In app"], ["email", "Email"], ["both", "Both"]];
const scheduleTypes = ["Once", "Daily", "Weekly", "Interval", "Cron"];
const weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const triggerTypes = [["email", "Incoming email"], ["reminder", "Reminder fires"],
  ["feed", "Feed card appears"], ["schedule", "Schedule"]];
const actionTypes = [["prompt", "Run a prompt"], ["save_attachments", "Save email attachments"],
  ["reminder", "Create an in-app reminder"], ["email_summary", "Email the summary"], ["feed_card", "Add a Feed card"]];
const feedKinds = { read: "Read", idea: "Idea", digest: "Digest", "reminder-context": "Reminder",
  action: "Action", "memory-review": "Memory review", automation: "Automation" };
const actionLabel = (type) => actionTypes.find(([key]) => type === key)?.[1] || type;
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

export function createAutomation({ api, refreshAPI, refresh, openThread, openInbox, undo }) {
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
    else if (!get("settings-automations").hidden) get("new-event-automation").focus();
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
      if (eventDeletion?.id === row.id) eventDeletion = result;
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
    const eventConfirmation = row.tool === "create_event_automation";
    const taskConfirmation = row.tool === "create_recurring_task";
    const confirmation = eventConfirmation || taskConfirmation;
    const status = row.status === "pending" && Date.parse(row.expires_at) <= Date.now() ? "expired" : row.status;
    const category = row.categories[0];
    article.append(summary(row.title, confirmation ? "clock" : marks[category] || "shield",
      pill(status, status === "pending" && confirmation ? (eventConfirmation ? "Confirm automation" : "Confirm schedule") : undefined)));
    if (row.worker_title) article.append(el("p", "thread-source", `Worker · ${row.worker_title}`));
    const fields = el("dl", "automation-fields");
    if (row.email) {
      dataField(fields, "To", row.email.to.join(", "));
      dataField(fields, "Subject", row.email.subject);
      dataField(fields, "Message", row.email.text);
    } else if (!confirmation) {
      dataField(fields, "Target", row.target);
      if (row.categories.includes("spend")) dataField(fields, "Estimated cost", row.amount);
      if (row.attachment_names?.length) dataField(fields, "Attachments", row.attachment_names.join("\n"));
      if (row.steps?.length) dataField(fields, "Steps", row.steps.map(({ action, target, text }) =>
        [action, target, text].filter(Boolean).join(" ")).join("\n"));
      if (row.request?.body != null) dataField(fields, "Request", JSON.stringify(row.request.body, null, 2));
    }
    if (row.goal_preview) {
      dataField(fields, "Target date", row.goal_preview.target_date);
      const checkin = row.goal_preview.checkin;
      if (checkin) dataField(fields, "Check-in", `${checkin.cadence === "daily" ? "Daily" :
        ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][checkin.day]} at ${checkin.time}`);
      if (row.goal_preview.links.length) dataField(fields, "Linked items", String(row.goal_preview.links.length));
    }
    if (fields.childElementCount) article.append(fields);
    if (row.upcoming?.length && !taskConfirmation) {
      article.append(el("p", "automation-label", row.tool === "create_watcher" ? "Upcoming checks" : "Reminder time"),
        times(row.upcoming, row.args.task?.timezone));
    }
    if (category === "skills" && row.args?.markdown) {
      const details = el("details", "automation-result-details");
      details.append(el("summary", "", "Review proposed Markdown"), el("pre", "", row.args.markdown));
      article.append(details);
    }
    if (eventConfirmation) article.append(eventDetails(row.args, row.automation_context || eventData));
    if (taskConfirmation) {
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
    if ((row.undo_task || row.undo_automation) && !row.undone) controls.append(button("Undo", "history", () => undo(row)));
    if (row.effect_action && ["memory_write", "delete_memory"].includes(row.tool) && !row.effect_undone) {
      controls.append(button("Undo", "history", () => undo({ id: row.effect_action, memory_change: true })));
    }
    if (!["chat", "idea", "goal"].includes(surface) && row.thread_id) {
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

  function scheduleEditor(schedule = {}, zoneName = DEFAULT_TIME_ZONE) {
    const zone = input("timezone", "text", zoneName, 80);
    zone.required = true;
    const type = select("type", scheduleTypes.map((type) => [type.toLowerCase(), type]), schedule.type || "daily");
    const fields = el("div", "automation-editor-fields");
    const dynamic = el("div", "automation-schedule-fields");
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
    function showFields() {
      const mode = type.value;
      const [text, field] = { once: ["Date and time", at], daily: ["Local time", time], weekly: ["Local time", time],
        interval: ["Minutes between runs", minutes], cron: ["Five-field cron", cron] }[mode];
      field.required = true;
      dynamic.replaceChildren(label(text, field));
      if (mode === "weekly") dynamic.append(days);
    }
    type.addEventListener("change", showFields);
    showFields();
    fields.append(label("Schedule", type), label("Time zone", zone), dynamic);
    return { fields, value() {
      const mode = type.value;
      const details = {
        once: { at: at.value }, daily: { time: time.value },
        weekly: { time: time.value, days: toggles.flatMap((item, index) => item.checked ? [index] : []) },
        interval: { minutes: Number(minutes.value) }, cron: { cron: cron.value },
      }[mode];
      if (mode === "once" && schedule.at && at.value === dateInput(schedule.at, zoneName) && zone.value === zoneName) {
        details.at = schedule.at;
      }
      return { timezone: zone.value, schedule: { type: mode, ...details } };
    } };
  }

  function editor(task, trigger) {
    openDialog(task?.watch ? "Edit watcher" : task ? "Edit recurring task" : "New recurring task", trigger);
    const form = el("form", "automation-editor");
    const name = input("name", "text", task?.name || "", 80);
    name.required = true;
    const instruction = el("textarea");
    instruction.name = "instruction";
    instruction.value = task?.instruction || "";
    instruction.maxLength = 4000;
    instruction.required = true;
    const scheduleUI = scheduleEditor(task?.schedule, task?.timezone);
    const channel = select("delivery", delivery, task?.delivery || "app");
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
    form.addEventListener("input", () => {
      reviewed = false;
      preview.replaceChildren();
      feedback.textContent = "";
      submit.textContent = "Preview schedule";
    });
    scheduleUI.fields.append(label("Delivery", channel));
    form.append(label("Name", name), task?.watch ? el("p", "meta", task.watch.url) : label("Instruction", instruction),
      scheduleUI.fields, label("Enabled", enabled, "automation-enabled"),
      preview, controls, feedback);
    dialog.append(form);
    name.focus();
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = { ...(task ? { id: task.id } : {}), name: name.value, instruction: instruction.value,
        enabled: enabled.checked, delivery: channel.value, ...scheduleUI.value() };
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

  const eventList = get("event-automation-list");
  const eventStatus = get("event-automation-status");
  let eventData;
  let eventSignature;
  let eventDeletion;
  let eventRequest = 0;

  function eventDetails(rule, data = eventData) {
    const { trigger, actions } = rule;
    const fields = el("dl", "automation-fields");
    let when = triggerTypes.find(([key]) => key === trigger.type)?.[1];
    if (trigger.type === "email") {
      const filters = [trigger.sender, trigger.subject && `Subject contains “${trigger.subject}”`,
        trigger.attachment && "Has attachment"].filter(Boolean);
      when = filters.length ? filters.join(" · ") : "Any incoming email";
    } else if (trigger.type === "feed") {
      when += [trigger.kind && feedKinds[trigger.kind], trigger.topic].filter(Boolean).map((value) => ` · ${value}`).join("");
    } else if (trigger.type === "reminder" && trigger.job_id) {
      when = data?.reminders.find(({ id }) => id === trigger.job_id)?.message || `Reminder ${trigger.job_id}`;
    } else if (trigger.type === "schedule") {
      when = trigger.schedule.type === "once" ? date(trigger.schedule.at, trigger.timezone)
        : `${scheduleText(trigger.schedule)} · ${trigger.timezone}`;
    }
    dataField(fields, "When", when);
    dataField(fields, "Then", actions.map((action) => {
      const target = action.thread_id === "new" ? "New side chat" : action.thread_id === "main" ? "Main chat"
        : data?.threads.find(({ id }) => id === action.thread_id)?.title || action.thread_id;
      const detail = {
        prompt: `${target} · ${action.prompt}`,
        save_attachments: action.destination === "box" ? "Box" : "Artifacts",
        reminder: `${action.message} · ${action.delay_minutes} min after this action starts`,
        feed_card: action.title && `${action.title} · ${action.topic}`,
        email_summary: "Reminder address",
      }[action.type];
      return [actionLabel(action.type), detail].filter(Boolean).join(" · ");
    }).join("\n"));
    return fields;
  }

  function eventEditor(rule, trigger) {
    openDialog(rule ? "Edit automation" : "New automation", trigger);
    const form = el("form", "automation-editor event-automation-editor");
    const name = input("name", "text", rule?.name || "", 80);
    name.required = true;
    const when = select("when", triggerTypes, rule?.trigger.type || "email");
    const options = el("div", "event-trigger-fields");
    const actionList = el("div", "event-action-fields");
    const actionReaders = new Map();
    const availableActions = () => actionTypes.filter(([key]) => key !== "save_attachments" || when.value === "email");
    let readTrigger;

    function field(host, labelText, key, value, { type = "text", required = false, limit, min, max } = {}) {
      const control = type === "textarea" ? el("textarea") : input(key, type, value ?? "", limit);
      if (type === "textarea") {
        control.name = key;
        control.value = value ?? "";
        control.maxLength = limit;
      }
      if (type === "checkbox") control.checked = !!value;
      if (type === "number") { control.min = min; control.max = max; }
      control.required = required;
      host.append(label(labelText, control, type === "checkbox" ? "event-checkbox" : ""));
      return control;
    }
    function choose(host, caption, key, values, value) {
      const control = select(key, values, value);
      host.append(label(caption, control));
      return control;
    }
    function displayTrigger(value = {}) {
      const type = when.value;
      options.replaceChildren();
      if (type === "email") {
        const sender = field(options, "From address (optional)", "sender", value.sender, { type: "email", limit: 254 });
        const subject = field(options, "Subject contains (optional)", "subject", value.subject, { limit: 240 });
        const attachment = field(options, "Require an attachment", "attachment", value.attachment, { type: "checkbox" });
        readTrigger = () => ({ type, sender: sender.value.trim(), subject: subject.value.trim(), attachment: attachment.checked });
      } else if (type === "reminder") {
        const choices = [["", "Any reminder"], ...eventData.reminders.map(({ id, message }) => [id, message])];
        if (value.job_id && !choices.some(([id]) => id === value.job_id)) choices.push([value.job_id, "Original reminder"]);
        const job = choose(options, "Reminder", "job", choices, value.job_id || "");
        readTrigger = () => ({ type, job_id: job.value });
      } else if (type === "feed") {
        const kind = choose(options, "Card kind", "kind",
          [["", "Any kind"], ...eventData.feed_kinds.map((key) => [key, feedKinds[key]])], value.kind || "");
        const topic = field(options, "Topic (optional)", "topic", value.topic, { limit: 60 });
        readTrigger = () => ({ type, kind: kind.value, topic: topic.value.trim() });
      } else {
        const schedule = scheduleEditor(value.schedule, value.timezone || eventData.timezone);
        options.append(schedule.fields);
        readTrigger = () => ({ type, ...schedule.value() });
      }
    }
    function addAction(value = { type: "prompt" }) {
      const group = el("fieldset", "event-action");
      const heading = el("legend", "", `Action ${actionReaders.size + 1}`);
      const selectType = select("action", availableActions(), value.type);
      const controls = el("div", "event-action-options");
      const remove = button("Remove action", "x", () => {
        actionReaders.delete(group);
        group.remove();
        updateActions();
        add.focus();
      });
      function show(selection = {}) {
        const type = selectType.value;
        controls.replaceChildren();
        let read = () => ({ type });
        if (type === "prompt") {
          const threads = [["new", "New side chat"], ...eventData.threads.map(({ id, title }) => [id, title])];
          if (selection.thread_id && !threads.some(([id]) => id === selection.thread_id)) {
            threads.push([selection.thread_id, "Original chat"]);
          }
          const thread = choose(controls, "Chat", "thread", threads, selection.thread_id || "new");
          const prompt = field(controls, "Prompt", "prompt", selection.prompt, { type: "textarea", limit: 4000, required: true });
          read = () => ({ type, thread_id: thread.value, prompt: prompt.value });
        } else if (type === "save_attachments") {
          const target = choose(controls, "Save to", "destination", [["artifacts", "Artifacts"], ["box", "Box"]], selection.destination || "artifacts");
          read = () => ({ type, destination: target.value });
        } else if (type === "reminder") {
          const message = field(controls, "Reminder text", "message", selection.message, { required: true, limit: 800 });
          const delay = field(controls, "Minutes after the run reaches this action", "delay", selection.delay_minutes ?? 1440,
            { type: "number", required: true, min: 1, max: 525600 });
          read = () => ({ type, message: message.value, delay_minutes: delay.valueAsNumber });
        } else if (type === "feed_card") {
          const title = field(controls, "Card title", "title", selection.title, { limit: 120, required: true });
          const topic = field(controls, "Topic", "topic", selection.topic, { limit: 60, required: true });
          read = () => ({ type, title: title.value, topic: topic.value });
        } else if (type === "email_summary") {
          controls.append(el("p", "meta", "Uses the address in Settings → Reminders."));
        }
        actionReaders.set(group, { read, heading, remove, selectType });
      }
      selectType.addEventListener("change", () => show());
      group.append(heading, label("Action type", selectType), controls, remove);
      actionList.append(group);
      show(value);
      updateActions();
      return selectType;
    }
    function updateActions() {
      const size = actionReaders.size;
      add.disabled = size >= 6;
      for (const [index, item] of [...actionReaders.values()].entries()) {
        item.heading.textContent = `Action ${index + 1}`;
        item.remove.hidden = size <= 1;
      }
    }
    const add = button("Add action", "plus", () => addAction().focus());
    const submit = el("button", "primary-setting automation-button", "Save automation");
    submit.type = "submit";
    const feedback = el("p", "meta");
    feedback.setAttribute("role", "status");
    when.addEventListener("change", () => {
      displayTrigger();
      for (const { selectType } of actionReaders.values()) {
        const hasAttachments = [...selectType.options].some(({ value }) => value === "save_attachments");
        if (when.value === "email" && !hasAttachments) {
          const option = el("option", "", actionLabel("save_attachments"));
          option.value = "save_attachments";
          selectType.append(option);
        } else if (hasAttachments) {
          const changed = selectType.value === "save_attachments";
          if (when.value !== "email") selectType.querySelector('[value="save_attachments"]').remove();
          if (changed && when.value !== "email") {
            selectType.value = "prompt";
            selectType.dispatchEvent(new Event("change"));
          }
        }
      }
    });
    displayTrigger(rule?.trigger);
    for (const action of rule?.actions || [{ type: "prompt" }]) addAction(action);
    const controls = el("div", "action-row");
    controls.append(add, submit);
    form.append(label("Name", name), label("When", when), options, actionList, controls, feedback);
    dialog.append(form);
    name.focus();
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      submit.disabled = true;
      try {
        await api(`/api/event-automations/${rule ? "update" : "create"}`, {
          ...(rule ? { id: rule.id } : {}), name: name.value, trigger: readTrigger(),
          actions: [...actionReaders.values()].map(({ read }) => read()),
        });
        dialog.close();
        eventStatus.textContent = "Automation saved.";
        await eventSettings();
      } catch (error) {
        feedback.textContent = error.message;
      } finally {
        submit.disabled = false;
      }
    });
  }

  function eventCard(rule, expanded) {
    const card = el("article", "card automation-approval event-automation-card");
    const controls = el("div", "automation-controls");
    const last = rule.runs[0];
    const toggle = button(rule.enabled ? "Pause" : "Enable", rule.enabled ? "pause" : "play",
      (event) => eventAction(rule, "update", event.currentTarget, { enabled: !rule.enabled }));
    toggle.setAttribute("aria-label", `${toggle.textContent} ${rule.name}`);
    controls.append(toggle, button("Edit", "edit", (event) => eventEditor(rule, event.currentTarget)),
      button("Delete", "trash", (event) => eventAction(rule, "delete", event.currentTarget)));
    card.append(summary(rule.name, "clock", pill(rule.enabled ? "complete" : "changing", rule.enabled ? "Enabled" : "Paused")),
      eventDetails(rule));
    const state = el("p", "event-last-run");
    state.append(el("strong", "", "Last run "), last ? pill(last.status) : el("span", "meta", "No runs yet"));
    if (last) state.append(el("span", "meta", date(last.at)));
    card.append(state);
    if (rule.next_at) card.append(el("p", "meta", `Next run ${date(rule.next_at, rule.trigger.timezone)}`));
    card.append(controls);
    const history = el("details", "event-run-history");
    history.dataset.automationHistory = rule.id;
    history.open = expanded.has(rule.id);
    history.append(el("summary", "", "Run history"));
    const list = el("ul", "event-run-list");
    for (const run of rule.runs) {
      const item = el("li");
      item.append(el("span", "meta", date(run.at)), pill(run.status));
      if (run.steps.length) {
        const steps = el("ol");
        for (const step of run.steps) {
          const detail = step.message || step.error || statuses[step.status] || step.status;
          steps.append(el("li", "", `${actionLabel(step.type)} · ${detail}`));
        }
        item.append(steps);
      }
      if (run.thread_id !== "main") item.append(button("Open chat", "message", () => openThread(run.thread_id)));
      if (run.status === "approval_needed") {
        item.append(button("Open Inbox approvals", "shield", openInbox));
      }
      list.append(item);
    }
    history.append(rule.runs.length ? list : el("p", "meta", "No runs yet."));
    card.append(history);
    return card;
  }

  async function eventAction(rule, operation, control, extra = {}) {
    control.disabled = true;
    try {
      const result = await api(`/api/event-automations/${operation}`, { id: rule.id, ...extra });
      if (operation === "delete") {
        eventDeletion = result.action;
        get("event-automation-approval").replaceChildren(approvalCard(eventDeletion, "automations"));
        get("event-automation-approval").querySelector("button")?.focus();
      }
      eventStatus.textContent = operation === "update" ? (result.enabled ? "Automation enabled." : "Automation paused.") : "";
      await eventSettings();
    } catch (error) {
      eventStatus.textContent = error.message;
    } finally {
      control.disabled = false;
    }
  }

  async function eventSettings({ background } = {}) {
    const request = ++eventRequest;
    try {
      const data = await refreshAPI("/api/event-automations", { background, signal: AbortSignal.timeout(6000) });
      if (get("settings-automations").hidden || request !== eventRequest) return;
      eventData = data;
      get("new-event-automation").disabled = false;
      if (eventDeletion?.undo_automation && !eventDeletion.undone &&
          data.automations.some(({ id }) => id === eventDeletion.undo_automation)) {
        eventDeletion = { ...eventDeletion, undone: true };
        get("event-automation-approval").replaceChildren(approvalCard(eventDeletion, "automations"));
      }
      const signature = JSON.stringify([data.automations, data.reminders]);
      if (eventSignature === signature) return;
      eventSignature = signature;
      const expanded = new Set([...eventList.querySelectorAll("details[open]")].map((row) => row.dataset.automationHistory));
      eventList.replaceChildren(...data.automations.map((row) => eventCard(row, expanded)));
      if (!data.automations.length) eventList.append(el("p", "meta", "No automations yet."));
    } catch (error) {
      if (!background && request === eventRequest) eventStatus.textContent = error.message;
    }
  }

  get("new-event-automation").addEventListener("click", (event) => eventEditor(null, event.currentTarget));

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
    if (task.watch) dataField(fields, "Watches", task.watch.url);
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

  async function loadTasks({ background } = {}) {
    const request = ++taskRequest;
    try {
      const result = await refreshAPI("/api/tasks", { background, signal: AbortSignal.timeout(6000) });
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
      if (!background && request === taskRequest) get("tasks-feedback").textContent = error.message;
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
    return refresh();
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
  function openTask(id) {
    selected = id;
    return chooseTab("tasks");
  }

  return { approvalCard, home, inbox, settings, eventSettings, loadTasks, openTask, openReminders: () => chooseTab("reminders"), tasksActive: () => activeTab === "tasks" };
}
