const kinds = {
  gifts: "Gifts & birthdays", travel: "Travel & bookings", events: "Events & hosting",
  reminders: "Reminder follow-ups", shopping: "Shopping & prices", weather: "Weather & timing",
  planning: "Plans & checklists", research: "Research", other: "Other suggestions",
};
export function createProactivity({ api }) {
  const form = document.getElementById("proactivity-settings-form");
  const saved = document.getElementById("proactivity-settings-status");
  const muted = document.getElementById("proactivity-muted");

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
  return { settings };
}
