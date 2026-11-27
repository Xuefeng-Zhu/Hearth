import { render } from "preact";
import { html } from "../ui.js";
import { node as el, button } from "../dom.js";
import { ReminderList } from "./view.js";
import { formatDate, statuses, inboxKinds as kinds, emailCard } from "./delivery.js";
import { localInputTime, localTimeToISO, setTimeZone } from "../time.js";
import { listSearchPath } from "../list-search.js";
import { prepareListMotion } from "../motion.js";

const get = (id) => document.getElementById(id);

export function createReminders({ api, refreshAPI, openView, openSettings, startSending, stopSending,
  currentView, currentSettings }) {
  let form, options, reminderSearch;
  let remindersUnfiltered = false;

  function wakeStatus(info) {
    emailCard(get("reminder-email-connection"), info);
    get("reminder-last-tick").textContent = formatDate(info.last_tick);
    get("reminder-next-due").textContent = formatDate(info.next_due);
  }

  function loadForm(info) {
    setTimeZone(info.settings.timezone);
    for (const [key, value] of Object.entries(info.settings)) {
      if (key === "auto_accept") continue;
      const control = form.elements[key];
      if (control.type === "checkbox") control.checked = value;
      else control.value = Array.isArray(value) ? value.join("\n") : value;
    }
    for (const input of options.querySelectorAll("input")) input.checked = info.settings.auto_accept.includes(input.value);
    wakeStatus(info);
  }

  async function settings() {
    if (!form) {
      form = get("reminder-settings-form");
      options = get("inbox-auto-kinds");
      for (const [value, label] of Object.entries(kinds)) {
        const check = el("input");
        check.type = "checkbox";
        check.name = "auto_accept";
        check.value = value;
        const wrapper = el("label", "check-label");
        wrapper.append(check, document.createTextNode(label));
        options.append(wrapper);
      }

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const feedback = get("reminder-settings-feedback");
        const save = form.querySelector("button[type=submit]");
        save.disabled = true;
        feedback.textContent = "Saving settings…";
        const body = Object.fromEntries(new FormData(form));
        body.allowed_senders = body.allowed_senders.split(/[\n,]+/).map((entry) => entry.trim()).filter(Boolean);
        body.auto_accept = [...options.querySelectorAll("input:checked")].map((entry) => entry.value);
        body.acknowledge = form.elements.acknowledge.checked;
        try {
          loadForm(await api("/api/reminders/settings", body));
          feedback.textContent = "Reminder settings saved.";
        } catch (error) {
          feedback.textContent = error.message;
        } finally {
          save.disabled = false;
        }
      });

      for (const item of document.querySelectorAll("[data-reminder-test]")) {
        item.addEventListener("click", async () => {
          const channel = item.dataset.reminderTest;
          const feedback = get("reminder-test-feedback");
          feedback.textContent = channel === "email" ? "Sending reminder…" : "Creating in-app reminder…";
          item.disabled = true;
          if (channel === "email") startSending();
          try {
            const result = await api("/api/reminders/test", { channel });
            const delivery = result.delivery[channel];
            feedback.textContent = `${statuses[delivery.status]}${delivery.reason ? ` · ${delivery.reason}` : ""}`;
            if (delivery.status === "failed") feedback.append(" ", button("View Reminders", () => openView("reminders")));
            wakeStatus(await api("/api/reminders/settings"));
          } catch (error) {
            feedback.textContent = error.message;
          } finally {
            if (channel === "email") stopSending();
            item.disabled = false;
          }
        });
      }
    }
    try {
      const info = await api("/api/reminders/settings");
      if (currentView() === "settings" && currentSettings() === "reminders") loadForm(info);
    } catch (error) {
      get("reminder-settings-feedback").textContent = error.message;
    }
  }

  async function cancelReminder(identity) {
    const feedback = get("reminders-feedback");
    try {
      await api("/api/reminders/cancel", { id: identity });
      feedback.textContent = "Reminder canceled.";
      await reminders();
    } catch (error) {
      feedback.textContent = error.message;
    }
  }

  let reminderSignature;
  let reminderRequest = 0;
  async function reminders({ background } = {}) {
    const target = get("reminders-content");
    const request = ++reminderRequest;
    const { query } = reminderSearch;
    try {
      const result = await refreshAPI(listSearchPath("/api/reminders", query),
        { background, signal: AbortSignal.timeout(6000) });
      if (request !== reminderRequest || query !== reminderSearch.query || currentView() !== "reminders") return;
      if (result.timezone) setTimeZone(result.timezone);
      const count = result.jobs.length + result.delivered.length + result.outbox.length;
      reminderSearch.count(count);
      const signature = JSON.stringify([query, result]);
      if (signature === reminderSignature) return;
      reminderSignature = signature;
      const groups = [
        ["Upcoming", [
          ...result.jobs.filter((job) => !job.snoozed_at),
          ...result.delivered.filter((row) => row.delivery.email?.status === "queued" && !row.delivery.app),
        ]],
        ["Snoozed", result.jobs.filter((job) => job.snoozed_at)],
        ["Delivered", result.delivered.filter((row) => row.delivery.email?.status !== "queued" || row.delivery.app)],
      ];
      const keys = [
        ...groups.flatMap(([name, rows]) => rows.map((row) => `${name}:${row.job_id || row.id}`)),
        ...result.outbox.map((row) => `outbox:${row.id}`),
      ];
      const play = remindersUnfiltered && !query ? prepareListMotion(target, keys) : undefined;
      remindersUnfiltered = !query;
      target.hidden = !!query && !count;
      render(html`<${ReminderList} ...${{ groups, outbox: result.outbox, query, cancelReminder }} />`, target);
      play?.();
    } catch (error) {
      if (!background && request === reminderRequest && query === reminderSearch.query) {
        reminderSearch.fail();
        get("reminders-feedback").textContent = error.message;
      }
    }
  }

  const refreshEmailStatus = async () => wakeStatus(await api("/api/reminders/settings"));
  function mountList(search) {
    reminderSearch = search;
    get("open-reminder-settings").addEventListener("click", () => openSettings("reminders"));

    const reminderForm = get("reminder-create-form");
    reminderForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = Object.fromEntries(new FormData(reminderForm));
      const feedback = get("reminders-feedback");
      if (!data.channel) delete data.channel;
      data.urgent = reminderForm.elements.urgent.checked;
      const submit = reminderForm.querySelector("button[type=submit]");
      submit.disabled = true;
      try {
        data.at = localTimeToISO(data.at);
        await api("/api/reminders/create", data);
        reminderForm.reset();
        get("reminder-create").open = false;
        get("reminder-create").querySelector("summary").focus();
        feedback.textContent = "Reminder scheduled.";
        await reminders();
      } catch (error) {
        feedback.textContent = error.message;
      } finally {
        submit.disabled = false;
      }
    });

  }

  return { settings, reminders, refreshEmailStatus, mountList };
}
