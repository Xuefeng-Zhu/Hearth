import { reconcileChildren } from "./dom.js";
import { icon, iconButton } from "./icons.js";

export const workerStatuses = {
  queued: "Queued",
  running: "Running",
  waiting_approval: "Waiting for approval",
  done: "Done",
  complete: "Completed",
  failed: "Failed",
  cancelled: "Stopped",
  declined: "Declined",
  sent: "Sent",
  simulated: "Simulated",
  expired: "Expired",
  request_unknown: "Outcome unconfirmed",
  partial: "Partially applied",
};

const tones = {
  done: "complete", waiting_approval: "pending", failed: "failed",
};
const defaults = { queued: "Waiting for a worker slot.", running: "Working on the assignment." };
export const workerActive = (worker) => ["queued", "running", "waiting_approval"].includes(worker.status);

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function workerDuration(ms) {
  const seconds = Math.floor(Math.max(0, ms || 0) / 1000);
  return seconds >= 60 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s` : `${seconds}s`;
}

function tick(time) {
  const value = workerDuration(Date.now() - Date.parse(time.dataset.workerSince));
  if (time.textContent !== value) time.textContent = value;
}

setInterval(() => {
  for (const timer of document.querySelectorAll("[data-worker-since]")) tick(timer);
}, 1_000);

function createRow(worker, stop, openThread) {
  const item = element("li", "worker-row");
  const details = element("details", "worker-details");
  const summary = element("summary", "worker-summary");
  const arrow = icon("chevron", 15);
  const title = element("strong", "worker-title", worker.title);
  const meta = element("span", "worker-meta");
  const status = element("span");
  const elapsed = element("time", "worker-elapsed");
  const note = element("span", "worker-result");
  meta.append(status, elapsed);
  summary.append(arrow, title, meta, note);
  const steps = element("ol", "worker-steps");
  const empty = element("p", "worker-empty", "No steps recorded yet.");
  const full = element("p", "worker-full");
  details.append(summary, full, steps, empty);
  if (openThread) {
    const link = element("button", "worker-open", "Open chat");
    link.type = "button";
    link.addEventListener("click", () => openThread(worker.thread_id));
    details.append(link);
  }
  const control = iconButton("stop", `Stop ${worker.title}`, () => stop(worker.turn_id, worker.id, control), "worker-stop");
  item.append(details, control);

  function update(current) {
    const active = workerActive(current);
    status.className = `automation-state automation-state-${tones[current.status] || current.status}`;
    status.textContent = workerStatuses[current.status] || current.status;
    const since = current.started_at || current.queued_at;
    if (active) {
      elapsed.dataset.workerSince = since;
      tick(elapsed);
    } else {
      delete elapsed.dataset.workerSince;
      elapsed.textContent = current.elapsed_ms < 10_000 ? `${(current.elapsed_ms / 1_000).toFixed(1)}s` :
        workerDuration(current.elapsed_ms);
    }
    const result = current.summary || defaults[current.status] || "";
    note.textContent = result;
    full.textContent = current.summary || "";
    full.hidden = !["done", "failed", "cancelled"].includes(current.status) || !full.textContent;
    if (!active && document.activeElement === control) summary.focus();
    control.hidden = !active;
    const incoming = current.steps || [];
    steps.replaceChildren(...incoming.map((step) => {
      const li = element("li");
      const status = workerStatuses[step.status] || step.status;
      li.append(element("span", "", step.label), element("span", "worker-step-status", ` · ${status}`));
      if (step.detail) li.append(element("span", "worker-step-detail", step.detail));
      return li;
    }));
    empty.hidden = !!incoming.length;
  }
  return { item, update };
}

export function createWorkersCard({ heading = "Workers", stop, openThread } = {}) {
  const card = element("section", "card workers-card");
  card.setAttribute("aria-label", heading);
  const header = element("div", "workers-heading");
  const title = element("h4", "", heading);
  title.tabIndex = -1;
  header.append(icon("workers", 18), title);
  const list = element("ul", "worker-list");
  const rows = new Map();
  const feedback = element("p", "worker-feedback");
  feedback.setAttribute("role", "status");

  async function request(turnId, workerId, control) {
    control.disabled = true;
    feedback.textContent = "";
    try {
      await stop(turnId, workerId);
    } catch (error) {
      feedback.textContent = error.message;
    } finally {
      control.disabled = false;
    }
  }

  let currentTurn;
  const stopAll = iconButton("stop", "Stop all workers", () => request(currentTurn, undefined, stopAll), "worker-stop-all");
  stopAll.append(element("span", "", "Stop all"));
  if (!openThread) header.append(stopAll);
  card.append(header, list, feedback);

  function update(workers) {
    currentTurn = workers[0]?.turn_id;
    const active = workers.some(workerActive);
    if (!active && document.activeElement === stopAll) title.focus();
    stopAll.hidden = !active;
    const visible = new Set(workers.map((worker) => worker.id));
    for (const id of rows.keys()) if (!visible.has(id)) rows.delete(id);
    const children = workers.map((worker) => {
      if (!rows.has(worker.id)) rows.set(worker.id, createRow(worker, request, openThread));
      const { item, update: updateRow } = rows.get(worker.id);
      updateRow(worker);
      return item;
    });
    reconcileChildren(list, children);
  }

  return { card, update };
}
