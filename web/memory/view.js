import { useLayoutEffect, useRef, useState } from "preact/hooks";
import { html, Icon } from "../ui.js";
import { Markdown } from "../artifacts/markdown.js";
import { memoryLabel } from "../chat/chips.js";
import { memoryNames } from "./labels.js";

export const areas = [
  { id: "profile", label: "Profile", icon: "user", singular: "field", empty: "Your personal details" },
  { id: "people", label: "People", icon: "people", singular: "contact", empty: "No contacts saved yet." },
  { id: "places", label: "Places", icon: "pin", singular: "place", empty: "No places saved yet." },
  { id: "topics", label: "Topics", icon: "book", singular: "note", empty: "No topics saved yet." },
  { id: "daily", label: "Daily", icon: "clock", singular: "log", empty: "No daily logs saved yet." },
  { id: "review", label: "Review", icon: "list" },
];

const labels = {
  name: "Name", preferred_name: "Preferred name", pronouns: "Pronouns", phone: "Phone",
  employer: "Employer", role: "Role", pets: "Pets", interests: "Interests",
  communication: "Communication preferences", id: "Address ID", label: "Label", address: "Address", notes: "Notes",
};
const identity = ["name", "preferred_name", "pronouns", "phone"];
const work = ["employer", "role"];
const lists = ["pets", "interests", "communication"];
const addressFields = ["id", "label", "address", "notes"];
const emptyAddress = { id: "", label: "", address: "", notes: "" };

function relatedLabel(row) {
  return row.relation || ({ contact: "Contact", organization: "Organization", place: "Place", project: "Project",
    event: "Event", interest: "Interest", misc: "Note", user: "Profile" })[row.type];
}

export function MemoryButton({ symbol, className, children, ...props }) {
  return html`<button type="button" class=${className} ...${props}>
    ${symbol && html`<${Icon} name=${symbol} size=${16} />`}${children}
  </button>`;
}

function Field({ name, value, label = labels[name], rows, required }) {
  return html`<label class="memory-field"><span>${label}</span>
    ${rows ? html`<textarea name=${name} rows=${rows} defaultValue=${value} required=${required} />`
      : html`<input name=${name} type=${name === "phone" ? "tel" : "text"} defaultValue=${value} required=${required} />`}
  </label>`;
}

export function MemoryView() {
  return html`
    <div class="memory-intro">
      <h2>What Hearth knows about you</h2>
      <p>Review the details Hearth can use in conversation and follow links between notes.</p>
    </div>
    <form id="memory-find" class="query-form" role="search">
      <label class="visually-hidden" for="memory-query">Search memory</label>
      <input id="memory-query" type="search" maxlength="1000" placeholder="Search memory…" required />
      <button type="submit">Search</button>
    </form>
    <div id="memory-find-results" class="query-results" aria-live="polite" hidden></div>
    <div id="memory-tabs" role="tablist" aria-label="Memory areas"></div>
    <div id="memory-status" role="status" class="meta"></div>
    <div id="memory-area" role="tabpanel" tabindex="0"></div>
  `;
}

export function MemoryTabs({ profile, section, records, choose }) {
  return areas.map(({ id, label, icon, singular }) => {
    const count = id === "profile" ? Object.values(profile).filter((value) => typeof value === "string" ? value.trim()
      : Array.isArray(value) ? value.length : Object.values(value).some(Boolean)).length : records(id).length;
    return html`<${MemoryButton} key=${id} className="memory-tab" symbol=${icon} role="tab" id=${`memory-tab-${id}`}
      aria-controls="memory-area" aria-selected=${String(id === section)} tabIndex=${id === section ? 0 : -1}
      onClick=${() => choose(id)}>${label}
      ${singular && html`<small>${`${count} ${singular}${count === 1 ? "" : "s"}`}</small>`}
    </${MemoryButton}>`;
  });
}

export function Related({ record, index, open }) {
  const ids = new Set([...(record?.related || []), ...index.filter((row) => row.related.includes(record?.id)).map((row) => row.id)]);
  return html`<section class="memory-related">
    <h4><${Icon} name="link" size=${17} />Related notes</h4>
    ${ids.size ? html`<ul class="memory-links">${[...ids].map((id) => {
      const row = index.find((item) => item.id === id);
      return html`<li key=${id}>${row
        ? html`<${MemoryButton} className="memory-link" onClick=${() => open(row)}>${row.title}</${MemoryButton}>`
        : html`<span class="meta">${id}</span>`}</li>`;
    })}</ul>` : html`<p class="meta">No related notes yet.</p>`}
  </section>`;
}

export function Profile({ data, approvals, saveProfile, open }) {
  const values = data.profile;
  const [addresses, setAddresses] = useState(() => values.addresses.map((value, id) => ({ id, value })));
  const sequence = useRef(values.addresses.length);
  const addressRows = useRef(null);
  const added = useRef(false);
  useLayoutEffect(() => {
    if (added.current) {
      addressRows.current.lastElementChild.querySelector("input").focus();
      added.current = false;
    }
  }, [addresses]);

  function submit(event) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const read = (key) => fields.get(key).trim();
    const into = (keys, read) => Object.fromEntries(keys.map((key) => [key, read(key)]));
    const profile = {
      ...into(identity, read),
      work: into(work, read),
      addresses: [...addressRows.current.children].map((row) =>
        into(addressFields, (key) => row.querySelector(`[name="${key}"]`).value.trim())),
      ...into(lists, (key) => read(key).split("\n").map((line) => line.trim()).filter(Boolean)),
    };
    saveProfile(event.submitter || event.currentTarget.querySelector("button[type=submit]"),
      { profile, notes: read("profile_notes"), revision: data.revision });
  }

  return html`<section class="memory-card">
    <h3 tabIndex="-1">Personal profile</h3>
    <p class="meta">Hearth uses this profile in every conversation.</p>
    <form class="memory-profile-form" onSubmit=${submit}>
      <div class="memory-fields">${identity.map((name) => html`<${Field} key=${name} name=${name} value=${values[name]} />`)}</div>
      <fieldset class="memory-fieldset memory-fields">
        <legend>Work</legend>
        ${work.map((name) => html`<${Field} key=${name} name=${name} value=${values.work[name]} />`)}
      </fieldset>
      <fieldset class="memory-fieldset">
        <legend>Addresses</legend>
        <div class="memory-addresses" ref=${addressRows}>${addresses.map(({ id, value }) => html`
          <div class="memory-address memory-fields" key=${id}>
            ${Object.keys(value).map((name) => html`<${Field} key=${name} name=${name} value=${value[name]} required=${name === "id"} />`)}
            <${MemoryButton} symbol="trash" onClick=${() => setAddresses(addresses.filter((row) => row.id !== id))}>Remove address</${MemoryButton}>
          </div>`)}</div>
        <${MemoryButton} symbol="plus" onClick=${() => {
          added.current = true;
          setAddresses([...addresses, { id: sequence.current++, value: emptyAddress }]);
        }}>Add address</${MemoryButton}>
      </fieldset>
      <div class="memory-fields">${lists.map((name) => html`<${Field} key=${name} name=${name}
        value=${values[name].join("\n")} label=${`${labels[name]} (one per line)`} rows=${3} />`)}</div>
      <${Field} name="profile_notes" value=${data.notes} label="Profile notes" rows=${3} />
      <button class="memory-primary" type="submit">Save profile</button>
    </form>
    <${Related} record=${data.index.find((row) => row.id === "user")} index=${data.index} open=${open} />
    <div class="memory-policy">
      <${MemoryButton} symbol="shield" onClick=${approvals}>Approval preferences</${MemoryButton}>
      ${data.forget_rules ? html`<p class="meta">${`${data.forget_rules} standing forget rule${data.forget_rules === 1 ? "" : "s"}`}</p>` : null}
    </div>
  </section>`;
}

export function NoteLayout({ group, rows, selected, choose, children }) {
  return html`<div class=${`memory-layout${rows.length ? " has-list" : ""}`}>
    ${rows.length > 0 && html`<div class="memory-card memory-list" aria-label=${group.label}>
      ${rows.map((row) => html`<${MemoryButton} key=${row.path} symbol=${group.icon} className="memory-list-item"
        title=${row.title} aria-pressed=${String(row.path === selected)} onClick=${() => choose(row.path)}>
        <span class="memory-list-title">${row.title}</span>
        <small>${group.id === "daily" ? row.id.split("/").at(-1) : relatedLabel(row)}</small>
      </${MemoryButton}>`)}
    </div>`}
    <article class="memory-card memory-note">${children}</article>
  </div>`;
}

export function Loading({ children }) {
  return html`<p class="meta">${children}<span class="loading-skeleton" aria-hidden="true"></span></p>`;
}

function NoteEditor({ file, row, operation, mutate, cancel }) {
  const form = useRef(null);
  const editing = operation === "write";
  useLayoutEffect(() => { form.current.elements.note.focus(); }, []);
  return html`<form class="memory-note-editor" ref=${form} onSubmit=${(event) => {
    event.preventDefault();
    const value = form.current.elements.note.value;
    if (!editing && !window.confirm(`Rename ${row.title} and update related links?`)) return;
    mutate(event.submitter || form.current.querySelector("button[type=submit]"), `/api/memory/${operation}`,
      { path: file.path, revision: file.revision, [editing ? "content" : "target"]: value },
      editing ? "Note saved." : "Note renamed.", editing ? file.path : value);
  }}>
    <${Field} name="note" value=${editing ? file.content : file.path} rows=${editing ? 12 : undefined}
      label=${editing ? "Markdown and front matter" : "New Markdown path"} required />
    <div class="memory-actions">
      <button class="memory-primary" type="submit">${editing ? "Save note" : "Rename note"}</button>
      <${MemoryButton} onClick=${cancel}>Cancel</${MemoryButton}>
    </div>
  </form>`;
}

export function MemoryNote({ path, row, hit, file, approvals, forget, choose, open, index, mutate, cancel }) {
  const [operation, edit] = useState();
  const body = file.body?.replace(/^\s*# [^\n]+(?:\n|$)/, "").trim();
  const message = hit?.message_id;
  return html`
    <h3 tabIndex="-1">${row?.title || (message ? "Chat excerpt" : path)}</h3>
    <p class="memory-note-meta meta">${message ? "Chat memory" : path}</p>
    <div class="memory-note-body">
      ${operation ? html`<${NoteEditor} key=${operation} ...${{ file, row, operation, mutate, cancel }} />`
        : hit && !message ? html`<pre class="memory-note-source">${file.content.split(/\r?\n/).map((line, index) => html`
          <span class=${`file-line${index + 1 >= hit.line && index + 1 <= hit.end_line ? " is-highlighted" : ""}`}>${line || " "}</span>`)}</pre>`
          : file.excerpt ? html`<p>${file.excerpt}</p>`
            : body ? html`<${Markdown} text=${body} className="markdown" />`
              : html`<p class="meta">This note is empty.</p>`}
    </div>
    <div class="memory-actions">
      ${message ? html`<${MemoryButton} symbol="trash" onClick=${() => forget(hit)}>Forget message</${MemoryButton}>`
        : path === "APPROVAL_PREFERENCES.md" ? html`<${MemoryButton} symbol="settings" onClick=${approvals}>Open approval settings</${MemoryButton}>`
          : path === "USER.md" ? html`<${MemoryButton} symbol="edit" onClick=${() => choose("profile")}>Edit profile</${MemoryButton}>`
            : html`<${MemoryButton} symbol="edit" onClick=${() => edit("write")}>Edit</${MemoryButton}>
              <${MemoryButton} symbol="file" onClick=${() => edit("move")}>Rename</${MemoryButton}>
              <${MemoryButton} symbol="trash" onClick=${() => forget({ path, revision: file.revision })}>Delete</${MemoryButton}>`}
    </div>
    ${row && html`<${Related} ...${{ record: row, index, open }} />`}
  `;
}

export function RecallResults({ result, open, forget }) {
  return html`
    <p class="meta">${`${memoryNames[result.backend]} · ${result.results.length} ${result.results.length === 1 ? "hit" : "hits"} · ${result.latency_ms.toLocaleString()} ms`}</p>
    ${result.warnings.map((warning) => html`<p class="meta">${warning}</p>`)}
    ${!result.results.length && html`<p class="empty">No memories matched.</p>`}
    ${result.results.map((hit) => {
      const score = hit.backend === "pinecone"
        ? `Score ${hit.score.toFixed(3)} · ${result.reranked ? "Reranked" : "Cosine similarity"}`
        : hit.similarity === null ? `Keyword ${hit.keyword.toFixed(3)}`
          : `Score ${hit.score.toFixed(3)} · Similarity ${hit.similarity.toFixed(3)} · Keyword ${hit.keyword.toFixed(3)}`;
      return html`<article class="result">
        <button type="button" class="result-title" onClick=${() => open(hit)}>${memoryLabel(hit)}</button>
        <p class="meta">${score}</p><p>${hit.excerpt}</p>
        ${forget && !hit.artifact_id && !hit.profile_fields && hit.path !== "APPROVAL_PREFERENCES.md" && html`
          <button type="button" class="forget-excerpt" aria-label=${`Forget ${memoryLabel(hit)}`}
            onClick=${() => forget(hit, true)}>Forget</button>`}
      </article>`;
    })}
  `;
}
