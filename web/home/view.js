import { render } from "preact";
import { html, Icon } from "../chat/view.js";

export function mountHome(byId) {
  render(html`
    <div class="home-inner">
      <div class="home-heading split-heading">
        <div class="home-date" id="home-date">
          <time id="home-date-full"></time><time id="home-date-compact"></time>
        </div>
        <button type="button" class="home-edit" id="home-edit" aria-pressed="false" disabled>
          <${Icon} name="grid" size=${17} /><span id="home-edit-label">Edit layout</span>
        </button>
      </div>
      <p class="home-feedback" id="home-feedback" role="status"></p>
      <p class="home-meta" id="home-loading">Loading panels…<span class="loading-skeleton" aria-hidden="true"></span></p>
      <section id="home-approvals" class="automation-section" aria-label="Pending approvals" hidden></section>
      <div id="home-workers" hidden></div>
      <div class="home-grid" id="home-grid"></div>
      <p class="home-empty home-meta" id="home-empty" hidden>All panels are removed. Edit the layout to restore them.</p>
      <div class="home-add-popover" id="home-add-popover" popover="manual" role="dialog"
           aria-labelledby="home-add-title" hidden>
        <header class="home-add-heading">
          <h2 id="home-add-title">Add panel</h2>
          <button type="button" class="home-icon-button" id="home-add-close" aria-label="Close Add panel">
            <${Icon} name="x" size=${18} />
          </button>
        </header>
        <section aria-labelledby="home-add-restore-title">
          <h3 id="home-add-restore-title">Restore</h3>
          <p class="home-meta" id="home-add-restore-empty">No hidden panels.</p>
          <ul class="home-rows" id="home-add-restore-items"></ul>
        </section>
        <section aria-labelledby="home-add-new-title">
          <h3 id="home-add-new-title">New panel</h3>
          <div class="home-add-kinds" id="home-add-kinds"></div>
          <form class="home-add-form" id="home-add-form">
            <label for="home-add-description">Describe a panel…</label>
            <textarea id="home-add-description" rows="2" maxlength="1000" required></textarea>
            <button type="submit" class="home-add-action home-add-submit">Send to Chat</button>
          </form>
        </section>
      </div>
      <button class="home-link" id="home-demo" type="button" hidden>Try sample panels in Chat</button>
    </div>
  `, byId("home-view"));
}

export function Control({ label, action, symbol, className = "home-link", accessibleName, control }) {
  return html`<button type="button" class=${className} aria-label=${accessibleName}
    data-control=${control} onClick=${action}>
    ${symbol && html`<${Icon} name=${symbol} size=${15} />`}<span>${label}</span>
  </button>`;
}

export function IconControl({ label, symbol, action, control, disabled }) {
  return html`<button type="button" class="home-icon-button" title=${label} aria-label=${label}
    data-control=${control} disabled=${disabled} onClick=${action}>
    <${Icon} name=${symbol} size=${18} />
  </button>`;
}

export function Rows({ items, empty, children }) {
  return items.length ? html`<ul class="home-rows">${items.map((item, index) => html`<li>${children(item, index)}</li>`)}</ul>`
    : html`<p class="home-meta">${empty}</p>`;
}

export function DetailLink({ label, href }) {
  return html`<a class="home-link" href=${href} target="_blank" rel="noopener noreferrer">${label}</a>`;
}
