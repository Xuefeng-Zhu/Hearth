import { icon } from "./icons.js";

const checkText = {
  checking: "Checking CI…", pending: "Tests running", passed: "Tests passed",
  failed: "Tests failed", missing: "Required tests missing", none: "No checks reported",
};
const stageText = {
  publishing: "Opening pull request…", waiting: "Waiting for tests", revising: "Updating pull request…",
  discarding: "Closing pull request…", discarded: "Proposal discarded", stale: "Needs a fresh proposal",
  behind: "Proposal is behind main",
  closed: "Pull request closed", updating: "Updating Hearth…", deploy_failed: "Deployment failed",
};

export function proposalPresentation({ status, checks, guard, ready, merge_sha }) {
  const complete = status === "updated";
  const editable = status === "review" || status === "waiting";
  const waiting = status === "review" && guard === "hearth" && checks === "pending";
  const reviewStage = ready ? "Ready to merge" : waiting ? "Waiting for tests" : "Ready for review";
  return {
    stage: complete ? `Hearth updated to ${merge_sha.slice(0, 7)}` : stageText[status] || reviewStage,
    checks: checkText[checks] || checkText.checking,
    guard: guard === "github" ? "GitHub branch protection" : guard === "hearth"
      ? (ready || merge_sha ? "Hearth's own checks: tests passed on an up-to-date branch" : "Hearth's own checks")
      : "",
    approve: status === "review" && !["failed", "missing"].includes(checks),
    revise: editable,
    refresh: status === "behind",
    discard: editable || ["publishing", "revising", "stale", "behind"].includes(status),
    complete,
  };
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function control(text) {
  const button = element("button", "", text);
  button.type = "button";
  return button;
}

function external(text) {
  const link = element("a", "", text);
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

export function updateCard(initial, { perform, announce }) {
  const card = element("section", "card self-update-card");
  const title = element("h3");
  title.id = `hearth-proposal-${initial.id}`;
  title.tabIndex = -1;
  card.setAttribute("aria-labelledby", title.id);
  const heading = element("div", "self-update-heading");
  heading.append(icon("shield", 18), title);
  const summary = element("p");
  const stage = element("p", "self-update-stage");
  const checks = element("p", "self-update-checks");
  const guard = element("p", "self-update-checks");
  const commit = element("p", "self-update-checks", "Head commit ");
  const sha = element("code");
  commit.append(sha);
  const detail = element("p", "self-update-detail");
  const warning = element("p", "self-update-detail");
  const files = element("ul", "self-update-files");
  const disclosure = element("details");
  const diff = element("pre", "self-update-diff");
  diff.tabIndex = 0;
  diff.setAttribute("aria-label", "Unified diff");
  disclosure.append(element("summary", "", "Unified diff"), diff);
  const pull = external();
  const run = external("Open deployment run");
  const links = element("div", "self-update-controls");
  links.append(pull, run);
  const approve = control("Approve and update");
  approve.className = "self-update-approve";
  const revise = control("Request changes");
  revise.setAttribute("aria-expanded", "false");
  const discard = control("Discard");
  const refresh = control("Refresh proposal");
  const actions = element("div", "self-update-controls");
  actions.append(approve, revise, refresh, discard);
  const form = element("form", "self-update-feedback");
  form.hidden = true;
  form.id = `hearth-feedback-${initial.id}`;
  revise.setAttribute("aria-controls", form.id);
  const label = element("label", "", "What should change?");
  const feedback = element("textarea");
  feedback.required = true;
  feedback.maxLength = 4000;
  feedback.rows = 3;
  label.append(feedback);
  const submit = element("button", "", "Send changes");
  const cancel = control("Cancel");
  const feedbackActions = element("div", "self-update-controls");
  feedbackActions.append(submit, cancel);
  form.append(label, feedbackActions);
  const error = element("p", "self-update-detail");
  error.setAttribute("role", "alert");
  const undo = element("p", "", "Ask me to revert");
  card.append(heading, summary, stage, checks, guard, commit, detail, warning, files, disclosure, links, actions, form, error, undo);

  let row, busy = false;
  function toggleFeedback(open) {
    form.hidden = !open;
    revise.setAttribute("aria-expanded", String(open));
  }
  function render(next) {
    const ui = proposalPresentation(next);
    const changed = !row || row.head !== next.head;
    row = next;
    title.textContent = row.title;
    summary.textContent = row.summary;
    stage.textContent = ui.stage;
    checks.textContent = `CI · ${ui.checks}`;
    checks.hidden = ["discarded", "closed"].includes(row.status);
    guard.textContent = ui.guard;
    guard.hidden = checks.hidden || !ui.guard;
    sha.textContent = row.head;
    detail.textContent = row.detail || "";
    detail.hidden = !row.detail;
    warning.textContent = row.merge_warning || "";
    warning.hidden = !row.merge_warning;
    if (changed) {
      files.replaceChildren(...row.files.map(({ path, added, removed }) => {
        const file = element("li");
        const counts = element("span", "self-update-counts");
        counts.append(element("span", "self-update-added", `+${added}`), element("span", "self-update-removed", `−${removed}`));
        counts.setAttribute("aria-label", `${added} added, ${removed} removed`);
        file.append(element("code", "", path), counts);
        return file;
      }));
      diff.textContent = row.diff;
    }
    pull.hidden = !row.url;
    if (row.url) {
      pull.href = row.url;
      pull.textContent = `Open PR #${row.number}`;
    }
    run.hidden = !row.run_url;
    if (row.run_url) run.href = row.run_url;
    links.hidden = pull.hidden && run.hidden;
    approve.hidden = !(ui.approve || row.status === "waiting");
    approve.disabled = busy || !ui.approve;
    revise.hidden = !ui.revise;
    discard.hidden = !ui.discard;
    refresh.hidden = !ui.refresh;
    actions.hidden = approve.hidden && revise.hidden && discard.hidden && refresh.hidden;
    for (const target of [revise, refresh, discard, submit, feedback, cancel]) target.disabled = busy;
    if (!ui.revise) toggleFeedback(false);
    undo.hidden = !ui.complete;
    announce(row, ui);
  }
  async function act(operation, value) {
    if (busy) return;
    const seen = row.head;
    busy = true;
    error.textContent = "";
    render(row);
    try {
      const result = await perform(operation, row, value);
      if (row.head === seen) render(result);
      if (operation === "revise") {
        feedback.value = "";
        toggleFeedback(false);
      }
    } catch (failure) {
      error.textContent = failure.message;
    } finally {
      busy = false;
      render(row);
      if (document.activeElement === document.body && card.isConnected) title.focus({ preventScroll: true });
    }
  }
  approve.addEventListener("click", () => act("approve"));
  refresh.addEventListener("click", () => act("refresh"));
  discard.addEventListener("click", () => act("discard"));
  revise.addEventListener("click", () => {
    toggleFeedback(form.hidden);
    if (!form.hidden) feedback.focus();
  });
  cancel.addEventListener("click", () => {
    toggleFeedback(false);
    revise.focus();
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (feedback.value.trim()) act("revise", feedback.value);
  });
  render(initial);
  return { card, render };
}
