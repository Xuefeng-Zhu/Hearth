import { useLayoutEffect, useRef } from "preact/hooks";
import { html } from "../chat/view.js";
import { highlighted, ListSearchExcerpt } from "../list-search-view.js";
import { formatDate } from "../reminders/view.js";
import { localInputTime, localTimeToISO } from "../time.js";

export const kinds = {
  reminder: "Reminder", event: "Event or booking", receipt: "Receipt or order",
  person: "Person or fact", list: "List or plan", other: "Note",
};
export const inboxStatuses = {
  review: "Needs review", accepted: "Accepted", dismissed: "Dismissed", undone: "Undone",
};

export function InboxView() {
  return html`
    <div class="section-intro split-heading delivery-intro">
      <div><h2>Email Inbox</h2><p>Review what Hearth found in your forwarded mail.</p></div>
      <button type="button" id="inbox-poll">Check mail</button>
    </div>
    <div id="inbox-search" class="list-search"></div>
    <div id="inbox-address" class="card email-hearth-card"></div>
    <p id="inbox-feedback" class="meta" role="status"></p>
    <section id="inbox-approvals" class="automation-section" aria-label="Approvals" hidden></section>
    <section id="inbox-runs" class="automation-section" aria-label="Recurring task results" hidden></section>
    <div id="inbox-search-empty" class="list-search-empty" hidden></div>
    <div id="inbox-content" class="list-search-results"></div>
  `;
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

function Sender({ card, matches }) {
  const senders = [["sender", "From"], ["original_sender", "Original sender"]].filter(([key]) => card[key]);
  return html`<p class="meta">
    ${senders.map(([key, label], index) => {
      const name = card[`${key}_name`];
      return html`${index ? " · " : ""}${label} ${highlighted(matches?.[key], name ? `${name} <${card[key]}>` : card[key])}`;
    })}
    ${card.original_date && `${senders.length ? " · " : ""}Original date ${formatDate(card.original_date)}`}
  </p>`;
}

function Source({ card }) {
  if (!card.body && !card.attachments.length) return null;
  return html`<details class="inbox-source">
    <summary>Email text and attachments</summary>
    ${card.body && html`<pre>${card.body}</pre>`}
    ${card.attachments.map((attachment) => html`<details class="inbox-source">
      <summary>${[attachment.name, attachment.type, attachment.size == null ? "" : `${attachment.size.toLocaleString()} bytes`]
        .filter(Boolean).join(" · ")}</summary>
      ${attachment.text ? html`<pre>${attachment.text}</pre>` : html`<p class="meta">${attachment.note || "Metadata only"}</p>`}
    </details>`)}
  </details>`;
}

function Editor({ proposal, save, cancel, showError }) {
  const titleInput = useRef(null);
  const kindSelect = useRef(null);
  const initialAt = proposal.at && Number.isFinite(Date.parse(proposal.at)) ? localInputTime(proposal.at) : "";
  useLayoutEffect(() => {
    kindSelect.current.value = proposal.kind;
    titleInput.current.focus();
  }, []);
  async function submit(event) {
    event.preventDefault();
    const control = event.submitter || event.currentTarget.querySelector("button[type=submit]");
    if (control.disabled) return;
    const { title, kind, at, summary } = Object.fromEntries(new FormData(event.currentTarget));
    control.disabled = true;
    try {
      const editedAt = at === initialAt ? proposal.at : at ? localTimeToISO(at) : null;
      await save({ title, kind, at: editedAt, summary });
    } catch (error) {
      showError(error.message);
    } finally {
      control.disabled = false;
    }
  }
  return html`<form class="delivery-form inbox-edit" onSubmit=${submit}>
    <label>Title<input ref=${titleInput} name="title" maxlength="240" required defaultValue=${proposal.title} /></label>
    <label>Proposal type<select ref=${kindSelect} name="kind">
      ${Object.entries(kinds).map(([value, label]) => html`<option key=${value} value=${value}>${label}</option>`)}
    </select></label>
    <label>Date and time<input type="datetime-local" name="at" defaultValue=${initialAt} /></label>
    <label>Summary<textarea name="summary" rows="2" maxlength="2000" defaultValue=${proposal.summary} /></label>
    <div class="delivery-actions delivery-full">
      <button type="submit" class="primary-setting">Save and accept</button>
      <button type="button" onClick=${cancel}>Cancel</button>
    </div>
  </form>`;
}

function InboxCard({ card, group, sourceKey, editing, edit, cancel, change, showError }) {
  const matches = card.search_matches;
  const editButton = useRef(null);
  return html`<article class="card delivery-card inbox-card" data-inbox=${card.id} data-motion-key=${`${group}:${card.id}`}>
    <div class="delivery-card-head">
      <h4>${highlighted(matches?.title, card.title)}</h4>
      <span class="meta">${formatDate(card.received_at)}</span>
    </div>
    <div class="delivery-chips">
      <span class="delivery-chip"><span>${highlighted(matches?.category, kinds[card.proposal.kind])}</span></span>
      <span class=${`delivery-chip delivery-${card.status === "accepted" ? "sent" : "queued"}`}>${inboxStatuses[card.status]}</span>
      ${card.automatic && html`<span class="delivery-chip">Automatic</span>`}
    </div>
    <${Sender} ...${{ card, matches }} />
    <p>${highlighted(matches?.summary, card.proposal.summary)}</p>
    <p class="inbox-proposal">${proposalText(card.proposal)}</p>
    <${ListSearchExcerpt} matches=${matches} />
    ${card.suspicious ? html`<p class="meta">Contains instruction-like text. Review required.</p>`
      : !card.authenticated && card.status === "review" && html`
        <p class="meta">${card.allowlisted ? "Sender authentication could not be verified." : "Sender is outside your allowlist."}</p>`}
    <${Source} key=${sourceKey} card=${card} />
    ${card.status === "review" ? html`<div class="delivery-actions" hidden=${editing}>
      <button type="button" class="primary-setting" onClick=${() => change(card.id, "accept")}>Accept</button>
      <button type="button" ref=${editButton} onClick=${() => edit(card.id)}>Edit</button>
      <button type="button" onClick=${() => change(card.id, "dismiss")}>Dismiss</button>
    </div>` : card.status === "accepted" && html`<div class="delivery-actions">
      <button type="button" onClick=${() => change(card.id, "undo")}>Undo</button>
    </div>`}
    ${editing && html`<${Editor} proposal=${card.proposal} save=${(fields) => change(card.id, "edit", fields)}
      cancel=${() => cancel(card.id, editButton.current)} showError=${showError} />`}
  </article>`;
}

export function InboxList({ review, processed, query, loaded, editing, ...actions }) {
  const cards = (rows, group) => rows.map(({ card, key }) => html`
    <${InboxCard} key=${card.id} sourceKey=${key} ...${{ card, group }} editing=${editing.has(card.id)} ...${actions} />`);
  return html`
    <section class="delivery-section" hidden=${!!query && !review.length}>
      <h3>Review<span class="delivery-count">${review.length}</span></h3>
      ${review.length ? cards(review, "review") : loaded && html`<p class="delivery-empty">No email waiting for review.</p>`}
    </section>
    <section class="delivery-section" hidden=${!processed.length}>
      <h3>Processed<span class="delivery-count">${processed.length}</span></h3>
      ${cards(processed, "processed")}
    </section>
  `;
}
