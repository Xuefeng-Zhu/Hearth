import { render } from "preact";
import { confirmControl } from "../motion.js";
import { html, Icon } from "../ui.js";
import { highlighted } from "../list-search-view.js";
import { timeFormatter } from "../time.js";

export const statuses = { queued: "Queued", sent: "Sent", failed: "Failed", canceled: "Canceled" };
export const channels = { app: "In app", email: "Email", both: "Both" };
const icons = { app: ["bell"], email: ["mail"], both: ["bell", "mail"] };
const fmt = timeFormatter({ dateStyle: "medium", timeStyle: "short" });
export const formatDate = (at) => at && Number.isFinite(Date.parse(at)) ? fmt.format(new Date(at)) : "—";

export function ChannelChip({ channel = "app", status, matches }) {
  return html`<span class=${`delivery-chip${status ? ` delivery-${status}` : ""}`}>
    ${icons[channel].map((name) => html`<${Icon} name=${name} size=${14} />`)}
    <span>${highlighted(matches, channels[channel])}${status ? ` · ${statuses[status]}` : ""}</span>
  </span>`;
}

export const inboxKinds = {
  reminder: "Reminder", event: "Event or booking", receipt: "Receipt or order",
  person: "Person or fact", list: "List or plan", other: "Note",
};

export function emailCard(target, info) {
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

export async function loadEmailConnection(api) {
  const target = document.getElementById("email-hearth-connection");
  try {
    emailCard(target, await api("/api/reminders/settings"));
  } catch (error) {
    render(error.message, target);
  }
}
