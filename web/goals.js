import { icon, iconButton } from "./icons.js";

const weekdays = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const calendarDate = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" });

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function button(text, symbol, onClick) {
  const element = node("button", "home-link goal-control");
  element.type = "button";
  element.append(icon(symbol, 16), node("span", "", text));
  element.addEventListener("click", onClick);
  return element;
}

function input(type, name, value = "") {
  const element = node("input");
  element.type = type;
  element.name = name;
  element.value = value;
  return element;
}

function label(text, field) {
  const element = node("label");
  element.append(node("span", "", text), field);
  return element;
}

function select(name, items, current) {
  const element = node("select");
  element.name = name;
  for (const [value, text] of items) element.append(new Option(text, value));
  element.value = current;
  return element;
}

export function createGoals({ api, approvalCard, reload }) {
  const dialog = document.getElementById("goal-dialog");
  const approval = node("div", "goal-approval");
  approval.hidden = true;
  const status = node("p", "home-meta goal-status");
  status.setAttribute("role", "status");
  let trigger;

  dialog.addEventListener("close", () => {
    const previous = trigger;
    trigger = undefined;
    if (previous?.isConnected) previous.focus();
    else document.querySelector(".home-card-goals [data-control=new-goal]")?.focus();
  });

  function open(title, control) {
    trigger = control;
    const header = node("header", "automation-dialog-header");
    const heading = node("h2", "", title);
    heading.id = "goal-dialog-title";
    header.append(heading, iconButton("x", "Close", () => dialog.close()));
    dialog.replaceChildren(header);
    dialog.showModal();
  }

  async function change(operation, body) {
    const result = await api(`/api/goals/${operation}`, body);
    if (result.action?.status === "pending") {
      approval.hidden = false;
      approval.replaceChildren(approvalCard(result.action, "goal"));
    } else {
      status.textContent = result.result?.error || result.result?.message || result.action?.title || "";
    }
    return result;
  }

  function formFor(operation, submitLabel, fields) {
    const form = node("form", "automation-editor goal-editor");
    const feedback = node("p", "home-meta goal-status");
    feedback.setAttribute("role", "status");
    const save = node("button", "primary-setting goal-control", submitLabel);
    save.type = "submit";
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      save.disabled = true;
      try {
        await change(operation, fields(new FormData(form)));
        dialog.close();
        await reload();
        if (!approval.hidden) approval.querySelector("button")?.focus();
      } catch (error) {
        feedback.textContent = error.message;
      } finally {
        save.disabled = false;
      }
    });
    dialog.append(form);
    return { form, save, feedback };
  }

  async function editor(row, timezone, control) {
    open(row ? "Edit goal" : "New goal", control);
    const { form, save, feedback } = formFor(row ? "update" : "create", row ? "Save goal" : "Create goal", (data) => {
      const links = [...linkValues].filter(([key, field]) => field.checked).map(([key]) => {
        const [kind, id] = key.split(":");
        return { kind, id };
      });
      const body = { title: data.get("title"), target_date: data.get("target") || null,
        checkin: cadence.value ? { cadence: cadence.value, time: at.value, day: Number(day.value) } : null };
      if (row) Object.assign(body, { id: row.id, revision: row.revision });
      if (!row || JSON.stringify(links) !== JSON.stringify(row.links)) body.links = links;
      return body;
    });
    const title = input("text", "title", row?.title);
    title.required = true;
    title.maxLength = 120;
    const target = input("date", "target", row?.target_date || "");
    const cadence = select("cadence", [["", "Off"], ["daily", "Daily"], ["weekly", "Weekly"]], row?.checkin?.cadence || "");
    const at = input("time", "checkin-time", row?.checkin?.time || "09:00");
    const day = select("day", weekdays.map((name, index) => [index, name]), row?.checkin?.day ?? 1);
    const atLabel = label("Check-in time", at);
    const dayLabel = label("Day of week", day);
    const updateCadence = () => {
      atLabel.hidden = !cadence.value;
      at.required = !!cadence.value;
      dayLabel.hidden = cadence.value !== "weekly";
    };
    cadence.addEventListener("change", updateCadence);
    updateCadence();
    const links = node("details", "goal-links");
    const linkList = node("div", "goal-link-options");
    links.append(node("summary", "goal-control", "Linked reminders and tasks"), linkList);
    const linkValues = new Map();
    form.append(label("Title", title), label("Target date", target), label("Check-in reminder", cadence),
      atLabel, dayLabel, node("p", "home-meta", `Check-ins use ${timezone}.`), links, save, feedback);
    title.focus();
    save.disabled = true;
    try {
      const data = await api("/api/goals/links");
      if (!form.isConnected) return;
      const choices = new Map(data.items.map((item) => [`${item.kind}:${item.id}`, item]));
      const selected = new Set((row?.links || []).map((item) => `${item.kind}:${item.id}`));
      const keys = new Set([...selected, ...choices.keys()]);
      for (const key of keys) {
        const item = choices.get(key);
        const check = input("checkbox", "links", key);
        check.checked = selected.has(key);
        check.disabled = !item && !check.checked;
        if (!item) check.addEventListener("change", () => { check.disabled = !check.checked; });
        const caption = item ? `${item.title} · ${item.kind}` : "Unavailable linked item";
        const choice = node("label", "goal-link-choice");
        choice.append(check, node("span", "", caption));
        linkValues.set(key, check);
        linkList.append(choice);
      }
      if (!keys.size) linkList.append(node("p", "home-meta", "No reminders or tasks to link yet."));
      save.disabled = false;
    } catch (error) {
      feedback.textContent = error.message;
      // Keep existing links if the list is temporarily unavailable.
      links.hidden = true;
      for (const item of row?.links || []) linkValues.set(`${item.kind}:${item.id}`, { checked: true });
      save.disabled = false;
    }
  }

  function checkin(row, control) {
    open(`Check in · ${row.title}`, control);
    const { form, save, feedback } = formFor("checkin", "Save check-in", (data) => ({
      id: row.id, revision: row.revision, note: data.get("note"),
      ...(row.progress.mode === "manual" ? { progress: Number(data.get("progress")) } : {}),
    }));
    if (row.progress.mode === "manual") {
      const progress = input("number", "progress", row.progress.percent);
      Object.assign(progress, { min: 0, max: 100, step: 1, required: true, inputMode: "numeric" });
      form.append(label("Progress (%)", progress));
    }
    const note = node("textarea");
    Object.assign(note, { name: "note", rows: 3, maxLength: 500, required: row.progress.mode === "linked" });
    form.append(label("Check-in note", note), save, feedback);
    form.querySelector("input, textarea").focus();
  }

  async function remove(row, control) {
    control.disabled = true;
    try {
      await change("delete", { id: row.id, revision: row.revision });
      await reload();
      if (!approval.hidden) approval.querySelector("button")?.focus();
    } catch (error) {
      status.textContent = error.message;
    } finally {
      control.disabled = false;
    }
  }

  function goalCard(row, timezone, time) {
    const card = node("article", "goal-row");
    const title = node("h3", "", row.title);
    const value = node("strong", "", `${row.progress.percent}%`);
    const progress = node("progress");
    progress.value = row.progress.percent;
    progress.max = 100;
    progress.setAttribute("aria-label", `Progress for ${row.title}`);
    const head = node("div", "goal-heading");
    head.append(title, value);
    card.append(head, progress);
    if (row.progress.mode === "linked") card.append(node("p", "home-meta", `${row.progress.completed} of ${row.progress.total} linked items complete`));
    if (row.target_date) {
      const date = node("time", "", calendarDate.format(new Date(`${row.target_date}T00:00:00Z`)));
      date.dateTime = row.target_date;
      const due = node("p", "home-meta", "Target ");
      due.append(date);
      card.append(due);
    }
    if (row.next_step) {
      const step = node("p", "goal-next");
      step.append(icon("sparkle", 16), node("span", "", row.next_step));
      card.append(step);
    }
    if (row.last_checkin?.note) card.append(node("p", "home-meta", `Last check-in · ${row.last_checkin.note}`));
    if (row.next_checkin) card.append(node("p", "home-meta", `Next check-in · ${time.format(new Date(row.next_checkin))}`));
    const controls = node("div", "goal-actions");
    const record = button("Check in", "check", (event) => checkin(row, event.currentTarget));
    const edit = button("Edit", "edit", (event) => editor(row, timezone, event.currentTarget));
    const del = iconButton("trash", `Delete ${row.title}`, (event) => remove(row, event.currentTarget), "home-link goal-control");
    for (const [name, control] of [["checkin", record], ["edit", edit], ["delete", del]]) {
      control.dataset.control = `goal-${row.id}-${name}`;
    }
    edit.setAttribute("aria-haspopup", "dialog");
    record.setAttribute("aria-haspopup", "dialog");
    controls.append(record, edit, del);
    card.append(controls);
    return card;
  }

  return {
    render(data, timezone, time, body) {
      const add = button("New goal", "plus", (event) => editor(null, timezone, event.currentTarget));
      add.dataset.control = "new-goal";
      add.setAttribute("aria-haspopup", "dialog");
      const items = node("div", "goal-list");
      items.append(...data.items.map((row) => goalCard(row, timezone, time)));
      body.replaceChildren(add, status, approval, items);
      if (!data.items.length) items.append(node("p", "home-meta", "No goals yet."));
    },
  };
}
