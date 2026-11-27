import { render } from "preact";
import { html, Icon } from "../chat/view.js";
import { node as el } from "../dom.js";
import { iconButton } from "../icons.js";
import { DEFAULT_TIME_ZONE, timeFormatter } from "../time.js";

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

function Button({ text, glyph, action, className = "", label = text, disabled, pressed, children }) {
  return html`<button type="button" class=${`automation-button ${className}`} title=${text} aria-label=${label}
    disabled=${disabled} aria-pressed=${pressed} onClick=${action}>
    <${Icon} name=${glyph} size=${18} /><span>${text}</span>${children}
  </button>`;
}

function Pill({ status, text = statuses[status] || status }) {
  return html`<span class=${`automation-state automation-state-${status}`}>${text}</span>`;
}

function Heading({ title, glyph, status, text }) {
  return html`<div class="automation-card-heading">
    <span class="automation-mark"><${Icon} name=${glyph} size=${19} /></span>
    <h3>${title}</h3><${Pill} ...${{ status, text }} />
  </div>`;
}

function Fields({ entries }) {
  const visible = entries.filter(([, value]) => value != null && value !== "");
  return visible.length ? html`<dl class="automation-fields">${visible.map(([name, value]) => html`<dt>${name}</dt><dd>${value}</dd>`)}</dl>` : null;
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

function Times({ values, zone }) {
  return html`<ol class="automation-times">${values.map((value) => html`
    <li><time datetime=${value}>${date(value, zone)}</time></li>`)}
  </ol>`;
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
    render(null, dialog);
  });

  function openDialog(title, trigger, body) {
    dialogTrigger = trigger;
    render(html`
      <header class="automation-dialog-header">
        <h2 id="automation-dialog-title">${title}</h2>
        <button type="button" class="icon-button" aria-label="Close" title="Close" onClick=${() => dialog.close()}>
          <${Icon} name="x" size=${18} />
        </button>
      </header>
      ${body}
    `, dialog);
    dialog.showModal();
    return dialog.querySelector("form");
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
    const captions = Object.entries(row.editable).map(([key, value]) => {
      const id = `automation-label-${++labelId}`;
      return html`<label><span id=${id}>${editLabels[key]}</span>${key === "subject"
        ? html`<input name=${key} type="text" defaultValue=${value} maxlength="240" aria-labelledby=${id} required />`
        : html`<textarea name=${key} defaultValue=${value} aria-labelledby=${id} required></textarea>`}</label>`;
    });
    const form = openDialog("Edit approval", trigger, html`<form class="automation-editor">
      ${captions}<button class="primary-setting" type="submit">Save changes</button><p class="meta" role="status"></p>
    </form>`);
    const save = form.querySelector("[type=submit]");
    const feedback = form.querySelector("[role=status]");
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
    const fields = [];
    if (row.email) fields.push(["To", row.email.to.join(", ")], ["Subject", row.email.subject], ["Message", row.email.text]);
    else if (!confirmation) {
      fields.push(["Target", row.target]);
      if (row.categories.includes("spend")) fields.push(["Estimated cost", row.amount]);
      if (row.attachment_names?.length) fields.push(["Attachments", row.attachment_names.join("\n")]);
      if (row.steps?.length) fields.push(["Steps", row.steps.map(({ action, target, text }) =>
        [action, target, text].filter(Boolean).join(" ")).join("\n")]);
      if (row.request?.body != null) fields.push(["Request", JSON.stringify(row.request.body, null, 2)]);
    }
    if (row.goal_preview) {
      fields.push(["Target date", row.goal_preview.target_date]);
      const checkin = row.goal_preview.checkin;
      if (checkin) fields.push(["Check-in", `${checkin.cadence === "daily" ? "Daily" :
        ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][checkin.day]} at ${checkin.time}`]);
      if (row.goal_preview.links.length) fields.push(["Linked items", String(row.goal_preview.links.length)]);
    }
    const result = row.result;
    const act = (verb) => decision(row, verb, article).catch(() => {});
    render(html`
      <${Heading} title=${row.title} glyph=${confirmation ? "clock" : marks[category] || "shield"} status=${status}
        text=${status === "pending" && confirmation ? (eventConfirmation ? "Confirm automation" : "Confirm schedule") : undefined} />
      ${row.worker_title && html`<p class="thread-source">Worker · ${row.worker_title}</p>`}
      <${Fields} entries=${fields} />
      ${row.upcoming?.length && !taskConfirmation ? html`
        <p class="automation-label">${row.tool === "create_watcher" ? "Upcoming checks" : "Reminder time"}</p>
        <${Times} values=${row.upcoming} zone=${row.args.task?.timezone} />` : null}
      ${category === "skills" && row.args?.markdown && html`<details class="automation-result-details">
        <summary>Review proposed Markdown</summary><pre>${row.args.markdown}</pre>
      </details>`}
      ${eventConfirmation && html`<${EventDetails} rule=${row.args} data=${row.automation_context || eventData} />`}
      ${taskConfirmation && html`<p class="automation-instruction">${row.args.instruction}</p>
        <p class="automation-label">Upcoming runs</p><${Times} values=${row.upcoming} zone=${row.args.timezone} />`}
      ${(result?.message || result?.error) && html`<p class="automation-result">${result.message || result.error}</p>`}
      ${(result?.response || result?.message_id || result?.text) && html`<details class="automation-result-details">
        <summary>Tool result</summary><pre>${result.response ? JSON.stringify(result.response, null, 2) : result.text || result.message_id}</pre>
      </details>`}
      <div class="automation-card-footer">
        <span class="meta">${status === "pending" ? `Expires ${date(row.expires_at)}` : ""}</span>
        <div class="automation-controls">
          ${status === "pending" && html`
            <${Button} text=${confirmation ? "Confirm" : "Approve"} glyph="check" className="primary-setting" action=${() => act("approve")} />
            ${Object.keys(row.editable || {}).length ? html`<${Button} text="Edit" glyph="edit"
              action=${(event) => edit(row, article, event.currentTarget)} />` : null}
            <${Button} text="Decline" glyph="x" action=${() => act("decline")} />`}
          ${(row.undo_task || row.undo_automation) && !row.undone &&
            html`<${Button} text="Undo" glyph="history" action=${() => undo(row)} />`}
          ${row.effect_action && ["memory_write", "delete_memory"].includes(row.tool) && !row.effect_undone &&
            html`<${Button} text="Undo" glyph="history" action=${() => undo({ id: row.effect_action, memory_change: true })} />`}
          ${!["chat", "idea", "goal"].includes(surface) && row.thread_id &&
            html`<${Button} text="Open chat" glyph="message" action=${() => openThread(row.thread_id)} />`}
        </div>
      </div>
      <p class="meta automation-feedback" role="status"></p>
    `, article);
    return article;
  }

  function approvalGroup(target, items, surface) {
    target.hidden = !items.length;
    render(items.length ? html`
      <div class="automation-section-heading"><${Icon} name="shield" />
        <h2>${surface === "home" ? "Pending approvals" : "Approvals"}</h2>
        <${Pill} status="pending" text=${items.filter((item) => item.status === "pending").length} />
      </div>
      <div class="automation-approval-list" ref=${(host) => host?.replaceChildren(...items.map((row) => approvalCard(row, surface)))}></div>
    ` : null, target);
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
    render(items.length ? html`
      <div class="automation-section-heading"><${Icon} name="clock" /><h2>Recurring task updates</h2></div>
      <div class="automation-approval-list">${items.map((row) => html`<article class="card automation-approval">
        <${Heading} title=${row.title} glyph="clock" status=${row.status} />
        <p class="automation-result">${row.text}</p><p class="meta">${date(row.created_at)}</p>
        ${row.email_state === "failed" && html`<p class="meta">${row.email_reason}</p>`}
        <${Button} text="Open chat" glyph="message" action=${() => openThread(row.thread_id)} />
      </article>`)}</div>
    ` : null, target);
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
    const scheduleUI = scheduleEditor(task?.schedule, task?.timezone);
    scheduleUI.fields.append(label("Delivery", select("delivery", delivery, task?.delivery || "app")));
    const [nameId, instructionId, enabledId] = Array.from({ length: task?.watch ? 2 : 3 }, () => `automation-label-${++labelId}`);
    const form = openDialog(task?.watch ? "Edit watcher" : task ? "Edit recurring task" : "New recurring task", trigger, html`
      <form class="automation-editor">
        <label><span id=${nameId}>Name</span><input name="name" type="text" defaultValue=${task?.name || ""}
          maxlength="80" required aria-labelledby=${nameId} /></label>
        ${task?.watch ? html`<p class="meta">${task.watch.url}</p>` : html`<label><span id=${instructionId}>Instruction</span>
          <textarea name="instruction" defaultValue=${task?.instruction || ""} maxlength="4000" required aria-labelledby=${instructionId}></textarea>
        </label>`}
        <div class="automation-editor-fields" ref=${(host) => host?.replaceChildren(...scheduleUI.fields.childNodes)}></div>
        <label class="automation-enabled"><span id=${enabledId || instructionId}>Enabled</span>
          <input name="enabled" type="checkbox" value="true" defaultChecked=${task?.enabled ?? true}
            aria-labelledby=${enabledId || instructionId} />
        </label>
        <div class="automation-preview"></div>
        <div class="automation-controls"><button class="primary-setting" type="submit">Preview schedule</button></div>
        <p class="meta" role="status"></p>
      </form>`);
    const { name, instruction, delivery: channel, enabled } = form.elements;
    const preview = form.querySelector(".automation-preview");
    const feedback = form.querySelector("[role=status]");
    const submit = form.querySelector("[type=submit]");
    let reviewed = false;
    form.addEventListener("input", () => {
      reviewed = false;
      render(null, preview);
      feedback.textContent = "";
      submit.textContent = "Preview schedule";
    });
    name.focus();
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = { ...(task ? { id: task.id } : {}), name: name.value, instruction: instruction?.value ?? task?.instruction ?? "",
        enabled: enabled.checked, delivery: channel.value, ...scheduleUI.value() };
      submit.disabled = true;
      try {
        if (!reviewed) {
          const result = await api("/api/tasks/preview", data);
          render(html`<p class="automation-label">Upcoming runs</p>${result.upcoming.length
            ? html`<${Times} values=${result.upcoming} zone=${result.timezone} />` : html`<p class="meta">No upcoming runs.</p>`}`, preview);
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

  function EventDetails({ rule, data = eventData }) {
    const { trigger, actions } = rule;
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
    const then = actions.map((action) => {
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
    }).join("\n");
    return html`<${Fields} entries=${[["When", when], ["Then", then]]} />`;
  }

  function eventEditor(rule, trigger) {
    const form = openDialog(rule ? "Edit automation" : "New automation", trigger, html`
      <form class="automation-editor event-automation-editor">
        <label><span>Name</span><input name="name" type="text"
          defaultValue=${rule?.name || ""} maxlength="80" required /></label>
        <label><span>When</span><select name="when" value=${rule?.trigger.type || "email"}>
          ${triggerTypes.map(([key, text]) => html`<option value=${key}>${text}</option>`)}
        </select></label>
        <div class="event-trigger-fields"></div>
        <div class="event-action-fields"></div>
        <div class="action-row">
          <${Button} text="Add action" glyph="plus" action=${() => addAction().focus()} />
          <button type="submit" class="primary-setting automation-button">Save automation</button>
        </div>
        <p class="meta" role="status"></p>
      </form>`);
    const { name, when } = form.elements;
    const options = form.querySelector(".event-trigger-fields");
    const actionList = form.querySelector(".event-action-fields");
    const add = form.querySelector(".action-row button");
    const submit = form.querySelector("[type=submit]");
    const feedback = form.querySelector("[role=status]");
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
    for (const control of [name, when]) {
      const id = `automation-label-${++labelId}`;
      control.closest("label").firstElementChild.id = id;
      control.setAttribute("aria-labelledby", id);
    }
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

  function EventCard({ rule, expanded }) {
    const last = rule.runs[0];
    const toggle = rule.enabled ? "Pause" : "Enable";
    return html`<article class="card automation-approval event-automation-card">
      <${Heading} title=${rule.name} glyph="clock" status=${rule.enabled ? "complete" : "changing"}
        text=${rule.enabled ? "Enabled" : "Paused"} />
      <${EventDetails} rule=${rule} />
      <p class="event-last-run"><strong>Last run </strong>
        ${last ? html`<${Pill} status=${last.status} /><span class="meta">${date(last.at)}</span>`
          : html`<span class="meta">No runs yet</span>`}
      </p>
      ${rule.next_at && html`<p class="meta">Next run ${date(rule.next_at, rule.trigger.timezone)}</p>`}
      <div class="automation-controls">
        <${Button} text=${toggle} label=${`${toggle} ${rule.name}`} glyph=${rule.enabled ? "pause" : "play"}
          action=${(event) => eventAction(rule, "update", event.currentTarget, { enabled: !rule.enabled })} />
        <${Button} text="Edit" glyph="edit" action=${(event) => eventEditor(rule, event.currentTarget)} />
        <${Button} text="Delete" glyph="trash" action=${(event) => eventAction(rule, "delete", event.currentTarget)} />
      </div>
      <details class="event-run-history" data-automation-history=${rule.id} open=${expanded.has(rule.id)}>
        <summary>Run history</summary>
        ${rule.runs.length ? html`<ul class="event-run-list">${rule.runs.map((run) => html`<li>
          <span class="meta">${date(run.at)}</span><${Pill} status=${run.status} />
          ${run.steps.length ? html`<ol>${run.steps.map((step) => html`<li>
            ${actionLabel(step.type)} · ${step.message || step.error || statuses[step.status] || step.status}
          </li>`)}</ol>` : null}
          ${run.thread_id !== "main" && html`<${Button} text="Open chat" glyph="message" action=${() => openThread(run.thread_id)} />`}
          ${run.status === "approval_needed" && html`<${Button} text="Open Inbox approvals" glyph="shield" action=${openInbox} />`}
        </li>`)}</ul>` : html`<p class="meta">No runs yet.</p>`}
      </details>
    </article>`;
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
      render(data.automations.length ? data.automations.map((rule) => html`<${EventCard} key=${rule.id} ...${{ rule, expanded }} />`)
        : html`<p class="meta">No automations yet.</p>`, eventList);
    } catch (error) {
      if (!background && request === eventRequest) eventStatus.textContent = error.message;
    }
  }

  get("new-event-automation").addEventListener("click", (event) => eventEditor(null, event.currentTarget));

  function TaskRun({ run, zone, expanded }) {
    const time = date(run.started_at, zone);
    const metadata = [run.duration_ms !== undefined ? `${(run.duration_ms / 1000).toFixed(1)} s` : "",
      `${run.attempts} attempt${run.attempts === 1 ? "" : "s"}`].filter(Boolean);
    return html`<details class="automation-run" open=${expanded.has(time)}>
      <summary><${Icon} name="chevron" size=${15} /><span class="automation-run-time">${time}</span><${Pill} status=${run.status} /></summary>
      <div class="automation-run-body">
        ${run.output && html`<p class="automation-result">${run.output}</p>`}
        ${run.reason && html`<p class="automation-result">${run.reason}</p>`}
        <p class="meta">${metadata.join(" · ")}</p>
        ${run.tools?.length ? html`<p class="meta">${run.tools.map((tool) => `${tool.tool} · ${statuses[tool.status]}`).join(", ")}</p>` : null}
      </div>
    </details>`;
  }

  function TaskDetail({ task, expanded }) {
    const running = task.manual_due || task.runs.some((run) => ["running", "retrying"].includes(run.status));
    const entries = [["Watches", task.watch?.url], ["Schedule", scheduleText(task.schedule)],
      ["Next run", task.next_run ? date(task.next_run, task.timezone) : "—"], ["Time zone", task.timezone],
      ["Delivery", delivery.find(([key]) => key === task.delivery)?.[1]]];
    return html`<article class="card automation-task-detail">
      <${Heading} title=${task.name} glyph="clock" status=${task.enabled ? "complete" : "changing"}
        text=${task.enabled ? "Enabled" : "Paused"} />
      <p class="automation-instruction">${task.instruction}</p>
      <div class="automation-controls automation-task-controls">
        <${Button} text="Run now" glyph="play" className="primary-setting" disabled=${!!running} action=${() => taskAction(task, "run")} />
        <${Button} text=${task.enabled ? "Pause" : "Resume"} glyph=${task.enabled ? "pause" : "play"}
          action=${() => task.enabled ? taskAction(task, "pause") : taskAction(task, "update", { enabled: true })} />
        <${Button} text="Edit" glyph="edit" action=${(event) => editor(task, event.currentTarget)} />
        <${Button} text="Delete" glyph="trash" action=${() => taskAction(task, "delete")} />
      </div>
      <${Fields} entries=${entries} />
      <div class="automation-history">
        <div class="automation-section-heading"><h4>Run history</h4>
          ${task.chat_id && html`<${Button} text="Open chat" glyph="message" action=${() => openThread(task.chat_id)} />`}
        </div>
        ${task.runs.length ? task.runs.map((run) => html`<${TaskRun} key=${run.id} run=${run} zone=${task.timezone} expanded=${expanded} />`)
          : html`<p class="meta">${running ? "Run queued." : "No runs yet."}</p>`}
      </div>
    </article>`;
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
      render(html`
        <div class="automation-task-list">${result.tasks.map((row) => html`
          <${Button} key=${row.id} text=${row.name} glyph="clock" className="automation-task-selector"
            pressed=${String(row.id === selected)} action=${() => { selected = row.id; loadTasks(); }}>
            <small class="meta">${row.enabled ? scheduleText(row.schedule) : "Paused"}</small>
          </${Button}>`)}
        </div>
        ${task ? html`<${TaskDetail} key=${task.id} ...${{ task, expanded }} />` : html`<p class="meta">No recurring tasks yet.</p>`}
      `, host);
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
