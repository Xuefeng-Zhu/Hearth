import { render } from "preact";
import { html, Icon } from "../ui.js";
import { highlighted, ListSearchExcerpt } from "../list-search-view.js";
import { formatDate, ChannelChip, channels } from "./delivery.js";

export function mountReminders(byId) {
  render(html`
    <div class="section-intro split-heading delivery-intro">
      <div><h2>Reminders</h2><p>See what’s coming up and what reached each channel.</p></div>
      <button type="button" id="open-reminder-settings">Reminder settings</button>
    </div>
    <div id="reminders-search" class="list-search"></div>
    <details class="card reminder-create" id="reminder-create">
      <summary>New reminder</summary>
      <form class="delivery-form" id="reminder-create-form">
        <label class="delivery-full">Title<input name="message" required maxlength="800" /></label>
        <label>When<input name="at" type="datetime-local" required /></label>
        <label>Channel<select name="channel"><option value="">Settings default</option><option value="app">In app</option><option value="email">Email</option><option value="both">Both</option></select></label>
        <label class="delivery-full">Note<textarea name="note" rows="2" maxlength="4000"></textarea></label>
        <label class="check-label delivery-full"><input name="urgent" type="checkbox" /> Urgent · send during quiet hours</label>
        <div class="action-row delivery-full"><button class="primary-setting" type="submit">Schedule reminder</button></div>
      </form>
    </details>
    <p id="reminders-feedback" class="meta" role="status"></p>
    <div id="reminders-search-empty" class="list-search-empty" hidden></div>
    <div id="reminders-content" class="list-search-results"></div>
  `, byId("reminders-panel"));
}

function Reminder({ row, name, cancelReminder }) {
  const matches = row.search_matches;
  const id = row.job_id || row.id;
  const deliveries = Object.entries(row.delivery);
  const detail = [row.late_minutes ? `Late by ${row.late_minutes}m` : "", row.action?.label,
    row.cron ? `Repeats · ${row.cron} UTC` : ""].filter(Boolean).join(" · ");
  return html`<article class="card delivery-card" data-reminder=${id} data-motion-key=${`${name}:${id}`}>
    <div class="delivery-card-head">
      <h4>${highlighted(matches?.title, row.message)}</h4>
      <span class="meta">${highlighted(matches?.due, row.due_text ?? formatDate(row.next_at || row.scheduled_at))}</span>
    </div>
    <div class="delivery-chips">${deliveries.map(([channel, delivery]) =>
      html`<${ChannelChip} channel=${channel} status=${delivery.status} matches=${matches?.[channel]} />`)}</div>
    ${row.note && html`<p class="delivery-note">${highlighted(matches?.note, row.note)}</p>`}
    <${ListSearchExcerpt} matches=${matches} />
    ${deliveries.map(([channel, delivery]) => (delivery.reason || delivery.sending) && html`<p class="meta">
      ${channels[channel]} · ${delivery.sending ? "Sending reminder" : delivery.reason}
      ${delivery.next_at && delivery.status === "queued" && !delivery.sending
        ? ` · Next attempt ${formatDate(delivery.next_at)}` : ""}
      ${delivery.reason?.startsWith("Not connected") && html`${" · "}<a href="#settings/connections">Connections</a>`}
    </p>`)}
    ${detail && html`<p class="meta">${detail}</p>`}
    ${row.cancelable && html`<div class="delivery-actions"><button type="button" onClick=${() => cancelReminder(id)}>Undo</button></div>`}
  </article>`;
}

function Outbox({ row }) {
  const matches = row.search_matches;
  return html`<article class="card delivery-card" data-motion-key=${`outbox:${row.id}`}>
    <a href=${`/api/reminders/outbox?id=${encodeURIComponent(row.id)}`} target="_blank" rel="noopener">
      ${highlighted(matches?.title, row.subject)}
    </a>
    <p class="meta">${highlighted(matches?.due, row.due_text ?? formatDate(row.created_at))}${" · Demo copy"}</p>
    <${ListSearchExcerpt} matches=${matches} />
  </article>`;
}

function Group({ name, count, children }) {
  return html`<section class="delivery-section">
    <h3>${name}<span class="delivery-count">${count}</span></h3>${children}
  </section>`;
}

export function ReminderList({ groups, outbox, query, cancelReminder }) {
  return html`
    ${groups.map(([name, rows]) => (!query || rows.length > 0) && html`
      <${Group} key=${name} name=${name} count=${rows.length}>
        ${rows.length ? rows.map((row) => html`<${Reminder} key=${row.id} ...${{ row, name, cancelReminder }} />`)
          : html`<p class="delivery-empty">No ${name.toLowerCase()} reminders.</p>`}
      </${Group}>`)}
    ${outbox.length ? html`<${Group} name="Outbox" count=${outbox.length}>
      ${outbox.map((row) => html`<${Outbox} key=${row.id} row=${row} />`)}
    </${Group}>` : null}
  `;
}
