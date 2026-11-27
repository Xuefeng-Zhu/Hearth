import { render } from "preact";
import { html } from "../chat/view.js";

function Automation() {
  return html`
    <div class="automation-controls event-automation-toolbar">
      <button type="button" class="settings-button primary-setting automation-button" id="new-event-automation" disabled>
        <span data-icon="plus"></span>New automation
      </button>
    </div>
    <p class="meta automation-feedback" id="event-automation-status" role="status"></p>
    <div id="event-automation-approval"></div>
    <div id="event-automation-list" class="automation-approval-list"></div>
  `;
}

function Watchers() {
  return html`
    <section class="card brain-form" aria-labelledby="watcher-status-title">
      <h3 id="watcher-status-title">Apify watchers are blocked</h3>
      <p class="meta">The Sprites gateway denied the Apify access checks needed to verify Actor runs. Hearth does not start Apify Actors for watchers.</p>
      <p class="meta">Page and price watchers from Home → Feed → Ideas use Hearth’s public-page reader. Manage approved watchers in Reminders → Recurring tasks.</p>
    </section>
  `;
}

function Approvals() {
  return html`
    <form id="approval-settings-form" class="card brain-form approval-settings">
      <div id="approval-policies"></div>
      <p class="meta">Reminders and task updates can email your configured recipient. Scheduled tools still ask before sending, spending, publishing, or deleting.</p>
      <div class="action-row"><button type="submit" class="primary-setting">Save settings</button></div>
      <p class="meta" id="approval-settings-feedback" role="status"></p>
    </form>
  `;
}

function Weather() {
  return html`
    <form id="weather-settings-form" class="card brain-form">
      <label for="weather-location">Weather location</label>
      <input id="weather-location" name="location" type="text" placeholder="San Francisco, CA" minlength="2" maxlength="120" required />
      <p class="meta">Enter a city and region, or a postal code. The clock uses Pacific time.</p>
      <div class="action-row">
        <button type="submit" class="primary-setting" id="weather-location-save">Save location</button>
      </div>
      <p class="meta" id="weather-settings-status" role="status"></p>
    </form>
  `;
}

function Feed() {
  return html`
    <form id="feed-settings-form" class="card brain-form">
      <label class="check-label"><input name="enabled" type="checkbox" /> Enable Feed</label>
      <label>Refresh every (minutes)<input name="frequency" type="number" min="30" max="1440" required /></label>
      <p class="meta">Refreshes respect the quiet hours in Action suggestions.</p>
      <label>Steer your Feed<textarea name="steering" maxlength="600" rows="3"
        placeholder="AI and hackathon news in the morning, family weekend ideas on Fridays"></textarea></label>
      <label>Topics to follow<textarea name="follow" rows="3" placeholder="One public topic per line"></textarea></label>
      <label>Topics to mute<textarea name="mute" rows="3" placeholder="One topic per line"></textarea></label>
      <h3>Your interest profile</h3>
      <p class="meta">Hearth derives interests from Memory. Follow or mute any topic above to edit the profile. Card feedback adjusts the scores.</p>
      <ul id="feed-interests" class="feed-interests"></ul>
      <div class="action-row"><button type="submit" class="primary-setting">Save settings</button></div>
      <p class="meta" id="feed-settings-status" role="status"></p>
    </form>
  `;
}

function Proactivity() {
  return html`
    <form id="proactivity-settings-form" class="card brain-form">
      <fieldset class="preference-fields delivery-form">
        <legend>Action suggestions in Feed</legend>
        <label class="check-label delivery-full"><input name="enabled" type="checkbox" /> Generate Action suggestions</label>
        <label>Check every (minutes)<input name="frequency" type="number" min="30" max="720" required /></label>
        <label>Maximum suggestions per day<input name="max_per_day" type="number" min="1" max="12" required /></label>
        <label>Quiet hours start<input name="quiet_start" type="time" required /></label>
        <label>Quiet hours end<input name="quiet_end" type="time" required /></label>
        <p class="meta delivery-full">Quiet hours use Pacific time. Identical start and end times turn quiet hours off.</p>
        <label class="check-label delivery-full"><input name="email_digest" type="checkbox" /> Email a daily digest</label>
        <p class="meta delivery-full">The digest uses the email recipient set in Reminders.</p>
      </fieldset>
      <p class="meta" id="proactivity-muted"></p>
      <div class="action-row"><button type="submit" class="primary-setting">Save settings</button></div>
      <p class="meta" id="proactivity-settings-status" role="status"></p>
    </form>
  `;
}

function Delivery() {
  return html`
    <div class="settings-layout reminder-settings-layout">
      <form id="reminder-settings-form" class="card brain-form">
        <fieldset class="preference-fields delivery-form">
          <legend>Delivery</legend>
          <label>Default channel<select name="channel"><option value="app">In app</option><option value="email">Email</option><option value="both">Both</option></select></label>
          <label>Recipient email<input name="recipient" type="email" maxlength="254" autocomplete="email" placeholder="you@example.com" /></label>
          <label>Quiet hours start<input name="quiet_start" type="time" required /></label>
          <label>Quiet hours end<input name="quiet_end" type="time" required /></label>
          <label class="delivery-full">Time zone<input name="timezone" required maxlength="100" /></label>
          <p class="meta delivery-full">Email waits until quiet hours end. Urgent reminders can arrive at any time.</p>
        </fieldset>
        <fieldset class="preference-fields delivery-form">
          <legend>Forwarded mail</legend>
          <label class="delivery-full">Allowed senders<textarea name="allowed_senders" rows="3" maxlength="12000" placeholder="One email address per line"></textarea></label>
          <p class="meta delivery-full">Items from other senders wait for your review.</p>
          <div class="delivery-full"><span class="delivery-label">Auto-accept from allowed senders</span>
            <div class="delivery-options" id="inbox-auto-kinds"></div>
          </div>
          <label class="check-label delivery-full"><input name="acknowledge" type="checkbox" /> Acknowledge accepted mail from allowed senders</label>
        </fieldset>
        <div class="action-row"><button type="submit" class="primary-setting">Save settings</button></div>
        <p id="reminder-settings-feedback" class="meta" role="status"></p>
      </form>
      <div class="settings-stack">
        <section id="reminder-email-connection" class="card email-hearth-card" aria-label="Email Hearth"></section>
        <section class="card email-hearth-card" aria-labelledby="reminder-test-title">
          <h3 id="reminder-test-title">Test channels</h3>
          <div class="delivery-actions">
            <button type="button" data-reminder-test="app">Send test in app</button>
            <button type="button" data-reminder-test="email">Send test email</button>
          </div>
          <p id="reminder-test-feedback" class="meta" role="status"></p>
        </section>
        <section class="card email-hearth-card" aria-labelledby="reminder-wake-title">
          <h3 id="reminder-wake-title">Scheduler wake status</h3>
          <dl class="delivery-details">
            <div><dt>Last tick</dt><dd id="reminder-last-tick">—</dd></div>
            <div><dt>Next due</dt><dd id="reminder-next-due">—</dd></div>
          </dl>
        </section>
      </div>
    </div>
  `;
}

function ArtifactSync() {
  return html`
    <form id="artifact-settings-form" class="card brain-form">
      <label class="check-label"><input id="artifact-auto-save" type="checkbox" checked /> Auto-save to Box</label>
      <label for="artifact-folder">Box folder name</label>
      <input id="artifact-folder" type="text" required maxlength="80" value="Hearth" />
      <p id="artifact-settings-connection" class="meta"></p>
      <div class="action-row"><button class="primary-setting" type="submit">Save settings</button></div>
      <p id="artifact-settings-status" class="meta" role="status"></p>
    </form>
  `;
}

export function mountSupportingSections(byId) {
  const sections = { automations: Automation, watchers: Watchers, approvals: Approvals, home: Weather,
    feed: Feed, proactivity: Proactivity, reminders: Delivery, artifacts: ArtifactSync };
  for (const [section, Component] of Object.entries(sections)) {
    render(html`<${Component} />`, byId(`settings-${section}`));
  }
}
