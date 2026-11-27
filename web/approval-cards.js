import { render } from "preact";
import { html, Icon } from "./ui.js";
import { node as el } from "./dom.js";
import { timeFormatter } from "./time.js";

const get = (id) => document.getElementById(id);
const marks = { send: "mail", spend: "clock", public: "share", destructive: "trash", skills: "skill", goals: "activity" };
const statuses = {
  pending: "Needs approval", expired: "Expired", declined: "Declined", cancelled: "Stopped", changing: "Execution unconfirmed",
  complete: "Completed", sent: "Sent", simulated: "Simulated", failed: "Failed", request_unknown: "Outcome unconfirmed",
  partial: "Partially applied", skipped: "Skipped", queued: "Queued", rate_limited: "Hourly limit reached", running: "Running", retrying: "Retry scheduled", approval_needed: "Needs approval",
};
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

let labelId = 0;

export function nextLabelId() {
  return `automation-label-${++labelId}`;
}

function label(text, input, className = "") {
  const element = el("label", className);
  const caption = el("span", "", text);
  caption.id = nextLabelId();
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

function Times({ values, zone }) {
  return html`<ol class="automation-times">${values.map((value) => html`
    <li><time datetime=${value}>${date(value, zone)}</time></li>`)}
  </ol>`;
}


function scheduleText(schedule) {
  if (schedule.type === "weekly") return `${schedule.days.map((day) => weekdays[day]).join(", ")} at ${schedule.time}`;
  if (schedule.type === "daily") return `Daily at ${schedule.time}`;
  if (schedule.type === "interval") return `Every ${schedule.minutes} min`;
  if (schedule.type === "cron") return schedule.cron;
  return "One time";
}

function EventDetails({ rule, data }) {
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


export { Button, Pill, Heading, Fields, Times, EventDetails, label, select, input, date, scheduleText,
  weekdays, triggerTypes, actionTypes, feedKinds, actionLabel, statuses };

export function createApprovalCards({ api, refresh, openThread, undo, onDecision, eventData }) {
  const dialog = get("automation-dialog");
  const takingAction = new Set();
  let dialogTrigger;
  let homeSignature, inboxSignature;

  dialog.addEventListener("close", () => {
    if (dialogTrigger?.isConnected) dialogTrigger.focus();
    else if (get("new-event-automation")?.checkVisibility()) get("new-event-automation").focus();
    else if (get("new-task")?.checkVisibility()) get("new-task").focus();
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
      onDecision(row.id, result);
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
      const id = nextLabelId();
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
      ${eventConfirmation && html`<${EventDetails} rule=${row.args} data=${row.automation_context || eventData()} />`}
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

  return { approvalCard, openDialog, home, inbox };
}
