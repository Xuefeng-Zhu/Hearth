import { icon, iconButton } from "./icons.js";
import { timeFormatter } from "./time.js";

const kinds = {
  read: ["Read", "book"], idea: ["Idea", "sparkle"], digest: ["Digest", "list"],
  "reminder-context": ["Reminder", "bell"], action: ["Action", "check"],
  "memory-review": ["Memory", "book"], automation: ["Automation", "clock"],
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function button(label, callback, symbol, className = "") {
  const control = element("button", `feed-button ${className}`);
  control.type = "button";
  if (symbol) control.append(icon(symbol, 16));
  control.append(document.createTextNode(label));
  control.addEventListener("click", callback);
  return control;
}

const date = timeFormatter({ month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

export function createFeed({ api, runSuggestion, openChat, openSource, openSettings, openReview }) {
  const root = element("div", "feed-widget");
  const toolbar = element("div", "feed-toolbar");
  const refreshButton = button("Refresh", refresh, "refresh");
  const savedButton = button("Saved", () => switchList(!saved), "bookmark");
  const settingsButton = iconButton("settings", "Feed settings", openSettings, "feed-icon");
  toolbar.append(refreshButton, savedButton, settingsButton);
  const steeringForm = element("form", "feed-steering");
  const label = element("label", "", "Steer your Feed");
  label.htmlFor = "home-feed-steering";
  const steering = element("textarea");
  steering.id = label.htmlFor;
  steering.rows = 2;
  steering.maxLength = 600;
  steering.placeholder = "AI news in the morning, family ideas on Fridays";
  const steerSave = button("Save steering", () => {}, null, "feed-primary");
  steerSave.type = "submit";
  steerSave.hidden = true;
  steeringForm.append(label, steering, steerSave);

  const status = element("p", "feed-status");
  status.setAttribute("role", "status");
  status.tabIndex = -1;
  const scroll = element("div", "feed-scroll");
  scroll.tabIndex = 0;
  scroll.setAttribute("role", "region");
  scroll.setAttribute("aria-label", "Feed cards");
  const list = element("div", "feed-list");
  const more = button("Show more", () => load(true));
  more.hidden = true;
  scroll.append(list, more);
  root.append(toolbar, steeringForm, status, scroll);
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

  function sourceLink(source) {
    const link = element("a", "feed-source", source.label);
    if (source.kind === "web") {
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.title = source.title;
      link.setAttribute("aria-label", `${source.label} · ${source.title}`);
    } else {
      const views = { memory: "memory", reminder: "reminders", chat: "chat", inbox: "inbox",
        task: "reminders", page: "artifacts", artifact: "artifacts" };
      link.href = `#${views[source.kind]}`;
      link.addEventListener("click", (event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        openSource(source).catch((error) => { status.textContent = error.message; });
      });
    }
    return link;
  }

  function card(row) {
    const article = element("article", "feed-card");
    const [name, symbol] = kinds[row.kind];
    const meta = element("div", "feed-meta");
    const kind = element("span", "feed-kind", name);
    kind.prepend(icon(symbol, 15));
    const time = element("time", "", date.format(new Date(row.at)));
    time.dateTime = row.at;
    meta.append(kind, time);
    const title = element("h3", "", row.title);
    title.id = `feed-card-${row.id}`;
    article.setAttribute("aria-labelledby", title.id);
    if (row.kind === "memory-review") {
      const actions = element("div", "feed-actions");
      const review = button("Review proposals", () => perform(review, () => openReview(row.id)), "list", "feed-primary");
      actions.append(review);
      article.append(meta, title, element("p", "feed-copy", row.body), actions);
      return article;
    }
    const sources = element("div", "feed-sources");
    sources.append(...row.links.map(sourceLink));
    const actions = element("div", "feed-actions");
    const feedbackRow = element("div", "feed-feedback-actions");
    const update = async (control, operation) => {
      await perform(control, async () => {
        const next = await api("/api/feed/feedback", { id: row.id, operation });
        const hiddenFromFeed = !saved && ["dismiss", "less"].includes(operation);
        const removedBookmark = saved && operation === "save" && !next.saved;
        if (hiddenFromFeed || removedBookmark) {
          rows = rows.filter((item) => item.id !== row.id);
          const adjacent = article.nextElementSibling || article.previousElementSibling;
          article.remove();
          if (!rows.length && cursor) load(true);
          const focus = adjacent?.querySelector(".feed-icon") || status;
          status.textContent = operation === "less" ? "You’ll see less on this topic."
            : operation === "dismiss" ? "Card dismissed." : "Removed from Saved.";
          focus.focus({ preventScroll: true });
        } else {
          if (operation === "like") row.liked = next.liked;
          if (operation === "save") row.saved = next.saved;
          like.setAttribute("aria-pressed", String(row.liked));
          save.setAttribute("aria-pressed", String(row.saved));
          status.textContent = {
            save: row.saved ? "Saved to your Feed." : "Removed from Saved.",
            like: row.liked ? "You’ll see more on this topic." : "Like removed.",
            less: "You’ll see less on this topic.",
            dismiss: "Card dismissed from your Feed.",
          }[operation];
        }
      });
    };
    const like = iconButton("thumbs-up", "Like", () => update(like, "like"), "feed-icon");
    const less = iconButton("thumbs-down", "Less like this", () => update(less, "less"), "feed-icon");
    const save = iconButton("bookmark", "Save", () => update(save, "save"), "feed-icon");
    const dismiss = iconButton("x", "Dismiss", () => update(dismiss, "dismiss"), "feed-icon");
    like.setAttribute("aria-pressed", String(row.liked));
    save.setAttribute("aria-pressed", String(row.saved));
    feedbackRow.append(like, less, save, dismiss);
    const ask = button("Ask about this", () => perform(ask, async () => {
      const result = await api("/api/feed/chat", { id: row.id });
      await openChat(result.thread, result.draft);
    }), "message");
    if (row.action_label) {
      const primary = button(row.action_label, () => perform(primary, async () => {
        await runSuggestion(row.id);
        await load();
      }), null, "feed-primary");
      actions.append(primary);
    }
    actions.append(ask);
    article.append(meta, title, element("p", "feed-copy", row.body), element("p", "feed-why", row.why),
      sources, actions, feedbackRow);
    if (row.action_label) {
      const options = element("details", "feed-options");
      const menu = element("summary", "", "Suggestion options");
      options.addEventListener("keydown", (event) => {
        if (event.key !== "Escape" || !options.open) return;
        event.preventDefault();
        options.open = false;
        menu.focus();
      });
      const controls = element("div", "feed-actions");
      for (const [caption, operation, extra] of [
        ["Snooze 1 day", "snooze", { days: 1 }], ["Snooze 1 week", "snooze", { days: 7 }],
        ["Mute category", "block", {}],
      ]) {
        const control = button(caption, () => perform(control, async () => {
          await api(`/api/proactivity/${operation}`, { id: row.id, ...extra });
          await load();
          status.textContent = operation === "snooze" ? "Suggestion snoozed." : "Suggestion category muted.";
          status.focus({ preventScroll: true });
        }));
        controls.append(control);
      }
      options.append(menu, controls);
      article.append(options);
    }
    return article;
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
    if (!quiet && !rows.length) status.textContent = "Loading Feed…";
    more.disabled = true;
    try {
      const page = await api(`/api/feed?${params}`);
      if (sequence !== request) return;
      enabled = page.enabled;
      updateSteering(page.steering);
      steeringForm.hidden = !enabled;
      scroll.hidden = !enabled;
      savedButton.disabled = !enabled;
      refreshButton.disabled = !enabled || refreshing;
      savedButton.setAttribute("aria-pressed", String(saved));
      const existing = new Set(rows.map((row) => row.id));
      const incoming = append ? page.cards.filter((row) => !existing.has(row.id)) : page.cards;
      if (append) {
        rows.push(...incoming);
        list.append(...incoming.map(card));
      } else if (JSON.stringify(rows) !== JSON.stringify(incoming)) {
        rows = incoming;
        list.replaceChildren(...rows.map(card));
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
    list.replaceChildren();
    more.hidden = true;
    load();
  }

  async function refresh() {
    if (refreshing) return;
    clearTimeout(polling);
    refreshing = true;
    refreshButton.disabled = true;
    status.textContent = "Refreshing Feed…";
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
    profile.replaceChildren(...config.interests.map((item) =>
      element("li", "", `${item.topic} · ${item.weight > 0 ? "+" : ""}${item.weight}${item.followed ? " · Followed" : ""}`)));
    if (!profile.children.length) profile.append(element("li", "", "Your interests will appear after a Feed refresh."));
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
