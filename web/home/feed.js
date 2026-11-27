import { render } from "preact";
import { html, Icon } from "../chat/view.js";
import { showLoading } from "../motion.js";
import { timeFormatter } from "../time.js";

const kinds = {
  read: ["Read", "book"], idea: ["Idea", "sparkle"], digest: ["Digest", "list"],
  "reminder-context": ["Reminder", "bell"], action: ["Action", "check"],
  "memory-review": ["Memory", "book"], automation: ["Automation", "clock"],
};

function Button({ text, action, symbol, className = "" }) {
  return html`<button type="button" class=${`feed-button ${className}`} onClick=${action}>
    ${symbol && html`<${Icon} name=${symbol} size=${16} />`}${text}
  </button>`;
}

function IconButton({ label, symbol, action, pressed }) {
  return html`<button type="button" class="feed-icon" title=${label} aria-label=${label} aria-pressed=${pressed} onClick=${action}>
    <${Icon} name=${symbol} size=${18} />
  </button>`;
}

const date = timeFormatter({ month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

export function createFeed({ api, runSuggestion, openChat, openSource, openSettings, openReview, approvalCard, refreshHome }) {
  const root = document.createElement("div");
  root.className = "feed-widget";
  render(html`
    <section class="idea-strip" aria-labelledby="feed-ideas-heading" hidden>
      <h3 id="feed-ideas-heading">Ideas</h3>
      <div class="idea-list"></div>
      <p class="feed-status" role="status" tabindex="-1"></p>
      <div class="idea-approval"></div>
    </section>
    <div class="feed-toolbar">
      <${Button} text="Refresh" symbol="refresh" action=${refresh} />
      <${Button} text="Saved" symbol="bookmark" action=${() => switchList(!saved)} />
      <${IconButton} label="Feed settings" symbol="settings" action=${openSettings} />
    </div>
    <form class="feed-steering">
      <label for="home-feed-steering">Steer your Feed</label>
      <textarea id="home-feed-steering" rows="2" maxlength="600" placeholder="AI news in the morning, family ideas on Fridays"></textarea>
      <button type="submit" class="feed-button feed-primary" hidden>Save steering</button>
    </form>
    <p class="feed-status" role="status" tabindex="-1"></p>
    <div class="feed-scroll" tabindex="0" role="region" aria-label="Feed cards">
      <div class="feed-list"></div>
      <button type="button" class="feed-button " hidden onClick=${() => load(true)}>Show more</button>
    </div>
  `, root);
  const [refreshButton, savedButton] = root.querySelectorAll(".feed-toolbar button");
  const steeringForm = root.querySelector(".feed-steering");
  const steering = steeringForm.querySelector("textarea");
  const steerSave = steeringForm.querySelector("button");
  const status = root.querySelector(":scope > .feed-status");
  const scroll = root.querySelector(".feed-scroll");
  const list = scroll.querySelector(".feed-list");
  const more = scroll.querySelector("button");
  const strip = root.querySelector(".idea-strip");
  const ideaList = strip.querySelector(".idea-list");
  const ideaStatus = strip.querySelector(".feed-status");
  const ideaApproval = strip.querySelector(".idea-approval");
  const observer = new IntersectionObserver(([entry]) => {
    if (entry.isIntersecting && !more.hidden) load(true);
  }, { root: scroll });
  observer.observe(more);

  const form = document.getElementById("feed-settings-form");
  const formStatus = document.getElementById("feed-settings-status");
  const profile = document.getElementById("feed-interests");
  let rows = [];
  let saved = false;
  let enabled = true;
  let cursor = null;
  let steeringValue = "";
  let loading = false;
  let refreshing = false;
  let initial = false;
  let lastLoaded = 0;
  let request = 0;
  let polling;

  let ideas = [];

  function renderIdeas() {
    strip.hidden = !enabled || saved || !(ideas.length || ideaApproval.childElementCount || ideaStatus.textContent);
    render(ideas.map((row) => html`<${IdeaCard} key=${row.id} row=${row} />`), ideaList);
  }

  function IdeaCard({ row }) {
    const id = `idea-${row.id}`;
    const symbol = { chat: "message", slides: "slides", reminder: "bell", automation: "clock", watcher: "monitor" }[row.kind];

    async function respond(event, operation) {
      const buttons = event.currentTarget.parentElement.querySelectorAll("button");
      buttons.forEach((control) => { control.disabled = true; });
      ideaStatus.textContent = "";
      try {
        const result = await api("/api/feed/idea", { id: row.id, operation });
        ideas = ideas.filter((idea) => idea.id !== row.id);
        if (result.action) ideaApproval.replaceChildren(approvalCard(result.action, "idea"));
        else if (!result.draft) ideaStatus.textContent = operation === "dismiss" ? "Idea dismissed." : "Similar Ideas will be hidden.";
        renderIdeas();
        if (result.thread) await openChat(result.thread, result.draft);
        else if (result.action) {
          ideaApproval.querySelector("button")?.focus();
          await refreshHome();
        } else ideaStatus.focus();
      } catch (error) {
        ideaStatus.textContent = error.message;
        ideaStatus.focus();
      } finally {
        buttons.forEach((control) => { control.disabled = false; });
      }
    }

    return html`<article class="feed-card idea-card" aria-labelledby=${id}>
      <h4 id=${id}>${row.title}</h4><p class="home-meta">${row.detail}</p>
      <div class="feed-actions">
        <${Button} text=${row.action_label} symbol=${symbol} className="feed-primary" action=${(event) => respond(event, "open")} />
        <${IconButton} label="Dismiss" symbol="x" action=${(event) => respond(event, "dismiss")} />
        <${Button} text="Not interested" action=${(event) => respond(event, "not-interested")} />
      </div>
    </article>`;
  }

  function Source({ source }) {
    const { label, title, kind } = source;
    if (kind === "web") return html`<a class="feed-source" href=${source.url} target="_blank" rel="noopener noreferrer"
      title=${title} aria-label=${`${label} · ${title}`}>${label}</a>`;
    const views = { memory: "memory", reminder: "reminders", chat: "chat", inbox: "inbox",
      task: "reminders", page: "artifacts", artifact: "artifacts" };
    return html`<a class="feed-source" href=${`#${views[kind]}`} onClick=${(event) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      openSource(source).catch((error) => { status.textContent = error.message; });
    }}>${label}</a>`;
  }

  function renderCards() {
    render(rows.map((row) => html`<${Card} key=${row.id} row=${row} />`), list);
  }

  function Card({ row }) {
    const id = `feed-card-${row.id}`;
    const [name, symbol] = kinds[row.kind];
    const isReview = row.kind === "memory-review";
    const update = (event, operation) => {
      const control = event.currentTarget;
      const article = control.closest("article");
      const wasSaved = saved;
      return perform(control, async () => {
        const next = await api("/api/feed/feedback", { id: row.id, operation });
        if (saved !== wasSaved) {
          await load(false, true);
          return;
        }
        const hiddenFromFeed = !saved && ["dismiss", "less"].includes(operation);
        const removedBookmark = saved && operation === "save" && !next.saved;
        if (hiddenFromFeed || removedBookmark) {
          const adjacent = article.nextElementSibling || article.previousElementSibling;
          rows = rows.filter((item) => item.id !== row.id);
          renderCards();
          if (!rows.length && cursor) load(true);
          const focus = adjacent?.querySelector(".feed-icon") || status;
          status.textContent = operation === "less" ? "You’ll see less on this topic."
            : operation === "dismiss" ? "Card dismissed." : "Removed from Saved.";
          focus.focus({ preventScroll: true });
        } else {
          const current = rows.find((item) => item.id === row.id);
          if (current && operation === "like") current.liked = next.liked;
          if (current && operation === "save") current.saved = next.saved;
          renderCards();
          status.textContent = {
            save: next.saved ? "Saved to your Feed." : "Removed from Saved.",
            like: next.liked ? "You’ll see more on this topic." : "Like removed.",
            less: "You’ll see less on this topic.",
            dismiss: "Card dismissed from your Feed.",
          }[operation];
        }
      });
    };
    const ask = (event) => perform(event.currentTarget, async () => {
      const result = await api("/api/feed/chat", { id: row.id });
      await openChat(result.thread, result.draft);
    });
    const run = (event) => perform(event.currentTarget, async () => {
      await runSuggestion(row.id);
      await load();
    });
    const suggestionOptions = [
      ["Snooze 1 day", "snooze", { days: 1 }], ["Snooze 1 week", "snooze", { days: 7 }], ["Mute category", "block", {}],
    ];
    const dismissOptions = (event) => {
      const options = event.currentTarget;
      if (event.key !== "Escape" || !options.open) return;
      event.preventDefault();
      options.open = false;
      options.firstElementChild.focus();
    };
    return html`<article class="feed-card" aria-labelledby=${id}>
      <div class="feed-meta">
        <span class="feed-kind"><${Icon} name=${symbol} size=${15} />${name}</span>
        <time datetime=${row.at}>${date.format(new Date(row.at))}</time>
      </div>
      <h3 id=${id}>${row.title}</h3>
      <p class="feed-copy">${row.body}</p>
      ${isReview ? html`<div class="feed-actions">
        <${Button} text="Review proposals" symbol="list" className="feed-primary"
          action=${(event) => perform(event.currentTarget, () => openReview(row.id))} />
      </div>` : html`
        <p class="feed-why">${row.why}</p>
        <div class="feed-sources">${row.links.map((source) => html`<${Source} source=${source} />`)}</div>
        <div class="feed-actions">
          ${row.action_label && html`<${Button} text=${row.action_label} action=${run} className="feed-primary" />`}
          <${Button} text="Ask about this" symbol="message" action=${ask} />
        </div>
        <div class="feed-feedback-actions">
          <${IconButton} label="Like" symbol="thumbs-up" pressed=${String(row.liked)} action=${(event) => update(event, "like")} />
          <${IconButton} label="Less like this" symbol="thumbs-down" action=${(event) => update(event, "less")} />
          <${IconButton} label="Save" symbol="bookmark" pressed=${String(row.saved)} action=${(event) => update(event, "save")} />
          <${IconButton} label="Dismiss" symbol="x" action=${(event) => update(event, "dismiss")} />
        </div>
        ${row.action_label && html`<details class="feed-options" onKeyDown=${dismissOptions}>
          <summary>Suggestion options</summary>
          <div class="feed-actions">${suggestionOptions.map(([text, operation, extra]) => html`
            <${Button} text=${text} action=${(event) => perform(event.currentTarget, async () => {
              await api(`/api/proactivity/${operation}`, { id: row.id, ...extra });
              await load();
              status.textContent = operation === "snooze" ? "Suggestion snoozed." : "Suggestion category muted.";
              status.focus({ preventScroll: true });
            })} />`)}
          </div>
        </details>`}
      `}
    </article>`;
  }

  async function perform(control, callback) {
    control.disabled = true;
    try {
      await callback();
    } catch (error) {
      status.textContent = error.message;
    } finally {
      control.disabled = false;
    }
  }

  function updateSteering(value) {
    if (steering.value === steeringValue) steering.value = value;
    steeringValue = value;
    steerSave.hidden = steering.value === steeringValue;
  }

  async function load(append = false, quiet = false) {
    if (append && (loading || !cursor)) return;
    const sequence = ++request;
    const params = new URLSearchParams({ saved: saved ? "1" : "0" });
    if (append) params.set("cursor", cursor);
    loading = true;
    if (!quiet && !rows.length) showLoading(status, "Loading Feed…");
    more.disabled = true;
    try {
      const page = await api(`/api/feed?${params}`);
      if (sequence !== request) return;
      enabled = page.enabled;
      if (!append) {
        const incomingIdeas = page.ideas || [];
        if (JSON.stringify(ideas) !== JSON.stringify(incomingIdeas)) {
          ideas = incomingIdeas;
          renderIdeas();
        } else {
          strip.hidden = !enabled || saved || !(ideas.length || ideaApproval.childElementCount || ideaStatus.textContent);
        }
      }
      updateSteering(page.steering);
      steeringForm.hidden = !enabled;
      scroll.hidden = !enabled;
      savedButton.disabled = !enabled;
      refreshButton.disabled = !enabled || refreshing;
      savedButton.setAttribute("aria-pressed", String(saved));
      const existing = new Set(rows.map((row) => row.id));
      const incoming = append ? page.cards.filter((row) => !existing.has(row.id)) : page.cards;
      if (append ? incoming.length : JSON.stringify(rows) !== JSON.stringify(incoming)) {
        rows = append ? [...rows, ...incoming] : incoming;
        renderCards();
      }
      cursor = page.next_cursor;
      more.hidden = !cursor;
      status.textContent = !enabled ? "Feed is off. Turn it on in Feed settings." : page.error ||
        (rows.length ? "" : saved ? "No saved cards yet." : "You’re caught up. Refresh to check for new cards.");
      initial = true;
      lastLoaded = Date.now();
    } catch (error) {
      if (sequence === request) {
        status.textContent = error.message;
        if (!append) refreshButton.disabled = false;
      }
    } finally {
      if (sequence === request) {
        loading = false;
        more.disabled = false;
      }
    }
  }

  function switchList(value) {
    if (saved === value) return;
    saved = value;
    rows = [];
    cursor = null;
    scroll.scrollTop = 0;
    renderCards();
    more.hidden = true;
    load();
  }

  async function refresh() {
    if (refreshing) return;
    clearTimeout(polling);
    refreshing = true;
    refreshButton.disabled = true;
    showLoading(status, "Refreshing Feed…");
    try {
      const result = await api("/api/feed/refresh", {});
      await load(false, true);
      if (result.status === "busy") {
        status.textContent = "A Feed refresh is running…";
        const waitForRun = async (attempt = 0) => {
          if (attempt === 24 || !root.isConnected) return;
          const page = await api("/api/feed").catch(() => null);
          if (!page?.running) return load(false, true);
          polling = setTimeout(() => waitForRun(attempt + 1), 5000);
        };
        polling = setTimeout(waitForRun, 3000);
      } else if (result.status === "quiet") {
        status.textContent = `Quiet hours end ${date.format(new Date(result.until))}.`;
      } else if (result.status === "interrupted" || result.status === "restoring") {
        status.textContent = "Refresh paused while the workspace changed. Try again.";
      } else if (result.error) {
        status.textContent = result.error;
      } else if (!saved && result.cards.length) {
        status.textContent = `${result.cards.length} new ${result.cards.length === 1 ? "card" : "cards"}.`;
      }
    } catch (error) {
      status.textContent = error.message;
    } finally {
      refreshing = false;
      refreshButton.disabled = !enabled;
    }
  }

  steering.addEventListener("input", () => { steerSave.hidden = steering.value === steeringValue; });
  steeringForm.addEventListener("submit", (event) => {
    event.preventDefault();
    return perform(steerSave, async () => {
      const config = await api("/api/feed/settings", { steering: steering.value });
      steering.value = config.steering;
      updateSteering(config.steering);
      status.textContent = "Steering saved for the next refresh.";
      status.focus({ preventScroll: true });
    });
  });

  function fill(config) {
    form.elements.enabled.checked = config.enabled;
    form.elements.frequency.value = config.frequency;
    form.elements.steering.value = config.steering;
    for (const key of ["follow", "mute"]) form.elements[key].value = config[key].join("\n");
    render(config.interests.length ? config.interests.map((item) => html`<li>
      ${item.topic} · ${item.weight > 0 ? "+" : ""}${item.weight}${item.followed ? " · Followed" : ""}
    </li>`) : html`<li>Your interests will appear after a Feed refresh.</li>`, profile);
    updateSteering(config.steering);
  }

  async function settings() {
    formStatus.textContent = "";
    try {
      fill(await api("/api/feed/settings"));
    } catch (error) {
      formStatus.textContent = error.message;
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = form.querySelector("[type=submit]");
    submit.disabled = true;
    const values = form.elements;
    const topics = (key) => values[key].value.split(/[,\n]/).map((value) => value.trim()).filter(Boolean);
    try {
      fill(await api("/api/feed/settings", {
        enabled: values.enabled.checked, frequency: values.frequency.valueAsNumber,
        steering: values.steering.value, follow: topics("follow"), mute: topics("mute"),
      }));
      formStatus.textContent = "Feed settings saved.";
      initial = false;
    } catch (error) {
      formStatus.textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  });

  return { root, settings, show(reload = false) {
    if (loading || refreshing) return;
    if (reload || !initial || (Date.now() - lastLoaded > 30000 && scroll.scrollTop < 5 && !root.contains(document.activeElement))) {
      load(false, initial);
    }
  } };
}
