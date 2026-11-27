import { render } from "preact";
import { html } from "../chat/view.js";
import { node as el, button } from "../dom.js";
import { formatDate, statuses, ReminderList } from "./view.js";
import { localInputTime, localTimeToISO, setTimeZone } from "../time.js";
import { appendHighlighted, reconcileChildren } from "../dom.js";
import { listSearchExcerpt, listSearchPath } from "../list-search.js";
import { confirmControl, prepareListMotion } from "../motion.js";

const kinds = {
  reminder: "Reminder", event: "Event or booking", receipt: "Receipt or order",
  person: "Person or fact", list: "List or plan", other: "Note",
};
const inboxStatuses = {
  review: "Needs review", accepted: "Accepted", dismissed: "Dismissed", undone: "Undone",
};
const get = (id) => document.getElementById(id);
function link(text, href) {
  const item = el("a", "", text);
  item.href = href;
  return item;
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

export function createReminders({ api, refreshAPI, openView, openSettings, startSending, stopSending,
  currentView, currentSettings, onInbox, reminderSearch, inboxSearch }) {
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
  let inboxUnfiltered = false;
  let remindersUnfiltered = false;
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

  function emailCard(target, info) {
    async function copyAddress(event) {
      const copy = event.currentTarget;
      try {
        await navigator.clipboard.writeText(info.inbox_address);
        confirmControl(copy);
        copy.textContent = "Copied";
      } catch {
        const selection = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(target.querySelector(".hearth-address"));
        selection.removeAllRanges();
        selection.addRange(range);
      }
    }
    // The copy confirmation resets on the next refresh.
    render(null, target);
    render(html`<h3>Email Hearth</h3>${info.inbox_address ? html`
      <div class="delivery-actions">
        <code class="hearth-address">${info.inbox_address}</code><button type="button" onClick=${copyAddress}>Copy address</button>
      </div>
      <p class="meta">Forward emails here to turn them into proposals in Inbox.</p>` : html`
      <p class="meta">${info.connection_message || info.inbox_error || "Hearth is preparing your AgentMail inbox."}</p>
      ${!info.connected && target.id !== "email-hearth-connection" && html`<a href="#settings/connections">Open Connections</a>`}
    `}`, target);
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
      render(error.message, target);
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

  let reminderSignature;
  let reminderRequest = 0;
  async function reminders({ background } = {}) {
    const target = get("reminders-content");
    const request = ++reminderRequest;
    const { query } = reminderSearch;
    try {
      const result = await refreshAPI(listSearchPath("/api/reminders", query),
        { background, signal: AbortSignal.timeout(6000) });
      if (request !== reminderRequest || query !== reminderSearch.query || currentView() !== "reminders") return;
      if (result.timezone) setTimeZone(result.timezone);
      const count = result.jobs.length + result.delivered.length + result.outbox.length;
      reminderSearch.count(count);
      const signature = JSON.stringify([query, result]);
      if (signature === reminderSignature) return;
      reminderSignature = signature;
      const groups = [
        ["Upcoming", [
          ...result.jobs.filter((job) => !job.snoozed_at),
          ...result.delivered.filter((row) => row.delivery.email?.status === "queued" && !row.delivery.app),
        ]],
        ["Snoozed", result.jobs.filter((job) => job.snoozed_at)],
        ["Delivered", result.delivered.filter((row) => row.delivery.email?.status !== "queued" || row.delivery.app)],
      ];
      const keys = [
        ...groups.flatMap(([name, rows]) => rows.map((row) => `${name}:${row.job_id || row.id}`)),
        ...result.outbox.map((row) => `outbox:${row.id}`),
      ];
      const play = remindersUnfiltered && !query ? prepareListMotion(target, keys) : undefined;
      remindersUnfiltered = !query;
      target.hidden = !!query && !count;
      render(html`<${ReminderList} ...${{ groups, outbox: result.outbox, query, cancelReminder }} />`, target);
      play?.();
    } catch (error) {
      if (!background && request === reminderRequest && query === reminderSearch.query) {
        reminderSearch.fail();
        get("reminders-feedback").textContent = error.message;
      }
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
    const matches = card.search_matches;
    const article = el("article", "card delivery-card inbox-card");
    article.dataset.inbox = card.id;
    const header = el("div", "delivery-card-head");
    header.append(appendHighlighted(el("h4"), matches?.title, card.title), el("span", "meta", formatDate(card.received_at)));
    const chips = el("div", "delivery-chips");
    const category = appendHighlighted(el("span"), matches?.category, kinds[card.proposal.kind]);
    const categoryChip = el("span", "delivery-chip");
    categoryChip.append(category);
    chips.append(categoryChip,
      el("span", `delivery-chip delivery-${card.status === "accepted" ? "sent" : "queued"}`, inboxStatuses[card.status]));
    if (card.automatic) chips.append(el("span", "delivery-chip", "Automatic"));
    const sender = el("p", "meta");
    for (const [key, label] of [["sender", "From"], ["original_sender", "Original sender"]]) {
      if (!card[key]) continue;
      if (sender.hasChildNodes()) sender.append(" · ");
      sender.append(`${label} `);
      const name = card[`${key}_name`];
      appendHighlighted(sender, matches?.[key], name ? `${name} <${card[key]}>` : card[key]);
    }
    if (card.original_date) {
      if (sender.hasChildNodes()) sender.append(" · ");
      sender.append(`Original date ${formatDate(card.original_date)}`);
    }
    article.append(header, chips, sender, appendHighlighted(el("p"), matches?.summary, card.proposal.summary),
      el("p", "inbox-proposal", proposalText(card.proposal)));
    const excerpt = listSearchExcerpt(matches);
    if (excerpt) article.append(excerpt);
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

  async function inbox({ background } = {}) {
    const request = ++inboxRequest;
    const { query } = inboxSearch;
    try {
      const result = await refreshAPI(listSearchPath("/api/inbox", query),
        { background, signal: AbortSignal.timeout(6000) });
      if (request !== inboxRequest || query !== inboxSearch.query || currentView() !== "inbox") return;
      inboxSearch.count(result.cards.length);
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
          row.element.dataset.motionKey = `${row.status === "review" ? "review" : "processed"}:${card.id}`;
        }
        next.set(card.id, row);
        (row.status === "review" ? review : processed).push(row.element);
      }
      for (const id of editing) if (!next.has(id)) editing.delete(id);
      inboxRows = next;
      const keys = [...review, ...processed].map((card) => card.dataset.motionKey);
      const play = inboxUnfiltered && !query ? prepareListMotion(inboxTarget, keys) : undefined;
      inboxUnfiltered = !query;
      inboxTarget.hidden = !!query && !result.cards.length;
      reviewGroup.hidden = !!query && !review.length;
      processedGroup.hidden = !processed.length;
      for (const [group, rows] of [[reviewGroup, review], [processedGroup, processed]]) {
        const title = group.firstElementChild;
        title.firstElementChild.textContent = rows.length;
        reconcileChildren(group, [title, ...(group === reviewGroup && !rows.length ? [reviewEmpty] : rows)]);
      }
      play?.();
    } catch (error) {
      if (!background && request === inboxRequest && query === inboxSearch.query) {
        inboxSearch.fail();
        get("inbox-feedback").textContent = error.message;
      }
    }
  }

  async function checkMail(manual) {
    const feedback = get("inbox-feedback");
    try {
      const result = await api("/api/inbox/poll", manual ? { force: true } : {});
      if (currentView() === "inbox") {
        await inbox({ background: !manual });
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
