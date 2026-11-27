import { render } from "preact";
import { useLayoutEffect, useRef, useState } from "preact/hooks";
import { html, Icon } from "../chat/view.js";
import { localDay, previousDay, timeFormatter } from "../time.js";
import { mascot, setPose } from "../avatar.js";
import { workerDuration, workerStatuses } from "../workers.js";

export const categories = {
  all: "All", chat: "Chats", memory: "Memory", action: "Actions", connector: "Connectors", error: "Errors",
};
export const kinds = {
  chat: ["Chat turn", "message"], recall: ["Memory recalled", "book"], memory: ["Memory", "book"],
  reminder: ["Reminder", "bell"], gateway: ["Connector", "plug"], search: ["Web search", "search"],
  browse: ["Web browsing", "monitor"], routing: ["Model routing", "route"], brain: ["Model fallback", "route"],
  voice: ["Voice", "mic"], artifact: ["Artifact", "file-text"], upload: ["Attachment", "paperclip"],
  page: ["Page", "page"], page_share: ["Page sharing", "share"],
  self_update: ["Hearth update", "shield"],
  skill: ["Skill", "skill"], goal: ["Goal", "activity"],
  worker: ["Worker", "workers"],
  undo: ["Undo", "retry"], inbox: ["Inbox", "inbox"], email: ["Email", "mail"],
  approval: ["Approval", "shield"], task: ["Recurring task", "clock"], automation: ["Automation", "clock"], proactivity: ["Proactivity", "sparkle"],
  panel: ["Home panel", "home"], feed: ["Feed", "sparkle"], checkpoint: ["Checkpoint", "history"], thread: ["Side chat", "message"], tool: ["Tool", "wrench"],
};
kinds.remember = kinds.memory;

const statusNames = {
  pending: "Awaiting approval", partial: "Partially applied", unknown: "Delivery unconfirmed",
  sending: "Delivery unconfirmed", changing: "Interrupted", request_unknown: "Request unconfirmed",
};
const relativeFormat = new Intl.RelativeTimeFormat(undefined, { numeric: "always", style: "short" });
const exactFormat = timeFormatter({ dateStyle: "full", timeStyle: "long" });
const dayFormat = timeFormatter({ month: "long", day: "numeric", year: "numeric" });
const shortFormat = timeFormatter({ dateStyle: "medium", timeStyle: "short" });
export const stamp = (value) => Date.parse(value) || 0;

export function dayKey(value) {
  return value ? localDay(value) : "";
}

function dayLabel(value, now) {
  const key = dayKey(value);
  if (!key) return "Date unavailable";
  if (key === dayKey(now)) return "Today";
  return key === previousDay(now) ? "Yesterday" : dayFormat.format(value);
}

function relativeTime(value, now) {
  const seconds = Math.round((value - now) / 1000);
  if (Math.abs(seconds) < 60) return "Just now";
  for (const [unit, size] of [["day", 86400], ["hour", 3600], ["minute", 60]]) {
    if (Math.abs(seconds) >= size) return relativeFormat.format(Math.trunc(seconds / size), unit);
  }
}

function routedModel(model) {
  return [model.name, model.model && model.provider !== "mock" ? model.model : ""].filter(Boolean).join(" · ");
}

function detailFields(row, gatewayResponse) {
  const data = row.data || {};
  const formatted = (value) => stamp(value) ? shortFormat.format(stamp(value)) : "";
  const join = (values) => values?.join("\n");
  const responseStatus = gatewayResponse?.status || data.http_status;
  const lines = [
    ["Request", data.prompt || data.query],
    ["Page URL", data.url],
    ["Version", data.page_version && `v${data.page_version}`],
    ["Commit", data.merge_sha],
    ["Change", row.kind === "page" && data.note],
    ["Category", row.kind === "proactivity" && data.category],
    ["Trigger", row.kind === "automation" && { email: "Incoming email", feed: "Feed card",
      reminder: "Reminder fired", schedule: "Schedule" }[data.trigger]],
    ["Actions", row.kind === "automation" && join(data.steps?.map((step) => step.message || step.error || step.status))],
    ["Session ID", data.session_id],
    ["Browse time", Number.isInteger(data.duration_ms) ? `${(data.duration_ms / 1000).toFixed(2)} s` : ""],
    ["Mode", row.kind === "browse" && data.mock && "Mock"],
    ["Reply", data.reply],
    ["Routing", data.reason || data.routing?.reason],
    ["Model order", join(data.order?.map(routedModel))],
    ["Notes", data.detail || data.error || data.reason || join(data.notices)],
    ["Memory files", join(data.paths) || data.path],
    ["Excerpt", data.excerpt],
    ["Memory backend", data.backend && (row.connector || "Keyword")],
    ["Fact", data.fact],
    ["Reminder", data.job?.message || data.message],
    ["Due", formatted(data.job?.next_at || data.scheduled_at)],
    ["Next due", formatted(data.next_due)],
    ["Channel", { app: "In app", email: "Email", both: "Both" }[data.job?.channel]],
    ["Delivery", data.delivery_summary || join(Object.entries(data.delivery || {}).map(([channel, delivery]) =>
      `${channel === "app" ? "In app" : "Email"} · ${delivery.status}${delivery.reason ? ` · ${delivery.reason}` : ""}`))],
    ["Late", data.late_minutes ? `Late by ${data.late_minutes}m` : ""],
    ["Summary", data.summary],
    ["Worker time", row.kind === "worker" && workerDuration(data.elapsed_ms)],
    ["Worker steps", row.kind === "worker" && join(data.steps.map((step) => step.label))],
    ["Proposed action", data.proposal],
    ["Event time", formatted(data.event_at)],
    ["Schedule", data.job?.cron && `${data.job.cron} UTC`],
    ["Recipients", data.email?.to.join(", ")],
    ["Subject", data.email?.subject],
    ["Message", data.email?.text],
    ["Connector request", data.request && `${data.request.method} ${data.request.path}`],
    ["Response", responseStatus && `HTTP ${responseStatus}`],
    ["Response preview", typeof gatewayResponse?.data === "string" && gatewayResponse.data.slice(0, 1200)],
    ["Checkpoint", data.checkpoint?.id],
    ["Original activity", formatted(data.original_at)],
    ["Duration", Number.isInteger(data.duration) ? `${Math.floor(data.duration / 60)}m ${data.duration % 60}s` : ""],
    ["Engine", data.engine],
    ["Transcript", join(data.lines?.map((line) => `${line.role === "user" ? "You" : "Agent"} — ${line.text}`))],
    ["Warnings", join(data.warnings)],
    ["Latency", Number.isInteger(data.latency_ms) ? `${data.latency_ms.toLocaleString()} ms` : ""],
  ];
  return lines.filter(([, value]) => value);
}

export function mountTimeline(get) {
  const options = Object.entries(kinds).filter(([id]) => id !== "remember")
    .sort(([, [a]], [, [b]]) => a.localeCompare(b));
  render(html`
        <div class="section-intro timeline-intro">
          <h2>Workspace activity</h2>
          <p>See what Hearth did and undo changes.</p>
        </div>
        <section class="timeline-today" aria-labelledby="timeline-today-title">
          <h3 id="timeline-today-title">Today at a glance</h3>
          <dl id="timeline-summary" class="timeline-summary">
            <div><dt>Turns</dt><dd id="timeline-turns">—</dd></div>
            <div><dt>Memories</dt><dd id="timeline-memory">—</dd></div>
            <div><dt>Actions</dt><dd id="timeline-actions">—</dd></div>
            <div><dt>Connector calls</dt><dd id="timeline-connectors">—</dd></div>
            <div><dt>Last undo</dt><dd id="timeline-last-undo">—</dd></div>
          </dl>
        </section>
        <p class="timeline-compact-summary" id="timeline-compact-summary" aria-label="Today’s activity"></p>
        <div class="timeline-controls">
          <div id="timeline-filters" class="timeline-filters" role="group" aria-label="Activity type"></div>
          <div class="timeline-fields">
            <label class="visually-hidden" for="timeline-search">Search activity</label>
            <input id="timeline-search" type="search" maxlength="240" placeholder="Search activity…" />
            <label class="visually-hidden" id="timeline-thread-label" for="timeline-thread">Thread</label>
            <select id="timeline-thread"><option value="">All threads</option></select>
            <label class="visually-hidden" id="timeline-category-label" for="timeline-category">Category</label>
            <select id="timeline-category"><option value="">All categories</option>
              ${options.map(([id, [label]]) => html`<option key=${id} value=${id}>${label}</option>`)}
            </select>
            <button class="timeline-mobile-filter" id="timeline-filter-open" type="button" aria-haspopup="dialog"
              aria-controls="timeline-filter-sheet"><${Icon} name="filter" size=${17} />${"Filter "}
              <span id="timeline-error-count" class="timeline-error-count" hidden></span></button>
          </div>
        </div>
        <div class="timeline-active-filter" id="timeline-active-filter" hidden>
          <button id="timeline-filter-clear" type="button"><span id="timeline-filter-name"></span>
            <${Icon} name="x" size=${15} /></button>
        </div>
        <dialog class="timeline-filter-sheet" id="timeline-filter-sheet" aria-labelledby="timeline-filter-title">
          <header>
            <h2 id="timeline-filter-title">Filter activity</h2>
            <button type="button" id="timeline-filter-close" aria-label="Close filters"><${Icon} name="x" /></button>
          </header>
          <div id="timeline-filter-options"></div>
          <div class="timeline-filter-thread" id="timeline-filter-thread"></div>
          <footer>
            <button type="button" id="timeline-filter-reset">Reset</button>
            <button type="button" id="timeline-filter-apply">Apply</button>
          </footer>
        </dialog>
        <p class="timeline-feedback meta" id="timeline-feedback" role="status">Loading activity…<span class="loading-skeleton" aria-hidden="true"></span></p>
        <p class="visually-hidden" id="timeline-announcer" role="status"></p>
        <div class="timeline" id="timeline"></div>
  `, get("timeline-view"));
}

export function ThreadOptions({ names }) {
  return html`<option value="">All threads</option>${[...names].sort(([, a], [, b]) => a.localeCompare(b))
    .map(([id, title]) => html`<option key=${id} value=${id}>${title}</option>`)}`;
}

export function Filters({ counts, active, choose }) {
  return Object.entries(categories).map(([id, label]) => html`
    <button key=${id} type="button" data-filter=${id} aria-pressed=${String(id === active)}
      aria-label=${`${label}, ${counts[id]}`} onClick=${() => choose(id)}>${label}<span>${counts[id]}</span></button>`);
}

export function Time({ at, now, className }) {
  const value = stamp(at);
  return html`<time class=${className} hidden=${!value} dateTime=${value ? at : null}
    title=${value ? exactFormat.format(value) : null}>${relativeTime(value, now)}</time>`;
}

function Detail({ row, response, state }) {
  const fields = detailFields(row, response);
  const [raw, setRaw] = useState(!!state.rawLoaded);
  return html`<div class="timeline-detail">
    ${fields.length > 0 && html`<dl class="timeline-detail-fields">${fields.map(([label, value]) =>
      html`<div key=${label}><dt>${label}</dt><dd>${String(value)}</dd></div>`)}</dl>`}
    ${row.data?.results?.length > 0 && html`<ul class="timeline-results">
      ${row.data.results.map((item) => html`<li>
        <strong>${item.title || [item.path, item.line && `line ${item.line}`].filter(Boolean).join(" · ")}</strong>
        ${(item.excerpt || item.snippet) && html`<p>${item.excerpt || item.snippet}</p>`}
      </li>`)}
    </ul>`}
    <details class="timeline-raw" open=${!!state.rawOpen} onToggle=${({ currentTarget }) => {
      state.rawOpen = currentTarget.open;
      if (state.rawOpen) setRaw(state.rawLoaded = true);
    }}>
      <summary data-focus="raw">Raw</summary>
      ${raw && html`<pre>${JSON.stringify(response === undefined ? row.data : { ...row.data, response }, null, 2)}</pre>`}
    </details>
  </div>`;
}

const undoMessages = {
  artifact: "Undo this artifact change?", automation: "Remove this run’s Feed cards and cancel any remaining reminders?",
  inbox: "Undo the changes from this email?", reminder: "Cancel this reminder?", page: "Undo this page change?",
  skill: "Undo this skill change?", goal: "Undo this goal change?",
};

function Confirmation({ row, action, busy, close, undo }) {
  const message = row.redoable ? "Apply this memory change again?" : undoMessages[row.kind] ||
    (action.undo_automation ? "Restore this automation?" : action.undo_task ? "Restore this recurring task?"
      : action.memory_change ? "Undo this memory change?"
        : "Restore this checkpoint? Newer chats, notes, and reminders will roll back. Delivered email stays delivered.");
  const label = row.redoable ? "Redo change" : (undoMessages[row.kind] || action.memory_change ||
    action.undo_task || action.undo_automation) ? "Undo change" : "Restore checkpoint";
  return html`
    <p>${message}</p>
    <div class="action-row">
      <button type="button" disabled=${busy} onClick=${() => close(true)}>Cancel</button>
      <button type="button" class="timeline-restore" data-focus="restore" disabled=${busy} onClick=${() => {
        close(false);
        return undo(action, { confirmed: true, timelineTitle: row.title, redo: !!row.redoable });
      }}>${label}</button>
    </div>`;
}

function Entry({ row, response, now, state, busy, approve, undo, confirmation, confirm, highlight }) {
  const ref = useRef(null);
  const [expanded, setExpanded] = useState(!!state.expanded);
  const kind = row.undone ? "undo" : row.kind;
  const [kindLabel, symbol] = kinds[kind] || kinds.tool;
  const canUndo = (row.undoable && !row.undone) || row.redoable;
  const confirming = confirmation === row.id;
  if (confirming) state.confirmed = true;
  const action = row.kind === "artifact" ? { ...row.data, id: row.action_id } : row.data;
  const tags = [
    [row.thread_title, "thread"], [row.model?.split("/").at(-1), "model"], [row.connector, "connector"],
    [row.source === "voice-call" && row.kind !== "voice" && "Voice call", "source"],
    [row.undone ? "Undone" : (row.kind === "worker" && workerStatuses[row.data?.status]) ||
      statusNames[row.data?.status] || (row.error && "Error"), "status"],
  ];
  const reminder = row.kind === "reminder";
  const animation = highlight.has(row.id);
  return html`<li ref=${ref} class=${[
      "timeline-entry", row.undone && "is-undone", row.error && "is-error", animation && "is-new", canUndo && "has-undo",
    ].filter(Boolean).join(" ")} data-kind=${kind} data-entry=${row.id}
    data-reminder-id=${reminder ? String(row.data.job?.id || row.data.id) : undefined}
    data-reminder-message=${reminder ? String(row.data.job?.message || row.data.message) : undefined}
    onAnimationEnd=${({ currentTarget, target }) => {
      if (currentTarget === target) {
        highlight.delete(row.id);
        currentTarget.classList.remove("is-new");
      }
    }}>
    <details class="timeline-card" id=${canUndo ? `activity-${row.action_id}` : null}
      open=${!!state.open} onToggle=${({ currentTarget }) => {
        state.open = currentTarget.open;
        if (state.open) setExpanded(state.expanded = true);
      }}>
      <summary class="timeline-card-head" data-focus="summary">
        <span class="timeline-kind" title=${kindLabel}><${Icon} name=${symbol} size=${19} />
          <span class="visually-hidden">${kindLabel}</span></span>
        <span class="timeline-card-copy">
          <span class="timeline-title" title=${row.title}>${row.title}</span>
          <span class="timeline-meta">${tags.map(([value, type]) => value && html`
            <span key=${type} class=${`timeline-tag timeline-tag-${type}`} title=${type === "model" ? row.model : value}>${value}</span>`)}</span>
        </span>
        <${Time} at=${row.at} now=${now} className="timeline-time" />
        <span class="timeline-chevron" aria-hidden="true"></span>
      </summary>
      ${expanded && html`<${Detail} ...${{ row, response, state }} />`}
    </details>
    ${canUndo && html`
      <button type="button" class="timeline-undo" data-focus="undo" disabled=${busy}
        aria-controls=${`confirm-${row.action_id}`} aria-expanded=${String(confirming)}
        onClick=${() => confirm(confirming ? undefined : row.id,
          () => ref.current.querySelector(".timeline-confirm button")?.focus())}>
        <${Icon} name="retry" size=${13} />${row.redoable ? "Redo" : "Undo"}
      </button>
      <div class="timeline-confirm" id=${`confirm-${row.action_id}`} hidden=${!confirming}>
        ${state.confirmed && html`<${Confirmation} ...${{ row, action, busy, undo }}
          close=${(focus) => confirm(undefined, focus ? () => ref.current.querySelector(".timeline-undo")?.focus() : undefined)} />`}
      </div>`}
    ${row.action_id && action.status === "pending" && !row.undone && html`
      <button type="button" class="timeline-approve" data-focus="approve" disabled=${busy} onClick=${() => approve(action)}>Approve</button>`}
  </li>`;
}

function EmptyTimeline({ hasEntries, clearSearch }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const sleeping = mascot("ember");
    sleeping.setAttribute("aria-hidden", "true");
    setPose(sleeping, { pose: "sleeping" });
    ref.current.prepend(sleeping);
  }, []);
  return html`<div class="timeline-empty" ref=${ref}>
    <h3>${hasEntries ? "No matching activity" : "Hearth is quiet"}</h3>
    <p>${hasEntries ? "Try a different search or clear your filters." : "Start a chat to see Hearth’s activity here."}</p>
    ${hasEntries && html`<button type="button" onClick=${clearSearch}>Clear filters</button>`}
  </div>`;
}

export function TimelineFeed({ days, now, hasEntries, clearSearch, cardStates, gatewayResults, ...actions }) {
  if (!days.size) return html`<${EmptyTimeline} ...${{ hasEntries, clearSearch }} />`;
  return [...days].map(([key, { value, items }]) => {
    const label = `timeline-day-${key || "unknown"}`;
    return html`<section key=${key} class="timeline-day">
      <h3 class="timeline-day-label" id=${label}>${dayLabel(value, now)}</h3>
      <ol class="timeline-rail" role="list" aria-labelledby=${label}>${items.map((row) => html`
        <${Entry} key=${row.id} ...${{ row, now }} state=${cardStates.get(row.id)} response=${gatewayResults.get(row.action_id)} ...${actions} />`)}</ol>
    </section>`;
  });
}
