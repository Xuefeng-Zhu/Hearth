import { icon } from "./icons.js";
import { markdown } from "./artifacts.js";

const areas = [
  { id: "profile", label: "Profile", icon: "user", singular: "field", empty: "Your personal details" },
  { id: "people", label: "People", icon: "people", singular: "contact", empty: "No contacts saved yet." },
  { id: "places", label: "Places", icon: "pin", singular: "place", empty: "No places saved yet." },
  { id: "topics", label: "Topics", icon: "book", singular: "note", empty: "No topics saved yet." },
  { id: "daily", label: "Daily", icon: "clock", singular: "log", empty: "No daily logs saved yet." },
];
const labels = {
  name: "Name", preferred_name: "Preferred name", pronouns: "Pronouns", phone: "Phone",
  employer: "Employer", role: "Role", pets: "Pets", interests: "Interests",
  communication: "Communication preferences", id: "Address ID", label: "Label", address: "Address", notes: "Notes",
};

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text != null) element.textContent = text;
  return element;
}

function button(text, onClick, symbol, className = "") {
  const element = node("button", className);
  element.type = "button";
  if (symbol) element.append(icon(symbol, 16));
  element.append(document.createTextNode(text));
  element.addEventListener("click", onClick);
  return element;
}

function sectionFor(path) {
  if (path === "USER.md" || path === "APPROVAL_PREFERENCES.md" || path.startsWith("chat/")) return "profile";
  return ({ people: "people", locations: "places", daily: "daily" })[path.split("/")[0]] || "topics";
}

function relatedLabel(row) {
  return row.relation || ({ contact: "Contact", organization: "Organization", place: "Place", project: "Project",
    event: "Event", interest: "Interest", misc: "Note", user: "Profile" })[row.type];
}

function field(container, name, value, { label = labels[name], multiline = false, required = false } = {}) {
  const wrapper = node("label", "memory-field");
  const control = node(multiline ? "textarea" : "input");
  if (!multiline) control.type = name === "phone" ? "tel" : "text";
  else control.rows = 3;
  control.name = name;
  control.required = required;
  control.value = value;
  wrapper.append(node("span", "", label), control);
  container.append(wrapper);
  return control;
}

export function createMemory({ api, forget, approvals }) {
  const tabs = document.getElementById("memory-tabs");
  const area = document.getElementById("memory-area");
  const status = document.getElementById("memory-status");
  let data;
  let section = "profile";
  let selected;
  let source;
  let request = 0;

  const records = (category) => (data?.index || []).filter((row) => sectionFor(row.path) === category
    && !["USER.md", "APPROVAL_PREFERENCES.md"].includes(row.path));
  const announce = (message) => { status.textContent = message; };

  function choose(category, path, hit) {
    section = category;
    selected = path;
    source = hit;
    announce("");
    return render();
  }

  function renderTabs() {
    const focus = document.activeElement?.id;
    const buttons = areas.map((item) => {
      const count = item.id === "profile"
        ? Object.values(data.profile).filter((value) => typeof value === "string" ? value.trim() :
          Array.isArray(value) ? value.length : Object.values(value).some(Boolean)).length
        : records(item.id).length;
      const control = button(item.label, () => choose(item.id), item.icon, "memory-tab");
      control.append(node("small", "", `${count} ${item.singular}${count === 1 ? "" : "s"}`));
      control.role = "tab";
      control.id = `memory-tab-${item.id}`;
      control.setAttribute("aria-controls", area.id);
      control.setAttribute("aria-selected", String(section === item.id));
      control.tabIndex = section === item.id ? 0 : -1;
      return control;
    });
    tabs.replaceChildren(...buttons);
    if (focus?.startsWith("memory-tab-")) document.getElementById(focus)?.focus();
    area.setAttribute("aria-labelledby", `memory-tab-${section}`);
  }

  tabs.addEventListener("keydown", (event) => {
    const index = areas.findIndex((item) => item.id === section);
    const next = { ArrowLeft: (index + areas.length - 1) % areas.length, ArrowRight: (index + 1) % areas.length,
      Home: 0, End: areas.length - 1 }[event.key];
    if (next == null) return;
    event.preventDefault();
    const item = areas[next];
    choose(item.id);
    document.getElementById(`memory-tab-${item.id}`)?.focus();
  });

  function related(record) {
    const block = node("section", "memory-related");
    const heading = node("h4", "");
    heading.append(icon("link", 17), "Related notes");
    block.append(heading);
    const ids = new Set([...(record?.related || []), ...data.index
      .filter((row) => row.related.includes(record?.id)).map((row) => row.id)]);
    const list = node("ul", "memory-links");
    for (const id of ids) {
      const row = data.index.find((item) => item.id === id);
      const entry = node("li", "");
      if (row) entry.append(button(row.title, async () => {
        await choose(sectionFor(row.path), row.path);
        area.querySelector(".memory-note h3, .memory-card h3")?.focus();
      }, "", "memory-link"));
      else entry.append(node("span", "meta", id));
      list.append(entry);
    }
    block.append(ids.size ? list : node("p", "meta", "No related notes yet."));
    return block;
  }

  function profile() {
    const panel = node("section", "memory-card");
    const title = node("h3", "", "Personal profile");
    title.tabIndex = -1;
    panel.append(title, node("p", "meta", "Hearth uses this profile in every conversation."));
    const form = node("form", "memory-profile-form");
    const grid = node("div", "memory-fields");
    const values = data.profile;
    const identity = ["name", "preferred_name", "pronouns", "phone"];
    for (const key of identity) field(grid, key, values[key]);
    form.append(grid);
    const work = node("fieldset", "memory-fieldset memory-fields");
    work.append(node("legend", "", "Work"));
    for (const key of ["employer", "role"]) field(work, key, values.work[key]);
    form.append(work);

    const addresses = node("fieldset", "memory-fieldset");
    addresses.append(node("legend", "", "Addresses"));
    const addressRows = node("div", "memory-addresses");
    const addAddress = (address = { id: "", label: "", address: "", notes: "" }) => {
      const row = node("div", "memory-address memory-fields");
      for (const key of Object.keys(address)) field(row, key, address[key], { required: key === "id" });
      row.append(button("Remove address", () => row.remove(), "trash"));
      addressRows.append(row);
      return row;
    };
    for (const address of values.addresses) addAddress(address);
    addresses.append(addressRows, button("Add address", () => addAddress().querySelector("input").focus(), "plus"));
    form.append(addresses);

    const lists = node("div", "memory-fields");
    for (const key of ["pets", "interests", "communication"]) {
      field(lists, key, values[key].join("\n"), { label: `${labels[key]} (one per line)`, multiline: true });
    }
    form.append(lists);
    field(form, "profile_notes", data.notes, { label: "Profile notes", multiline: true });
    const save = node("button", "memory-primary", "Save profile");
    save.type = "submit";
    form.append(save);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const inputs = new FormData(form);
      const into = (keys, read) => Object.fromEntries(keys.map((key) => [key, read(key)]));
      const read = (key) => inputs.get(key).trim();
      const next = {
        ...into(identity, read),
        work: into(["employer", "role"], read),
        addresses: [...addressRows.children].map((row) =>
          into(["id", "label", "address", "notes"], (key) => row.querySelector(`[name="${key}"]`).value.trim())),
        ...into(["pets", "interests", "communication"], (key) => read(key).split("\n").map((line) => line.trim()).filter(Boolean)),
      };
      mutate(save, "/api/memory/profile", { profile: next, notes: read("profile_notes"), revision: data.revision },
        "Profile saved.", undefined, () => area.querySelector(".memory-primary")?.focus());
    });
    panel.append(form, related(data.index.find((row) => row.id === "user")));
    const settings = node("div", "memory-policy");
    settings.append(button("Approval preferences", approvals, "shield"));
    if (data.forget_rules) settings.append(node("p", "meta",
      `${data.forget_rules} standing forget rule${data.forget_rules === 1 ? "" : "s"}`));
    panel.append(settings);
    return panel;
  }

  async function mutate(control, endpoint, body, message, next, onDone) {
    if (control.disabled) return;
    control.disabled = true;
    try {
      await api(endpoint, body);
      selected = next;
      source = undefined;
      if (next) section = sectionFor(next);
      await load();
      announce(message);
      onDone?.();
    } catch (error) {
      announce(error.message);
    } finally {
      control.disabled = false;
    }
  }

  function editor(panel, record, file, operation) {
    const form = node("form", "memory-note-editor");
    const editing = operation === "write";
    const control = field(form, "note", editing ? file.content : file.path, {
      label: editing ? "Markdown and front matter" : "New Markdown path", multiline: editing, required: true,
    });
    if (editing) control.rows = 12;
    const controls = node("div", "memory-actions");
    const save = node("button", "memory-primary", editing ? "Save note" : "Rename note");
    save.type = "submit";
    controls.append(save, button("Cancel", render));
    form.append(controls);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const value = control.value;
      if (!editing && !window.confirm(`Rename ${record.title} and update related links?`)) return;
      mutate(save, `/api/memory/${operation}`, {
        path: file.path, revision: file.revision, [editing ? "content" : "target"]: value,
      }, editing ? "Note saved." : "Note renamed.", editing ? file.path : value, () => {
        area.querySelector(".memory-note h3")?.focus();
      });
    });
    panel.querySelector(".memory-note-body").replaceChildren(form);
    control.focus();
  }

  async function notePanel(panel, row, hit, version) {
    const path = hit?.path || row.path;
    try {
      const file = hit?.message_id
        ? await api(`/api/memory/chat?thread=${encodeURIComponent(hit.thread_id)}&message=${encodeURIComponent(hit.message_id)}`)
        : await api(`/api/memory?path=${encodeURIComponent(path)}`);
      if (version !== request) return;
      const title = node("h3", "", row?.title || (hit?.message_id ? "Chat excerpt" : path));
      title.tabIndex = -1;
      const footer = node("div", "memory-actions");
      if (hit?.message_id) {
        footer.append(button("Forget message", () => forget(hit), "trash"));
      } else if (path === "APPROVAL_PREFERENCES.md") {
        footer.append(button("Open approval settings", approvals, "settings"));
      } else if (path === "USER.md") {
        footer.append(button("Edit profile", () => choose("profile"), "edit"));
      } else {
        footer.append(button("Edit", () => editor(panel, row, file, "write"), "edit"),
          button("Rename", () => editor(panel, row, file, "move"), "file"),
          button("Delete", () => forget({ path, revision: file.revision }), "trash"));
      }
      const detail = node("div", "memory-note-body");
      if (hit && !hit.message_id) {
        const preview = node("pre", "memory-note-source");
        file.content.split(/\r?\n/).forEach((line, index) => {
          const active = index + 1 >= hit.line && index + 1 <= hit.end_line;
          preview.append(node("span", `file-line${active ? " is-highlighted" : ""}`, line || " "));
        });
        detail.append(preview);
      } else if (file.excerpt) detail.append(node("p", "", file.excerpt));
      else {
        const body = file.body.replace(/^\s*# [^\n]+(?:\n|$)/, "").trim();
        detail.append(body ? markdown(body, "markdown") : node("p", "meta", "This note is empty."));
      }
      panel.replaceChildren(title, node("p", "memory-note-meta meta", hit?.message_id ? "Chat memory" : path),
        detail, footer, ...(row ? [related(row)] : []));
    } catch (error) {
      if (version === request) panel.replaceChildren(node("p", "meta", error.message));
    }
  }

  async function render() {
    if (!data) return;
    const version = ++request;
    renderTabs();
    if (section === "profile" && !source && (!selected || selected === "USER.md")) {
      area.replaceChildren(profile());
      return;
    }
    const grouping = areas.find((item) => item.id === section);
    const rows = records(section);
    if (section === "daily") rows.reverse();
    const current = data.index.find((row) => row.path === selected) || rows[0];
    selected = source?.path || current?.path;
    const layout = node("div", `memory-layout${rows.length ? " has-list" : ""}`);
    if (rows.length) {
      const list = node("div", "memory-card memory-list");
      list.setAttribute("aria-label", grouping.label);
      for (const row of rows) {
        const item = button(row.title, () => {
          choose(section, row.path);
          area.querySelector('[aria-pressed="true"]')?.focus();
        }, grouping.icon, "memory-list-item");
        item.append(node("small", "", section === "daily" ? row.id.split("/").at(-1) : relatedLabel(row)));
        item.setAttribute("aria-pressed", String(row.path === selected));
        list.append(item);
      }
      layout.append(list);
    }
    const main = node("article", "memory-card memory-note");
    layout.append(main);
    area.replaceChildren(layout);
    if (source || current) {
      main.append(node("p", "meta", "Loading note…"));
      await notePanel(main, current, source, version);
    } else {
      main.append(icon(grouping.icon, 26), node("h3", "", grouping.label), node("p", "meta", grouping.empty));
    }
  }

  async function load() {
    data = await api("/api/memory");
    return render();
  }

  return {
    load,
    selectSource(hit) {
      section = sectionFor(hit.path);
      selected = hit.path;
      source = hit;
    },
    clearSource() {
      selected = undefined;
      source = undefined;
    },
  };
}
