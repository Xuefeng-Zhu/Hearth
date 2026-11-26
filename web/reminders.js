import { icon } from "./icons.js";
import { localInputTime, localTimeToISO, setTimeZone, timeFormatter } from "./time.js";
import { reconcileChildren } from "./dom.js";

const channels = { app: "In app", email: "Email", both: "Both" };
const icons = { app: ["bell"], email: ["mail"], both: ["bell", "mail"] };
const statuses = { queued: "Queued", sent: "Sent", failed: "Failed", canceled: "Canceled" };
const kinds = {
  reminder: "Reminder", event: "Event or booking", receipt: "Receipt or order",
  person: "Person or fact", list: "List or plan", other: "Note",
};
const inboxStatuses = {
  review: "Needs review", accepted: "Accepted", dismissed: "Dismissed", undone: "Undone",
};
const get = (id) => document.getElementById(id);
const fmt = timeFormatter({ dateStyle: "medium", timeStyle: "short" });
const formatDate = (at) => at && Number.isFinite(Date.parse(at)) ? fmt.format(new Date(at)) : "—";

function el(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}

function button(label, action) {
  const item = el("button", "", label);
  item.type = "button";
  item.addEventListener("click", action);
  return item;
}

function link(text, href) {
  const item = el("a", "", text);
  item.href = href;
  return item;
}

export function channelChip(channel = "app", status) {
  const chip = el("span", `delivery-chip${status ? ` delivery-${status}` : ""}`);
  chip.append(...icons[channel].map((name) => icon(name, 14)), document.createTextNode(channels[channel] + (status ? ` · ${statuses[status]}` : "")));
  return chip;
}

function heading(container, title, count) {
  const section = el("section", "delivery-section");
  const label = el("h3", "", title);
  if (count !== undefined) label.append(el("span", "delivery-count", String(count)));
  section.append(label);
  container.append(section);
  return section;
}

function localInput(at) {
  if (!at || !Number.isFinite(Date.parse(at))) return "";
  return localInputTime(at);
}

function field(label, control) {
  const item = el("label", "", label);
  item.append(control);
  return item;
}

function option(label, value) {
  const item = el("option", "", label);
  item.value = value;
  return item;
}

export function createReminders({ api, openView, openSettings, startSending, stopSending, currentView, currentSettings, onInbox }) {
  const form = get("reminder-settings-form");
  const options = get("inbox-auto-kinds");
  let backgroundPoll;
  let manualPending = false;
  let inboxRequest = 0;
  let inboxConnection;
  const inboxTarget = get("inbox-content");
  const reviewGroup = heading(inboxTarget, "Review", 0);
  const processedGroup = heading(inboxTarget, "Processed", 0);
  processedGroup.hidden = true;
  const reviewEmpty = el("p", "delivery-empty", "No email waiting for review.");
  let inboxRows = new Map();
  const editing = new Set();

  for (const [value, label] of Object.entries(kinds)) {
    const check = el("input");
    check.type = "checkbox";
    check.name = "auto_accept";
    check.value = value;
    const wrapper = el("label", "check-label");
    wrapper.append(check, document.createTextNode(label));
    options.append(wrapper);
  }

  function emailCard(target, info, title = "Email Hearth") {
    target.replaceChildren(el("h3", "", title));
    if (info.inbox_address) {
      const address = el("code", "hearth-address", info.inbox_address);
      const copy = button("Copy address", async () => {
        try {
          await navigator.clipboard.writeText(info.inbox_address);
          copy.textContent = "Copied";
        } catch {
          const selection = window.getSelection();
          const range = document.createRange();
          range.selectNodeContents(address);
          selection.removeAllRanges();
          selection.addRange(range);
        }
      });
      const line = el("div", "delivery-actions");
      line.append(address, copy);
      target.append(line, el("p", "meta", "Forward emails here to turn them into proposals in Inbox."));
    } else {
      target.append(el("p", "meta", info.connection_message || info.inbox_error || "Hearth is preparing your AgentMail inbox."));
      if (!info.connected && target.id !== "email-hearth-connection") {
        target.append(link("Open Connections", "#settings/connections"));
      }
    }
  }

  function wakeStatus(info) {
    emailCard(get("reminder-email-connection"), info);
    get("reminder-last-tick").textContent = formatDate(info.last_tick);
    get("reminder-next-due").textContent = formatDate(info.next_due);
  }

  function loadForm(info) {
    setTimeZone(info.settings.timezone);
    for (const [key, value] of Object.entries(info.settings)) {
      if (key === "auto_accept") continue;
      const control = form.elements[key];
      if (control.type === "checkbox") control.checked = value;
      else control.value = Array.isArray(value) ? value.join("\n") : value;
    }
    for (const input of options.querySelectorAll("input")) input.checked = info.settings.auto_accept.includes(input.value);
    wakeStatus(info);
  }

  async function settings() {
    try {
      const info = await api("/api/reminders/settings");
      if (currentView() === "settings" && currentSettings() === "reminders") loadForm(info);
    } catch (error) {
      get("reminder-settings-feedback").textContent = error.message;
    }
  }

  async function connections() {
    const target = get("email-hearth-connection");
    try {
      emailCard(target, await api("/api/reminders/settings"));
    } catch (error) {
      target.textContent = error.message;
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const feedback = get("reminder-settings-feedback");
    const save = form.querySelector("button[type=submit]");
    save.disabled = true;
    feedback.textContent = "Saving settings…";
    const body = Object.fromEntries(new FormData(form));
    body.allowed_senders = body.allowed_senders.split(/[\n,]+/).map((entry) => entry.trim()).filter(Boolean);
    body.auto_accept = [...options.querySelectorAll("input:checked")].map((entry) => entry.value);
    body.acknowledge = form.elements.acknowledge.checked;
    try {
      loadForm(await api("/api/reminders/settings", body));
      feedback.textContent = "Reminder settings saved.";
    } catch (error) {
      feedback.textContent = error.message;
    } finally {
      save.disabled = false;
    }
  });

  for (const item of document.querySelectorAll("[data-reminder-test]")) {
    item.addEventListener("click", async () => {
      const channel = item.dataset.reminderTest;
      const feedback = get("reminder-test-feedback");
      feedback.textContent = channel === "email" ? "Sending reminder…" : "Creating in-app reminder…";
      item.disabled = true;
      if (channel === "email") startSending();
      try {
        const result = await api("/api/reminders/test", { channel });
        const delivery = result.delivery[channel];
        feedback.textContent = `${statuses[delivery.status]}${delivery.reason ? ` · ${delivery.reason}` : ""}`;
        if (delivery.status === "failed") feedback.append(" ", button("View Reminders", () => openView("reminders")));
        wakeStatus(await api("/api/reminders/settings"));
      } catch (error) {
        feedback.textContent = error.message;
      } finally {
        if (channel === "email") stopSending();
        item.disabled = false;
      }
    });
  }

  get("open-reminder-settings").addEventListener("click", () => openSettings("reminders"));

  const reminderForm = get("reminder-create-form");
  reminderForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(reminderForm));
    const feedback = get("reminders-feedback");
    if (!data.channel) delete data.channel;
    data.urgent = reminderForm.elements.urgent.checked;
    const submit = reminderForm.querySelector("button[type=submit]");
    submit.disabled = true;
    try {
      data.at = localTimeToISO(data.at);
      await api("/api/reminders/create", data);
      reminderForm.reset();
      get("reminder-create").open = false;
      get("reminder-create").querySelector("summary").focus();
      feedback.textContent = "Reminder scheduled.";
      await reminders();
    } catch (error) {
      feedback.textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  });

  async function cancelReminder(identity) {
    const feedback = get("reminders-feedback");
    try {
      await api("/api/reminders/cancel", { id: identity });
      feedback.textContent = "Reminder canceled.";
      await reminders();
    } catch (error) {
      feedback.textContent = error.message;
    }
  }

  function reminderCard(row) {
    const card = el("article", "card delivery-card");
    card.dataset.reminder = row.job_id || row.id;
    const header = el("div", "delivery-card-head");
    const title = el("h4", "", row.message);
    const when = formatDate(row.next_at || row.scheduled_at);
    header.append(title, el("span", "meta", when));
    const chips = el("div", "delivery-chips");
    for (const [channel, delivery] of Object.entries(row.delivery)) {
      chips.append(channelChip(channel, delivery.status));
    }
    card.append(header, chips);
    if (row.note) card.append(el("p", "delivery-note", row.note));
    for (const [channel, delivery] of Object.entries(row.delivery)) {
      if (delivery.reason || delivery.sending) {
        const reason = el("p", "meta", `${channels[channel]} · ${delivery.sending ? "Sending reminder" : delivery.reason}`);
        if (delivery.next_at && delivery.status === "queued" && !delivery.sending) {
          reason.append(` · Next attempt ${formatDate(delivery.next_at)}`);
        }
        if (delivery.reason?.startsWith("Not connected")) reason.append(" · ", link("Connections", "#settings/connections"));
        card.append(reason);
      }
    }
    const detail = [
      row.late_minutes ? `Late by ${row.late_minutes}m` : "",
      row.action?.label,
      row.cron ? `Repeats · ${row.cron} UTC` : "",
    ].filter(Boolean).join(" · ");
    if (detail) card.append(el("p", "meta", detail));
    if (row.cancelable) card.append(button("Undo", () => cancelReminder(row.job_id || row.id)));
    return card;
  }

  let reminderSignature;
  async function reminders() {
    const target = get("reminders-content");
    try {
      const result = await api("/api/reminders");
      if (result.timezone) setTimeZone(result.timezone);
      const signature = JSON.stringify(result);
      if (signature === reminderSignature) return;
      reminderSignature = signature;
      target.replaceChildren();
      const groups = [
        ["Upcoming", [
          ...result.jobs.filter((job) => !job.snoozed_at),
          ...result.delivered.filter((row) => row.delivery.email?.status === "queued" && !row.delivery.app),
        ]],
        ["Snoozed", result.jobs.filter((job) => job.snoozed_at)],
        ["Delivered", result.delivered.filter((row) => row.delivery.email?.status !== "queued" || row.delivery.app)],
      ];
      for (const [name, entries] of groups) {
        const group = heading(target, name, entries.length);
        if (!entries.length) group.append(el("p", "delivery-empty", `No ${name.toLowerCase()} reminders.`));
        else group.append(...entries.map(reminderCard));
      }
      if (result.outbox.length) {
        const outbox = heading(target, "Outbox", result.outbox.length);
        for (const row of result.outbox) {
          const card = el("article", "card delivery-card");
          const title = link(row.subject, `/api/reminders/outbox?id=${encodeURIComponent(row.id)}`);
          title.target = "_blank";
          title.rel = "noopener";
          card.append(title, el("p", "meta", `${formatDate(row.created_at)} · Demo copy`));
          outbox.append(card);
        }
      }
    } catch (error) {
      get("reminders-feedback").textContent = error.message;
    }
  }

  function proposalText(proposal) {
    const action = {
      reminder: "Schedule a reminder",
      event: "Add a Timeline event and a reminder",
      receipt: proposal.at ? "Save to Memory and schedule a return reminder" : "Save receipt to Memory",
      person: "Save a fact to Memory", list: "Create a local Artifact", other: "Save a note to Memory",
    }[proposal.kind];
    return [action, proposal.at && formatDate(proposal.at), proposal.merchant, proposal.amount].filter(Boolean).join(" · ");
  }

  async function changeCard(card, operation, fields) {
    const feedback = get("inbox-feedback");
    try {
      const result = await api(`/api/inbox/${operation}`, { id: card.id, ...fields });
      editing.delete(card.id);
      feedback.textContent = inboxStatuses[result.status] + ".";
      await inbox();
    } catch (error) {
      feedback.textContent = error.message;
    }
  }

  function editor(card, article, target) {
    const proposal = card.proposal;
    editing.add(card.id);
    const form = el("form", "delivery-form inbox-edit");
    const title = el("input");
    title.value = proposal.title;
    title.maxLength = 240;
    title.required = true;
    const kind = el("select");
    kind.append(...Object.entries(kinds).map(([value, label]) => option(label, value)));
    kind.value = proposal.kind;
    const date = el("input");
    date.type = "datetime-local";
    date.value = localInput(proposal.at);
    const summary = el("textarea");
    summary.rows = 2;
    summary.maxLength = 2000;
    summary.value = proposal.summary;
    const actions = el("div", "delivery-actions delivery-full");
    const save = el("button", "primary-setting", "Save and accept");
    save.type = "submit";
    actions.append(save, button("Cancel", () => {
      editing.delete(card.id);
      form.remove();
      target.hidden = false;
      target.querySelectorAll("button")[1].focus();
      inbox();
    }));
    form.append(field("Title", title), field("Proposal type", kind), field("Date and time", date),
      field("Summary", summary), actions);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      save.disabled = true;
      try {
        const editedAt = date.value === localInput(proposal.at) ? proposal.at
          : date.value ? localTimeToISO(date.value) : null;
        await changeCard(card, "edit", { title: title.value, kind: kind.value, at: editedAt, summary: summary.value });
      } catch (error) {
        get("inbox-feedback").textContent = error.message;
      } finally {
        save.disabled = false;
      }
    });
    target.hidden = true;
    article.append(form);
    title.focus();
  }

  function inboxCard(card) {
    const article = el("article", "card delivery-card inbox-card");
    const header = el("div", "delivery-card-head");
    header.append(el("h4", "", card.title), el("span", "meta", formatDate(card.received_at)));
    const chips = el("div", "delivery-chips");
    chips.append(el("span", "delivery-chip", kinds[card.proposal.kind]),
      el("span", `delivery-chip delivery-${card.status === "accepted" ? "sent" : "queued"}`, inboxStatuses[card.status]));
    if (card.automatic) chips.append(el("span", "delivery-chip", "Automatic"));
    article.append(header, chips, el("p", "meta", [card.sender && `From ${card.sender}`,
      card.original_sender && `Original sender ${card.original_sender}`, card.original_date && `Original date ${formatDate(card.original_date)}`]
      .filter(Boolean).join(" · ")),
    el("p", "", card.proposal.summary), el("p", "inbox-proposal", proposalText(card.proposal)));
    if (card.suspicious) article.append(el("p", "meta", "Contains instruction-like text. Review required."));
    else if (!card.authenticated && card.status === "review") {
      article.append(el("p", "meta", card.allowlisted ? "Sender authentication could not be verified." : "Sender is outside your allowlist."));
    }
    if (card.body || card.attachments.length) {
      const details = el("details", "inbox-source");
      details.append(el("summary", "", "Email text and attachments"));
      if (card.body) details.append(el("pre", "", card.body));
      for (const attachment of card.attachments) {
        const file = el("details", "inbox-source");
        file.append(el("summary", "", [attachment.name, attachment.type,
          attachment.size == null ? "" : `${attachment.size.toLocaleString()} bytes`].filter(Boolean).join(" · ")));
        if (attachment.text) file.append(el("pre", "", attachment.text));
        else file.append(el("p", "meta", attachment.note || "Metadata only"));
        details.append(file);
      }
      article.append(details);
    }
    const actions = el("div", "delivery-actions");
    if (card.status === "review") {
      const accept = button("Accept", () => changeCard(card, "accept"));
      accept.className = "primary-setting";
      actions.append(accept, button("Edit", () => editor(card, article, actions)),
        button("Dismiss", () => changeCard(card, "dismiss")));
    } else if (card.status === "accepted") actions.append(button("Undo", () => changeCard(card, "undo")));
    if (actions.children.length) article.append(actions);
    return article;
  }

  async function inbox() {
    const request = ++inboxRequest;
    try {
      const result = await api("/api/inbox");
      if (request !== inboxRequest || currentView() !== "inbox") return;
      onInbox(result.task_notifications || [], result.approvals || []);
      if (result.settings?.timezone) setTimeZone(result.settings.timezone);
      const connection = JSON.stringify([result.connected, result.inbox_address, result.inbox_error, result.connection_message]);
      if (connection !== inboxConnection) {
        inboxConnection = connection;
        emailCard(get("inbox-address"), result);
      }
      const next = new Map();
      const review = [];
      const processed = [];
      for (const card of result.cards) {
        const signature = JSON.stringify([card, result.settings?.timezone]);
        let row = inboxRows.get(card.id);
        if (!row || (row.signature !== signature && !editing.has(card.id))) {
          row = { signature, element: inboxCard(card), status: card.status };
        }
        next.set(card.id, row);
        (row.status === "review" ? review : processed).push(row.element);
      }
      for (const id of editing) if (!next.has(id)) editing.delete(id);
      inboxRows = next;
      processedGroup.hidden = !processed.length;
      for (const [group, rows] of [[reviewGroup, review], [processedGroup, processed]]) {
        const title = group.firstElementChild;
        title.firstElementChild.textContent = rows.length;
        reconcileChildren(group, [title, ...(group === reviewGroup && !rows.length ? [reviewEmpty] : rows)]);
      }
    } catch (error) {
      if (request === inboxRequest) get("inbox-feedback").textContent = error.message;
    }
  }

  async function checkMail(manual) {
    const feedback = get("inbox-feedback");
    try {
      const result = await api("/api/inbox/poll", manual ? { force: true } : {});
      if (currentView() === "inbox") {
        await inbox();
        if (manual) feedback.textContent = result.processed ? `Processed ${result.processed} email(s).` : "Check complete.";
      }
      if (currentView() === "settings" && currentSettings() === "connections") await connections();
      if (currentView() === "settings" && currentSettings() === "reminders") wakeStatus(await api("/api/reminders/settings"));
    } catch (error) {
      if (manual) feedback.textContent = error.message;
    }
  }

  function poll() {
    if (manualPending || backgroundPoll) return;
    backgroundPoll = checkMail(false).finally(() => { backgroundPoll = undefined; });
  }

  const manualCheck = get("inbox-poll");
  manualCheck.addEventListener("click", async () => {
    if (manualPending) return;
    manualPending = true;
    manualCheck.setAttribute("aria-disabled", "true");
    get("inbox-feedback").textContent = "Checking for forwarded email…";
    try {
      await backgroundPoll;
      await checkMail(true);
    } finally {
      manualPending = false;
      manualCheck.removeAttribute("aria-disabled");
    }
  });
  return { settings, reminders, inbox, connections, poll };
}
