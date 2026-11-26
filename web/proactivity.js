const urgency = { soon: "Time-sensitive", upcoming: "Upcoming", low: "Flexible" };
const kinds = {
  gifts: "Gifts & birthdays", travel: "Travel & bookings", events: "Events & hosting",
  reminders: "Reminder follow-ups", shopping: "Shopping & prices", weather: "Weather & timing",
  planning: "Plans & checklists", research: "Research", other: "Other suggestions",
};
const expiry = new Intl.DateTimeFormat(undefined, {
  month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/Los_Angeles",
});

function node(tag, name, text) {
  const element = document.createElement(tag);
  if (name) element.className = name;
  if (text) element.textContent = text;
  return element;
}

function button(text, className, callback) {
  const element = node("button", className, text);
  element.type = "button";
  element.onclick = callback;
  return element;
}

export function createProactivity({ api, runSuggestion }) {
  const section = document.getElementById("for-you");
  const list = document.getElementById("for-you-cards");
  const empty = document.getElementById("for-you-empty");
  const message = document.getElementById("for-you-feedback");
  const form = document.getElementById("proactivity-settings-form");
  const saved = document.getElementById("proactivity-settings-status");
  const muted = document.getElementById("proactivity-muted");
  let signature;
  let enabled = true;
  let pending = false;

  function card(row) {
    const article = node("article", "suggestion-card");
    const title = node("h3", "", row.title);
    title.id = `suggestion-${row.id}`;
    article.setAttribute("aria-labelledby", title.id);

    const badges = node("div", "suggestion-meta");
    const time = node("time", "", `Until ${expiry.format(new Date(row.expires_at))} PT`);
    time.dateTime = row.expires_at;
    badges.append(node("span", `suggestion-urgency is-${row.urgency}`, urgency[row.urgency]), time);

    const actions = node("div", "suggestion-actions");
    const choices = node("div", "suggestion-snooze");
    choices.id = `snooze-${row.id}`;
    choices.hidden = true;

    async function update(operation, days) {
      if (pending) return;
      pending = true;
      message.textContent = "";
      const focus = document.activeElement;
      for (const control of article.querySelectorAll("button")) control.disabled = true;
      try {
        if (operation === "do") {
          await runSuggestion(row.id);
        } else {
          const result = await api(`/api/proactivity/${operation}`, { id: row.id, ...(days ? { days } : {}) });
          render(result.cards, enabled);
          document.getElementById("for-you-title").focus({ preventScroll: true });
          message.textContent = operation === "snooze" ? `Snoozed for ${days === 1 ? "one day" : "one week"}.`
            : operation === "dismiss" ? "Suggestion dismissed." : `Muted ${kinds[row.kind].toLowerCase()}.`;
        }
      } catch (error) {
        message.textContent = error.message;
      } finally {
        pending = false;
        for (const control of article.querySelectorAll("button")) control.disabled = false;
        if (focus?.isConnected && document.activeElement === document.body) focus.focus();
      }
    }

    const snooze = button("Snooze", "suggestion-secondary", () => {
      choices.hidden = !choices.hidden;
      snooze.setAttribute("aria-expanded", String(!choices.hidden));
      if (!choices.hidden) choices.firstElementChild.focus();
    });
    snooze.setAttribute("aria-expanded", "false");
    snooze.setAttribute("aria-controls", choices.id);
    choices.onkeydown = (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      choices.hidden = true;
      snooze.setAttribute("aria-expanded", "false");
      snooze.focus();
    };
    choices.append(
      button("1 day", "suggestion-secondary", () => update("snooze", 1)),
      button("1 week", "suggestion-secondary", () => update("snooze", 7)),
    );
    actions.append(
      button(row.action_label || "Start in chat", "suggestion-primary", () => update("do")),
      snooze,
      button("Dismiss", "suggestion-secondary", () => update("dismiss")),
    );
    article.append(badges, title, node("p", "suggestion-why", row.why), actions, choices,
      button("Not interested in this kind", "suggestion-mute", () => update("block")));
    return article;
  }

  function render(cards, active) {
    const next = JSON.stringify([cards, active]);
    if (next === signature) return;
    signature = next;
    enabled = active;
    section.hidden = !enabled;
    empty.hidden = !!cards.length;
    list.replaceChildren(...cards.map(card));
  }

  function fill(config) {
    for (const input of form.querySelectorAll("input")) {
      if (input.type === "checkbox") input.checked = config[input.name];
      else input.value = config[input.name];
    }
    muted.textContent = config.blocked.length ? `Muted categories: ${config.blocked.map((kind) => kinds[kind]).join(", ")}.` : "";
  }

  async function settings() {
    try {
      fill(await api("/api/proactivity/settings"));
    } catch (error) {
      saved.textContent = error.message;
    }
  }

  form.onsubmit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(form));
    const submit = form.querySelector("button");
    submit.disabled = true;
    try {
      fill(await api("/api/proactivity/settings", {
        ...values, enabled: form.elements.enabled.checked, email_digest: form.elements.email_digest.checked,
        frequency: Number(values.frequency), max_per_day: Number(values.max_per_day),
      }));
      saved.textContent = "Proactivity settings saved.";
    } catch (error) {
      saved.textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  };
  return { render, settings };
}
