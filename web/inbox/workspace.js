import { render } from "preact";
import { html } from "../ui.js";
import { listSearchPath } from "../list-search.js";
import { prepareListMotion } from "../motion.js";
import { setTimeZone } from "../time.js";
import { emailCard } from "../reminders/delivery.js";
import { InboxList, InboxView, inboxStatuses } from "./view.js";

const get = (id) => document.getElementById(id);

export function mountInbox() {
  render(html`<${InboxView} />`, get("inbox-view"));
}

export function createInbox({ api, refreshAPI, search, currentView, onInbox, checkMail, pendingPoll }) {
  const target = get("inbox-content");
  const address = get("inbox-address");
  const feedback = get("inbox-feedback");
  let manualPending = false;
  let request = 0;
  let connection;
  let rows = new Map();
  let unfiltered = false;
  let loaded = false;
  let sequence = 0;
  const editing = new Set();
  let review = [];
  let processed = [];
  const showError = (message) => { feedback.textContent = message; };

  function paint(query) {
    render(html`<${InboxList} ...${{ review, processed, query, loaded, editing, edit, cancel, change, showError }} />`, target);
  }

  function edit(id) {
    editing.add(id);
    paint(search.query);
  }

  function cancel(id, control) {
    editing.delete(id);
    paint(search.query);
    control?.focus();
    load();
  }

  async function change(id, operation, fields) {
    try {
      const result = await api(`/api/inbox/${operation}`, { id, ...fields });
      editing.delete(id);
      feedback.textContent = inboxStatuses[result.status] + ".";
      await load();
    } catch (error) {
      showError(error.message);
    }
  }

  async function load({ background } = {}) {
    const current = ++request;
    const { query } = search;
    try {
      const result = await refreshAPI(listSearchPath("/api/inbox", query),
        { background, signal: AbortSignal.timeout(6000) });
      if (current !== request || query !== search.query || currentView() !== "inbox") return;
      search.count(result.cards.length);
      onInbox(result.task_notifications || [], result.approvals || []);
      if (result.settings?.timezone) setTimeZone(result.settings.timezone);
      const signature = JSON.stringify([result.connected, result.inbox_address, result.inbox_error, result.connection_message]);
      if (signature !== connection) {
        connection = signature;
        emailCard(address, result);
      }
      const next = new Map();
      review = [];
      processed = [];
      for (const card of result.cards) {
        const signature = JSON.stringify([card, result.settings?.timezone]);
        let row = rows.get(card.id);
        if (!row || (row.signature !== signature && !editing.has(card.id))) row = { signature, card, key: ++sequence };
        next.set(card.id, row);
        (row.card.status === "review" ? review : processed).push(row);
      }
      for (const id of editing) if (!next.has(id)) editing.delete(id);
      rows = next;
      const keys = [...review.map(({ card }) => `review:${card.id}`), ...processed.map(({ card }) => `processed:${card.id}`)];
      const play = unfiltered && !query ? prepareListMotion(target, keys) : undefined;
      unfiltered = !query;
      loaded = true;
      target.hidden = !!query && !result.cards.length;
      paint(query);
      play?.();
    } catch (error) {
      if (!background && current === request && query === search.query) {
        search.fail();
        showError(error.message);
      }
    }
  }

  const manualCheck = get("inbox-poll");
  manualCheck.addEventListener("click", async () => {
    if (manualPending) return;
    manualPending = true;
    manualCheck.setAttribute("aria-disabled", "true");
    feedback.textContent = "Checking for forwarded email…";
    try {
      await pendingPoll();
      const result = await checkMail(true);
      if (currentView() === "inbox") {
        feedback.textContent = result.processed ? `Processed ${result.processed} email(s).` : "Check complete.";
      }
    } catch (error) {
      showError(error.message);
    } finally {
      manualPending = false;
      manualCheck.removeAttribute("aria-disabled");
    }
  });
  paint("");
  return { load, get manualPending() { return manualPending; } };
}
