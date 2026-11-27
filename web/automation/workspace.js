import { render } from "preact";
import { html, Icon } from "../ui.js";
import { node as el } from "../dom.js";
import { iconButton } from "../icons.js";
import { DEFAULT_TIME_ZONE, timeFormatter } from "../time.js";

import { Button, Pill, Heading, Fields, Times, EventDetails, label, select, input, date, scheduleText,
  weekdays, triggerTypes, actionTypes, feedKinds, actionLabel, statuses, nextLabelId } from "../approval-cards.js";

const get = (id) => document.getElementById(id);
const policyOptions = [["ask", "Always ask"], ["allow", "Allow without asking"]];
const labels = { send: "Send messages", spend: "Spend money", public: "Publish publicly", destructive: "Delete items", skills: "Skills", goals: "Create goals" };
const delivery = [["app", "In app"], ["email", "Email"], ["both", "Both"]];
const scheduleTypes = ["Once", "Daily", "Weekly", "Interval", "Cron"];
function button(label, glyph, handler, className = "") {
  const item = iconButton(glyph, label, handler, `automation-button ${className}`);
  item.append(el("span", "", label));
  return item;
}

function dateInput(value, zone) {
  if (!value) return "";
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: zone, hourCycle: "h23",
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
    .formatToParts(new Date(value));
  const pieces = Object.fromEntries(parts.map(({ type, value: field }) => [type, field]));
  return `${pieces.year}-${pieces.month}-${pieces.day}T${pieces.hour}:${pieces.minute}`;
}

export function createAutomation({ api, refreshAPI, refresh, openThread, openInbox, undo, approvals }) {
  const dialog = get("automation-dialog");
  const { approvalCard, openDialog } = approvals;
  let activeTab = "reminders";
  let selected;
  let taskSignature;
  let taskRequest = 0;
  let deleting;

  let settingsForm, settingsStatus;
  async function settings() {
    if (!settingsForm) {
      settingsForm = get("approval-settings-form");
      settingsStatus = get("approval-settings-feedback");
      const policies = get("approval-policies");
      for (const [key, phrase] of Object.entries(labels)) policies.append(label(phrase, select(key, policyOptions, "ask")));
      settingsForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          await api("/api/approvals/settings", Object.fromEntries(new FormData(settingsForm)));
          settingsStatus.textContent = "Settings saved.";
        } catch (error) {
          settingsStatus.textContent = error.message;
        }
      });
    }
    try {
      const policy = await api("/api/approvals/settings");
      for (const key of Object.keys(labels)) settingsForm.elements[key].value = policy[key];
    } catch (error) {
      settingsStatus.textContent = error.message;
    }
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
    const [nameId, instructionId, enabledId] = Array.from({ length: task?.watch ? 2 : 3 }, nextLabelId);
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

  let eventList, eventStatus;
  let eventData;
  let eventSignature;
  let eventDeletion;
  let eventRequest = 0;

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
      const id = nextLabelId();
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
      <${EventDetails} rule=${rule} data=${eventData} />
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

  let eventMounted = false;
  async function eventSettings({ background } = {}) {
    if (!eventMounted) {
      eventMounted = true;
      eventList = get("event-automation-list");
      eventStatus = get("event-automation-status");
      get("new-event-automation").addEventListener("click", (event) => eventEditor(null, event.currentTarget));
    }
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

  function mountTasks() {
    get("new-task").addEventListener("click", (event) => editor(null, event.currentTarget));
  }

  function openTask(id) {
    selected = id;
    return chooseTab("tasks");
  }

  return { settings, eventSettings, loadTasks, mountTasks, chooseTab, openTask,
    onDecision(id, result) {
      if (deleting?.id === id) deleting = result;
      if (eventDeletion?.id === id) eventDeletion = result;
    },
    get eventData() { return eventData; },
    openReminders: () => chooseTab("reminders"), tasksActive: () => activeTab === "tasks" };
}
