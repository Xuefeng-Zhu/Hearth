import { icon } from "./icons.js";

const limit = 25;
const get = (id) => document.getElementById(id);
const boxLink = /^https:\/\/app\.box\.com\/file\/[0-9]{1,30}$/;

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text) item.textContent = text;
  return item;
}

export function fileAnswerSources(result, { showSource = true } = {}) {
  const details = node("div", "file-answer-sources");
  if (showSource && result.source) details.append(node("p", "meta", result.source));
  const citations = (result.citations || []).filter((item) => boxLink.test(item.box_url));
  if (citations.length) {
    const list = node("ul", "file-citation-list");
    list.setAttribute("aria-label", "Cited files");
    for (const item of citations) {
      const entry = node("li");
      const link = node("a", "artifact-control", "Open in Box");
      link.href = item.box_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.setAttribute("aria-label", `Open ${item.filename} in Box`);
      link.append(icon("external", 15));
      entry.append(node("span", "", item.filename), link);
      list.append(entry);
    }
    details.append(list);
  }
  if (result.warnings?.length) {
    const warnings = node("ul", "file-answer-warnings meta");
    for (const warning of result.warnings) warnings.append(node("li", "", warning));
    details.append(warnings);
  }
  return details;
}

export function createFileQuestions(api) {
  const dialog = get("file-question-dialog");
  const form = get("file-question-form");
  const scope = get("file-question-scope");
  const picker = get("file-question-picker");
  const list = get("file-question-list");
  const search = get("file-question-search");
  const question = get("file-question-input");
  const submit = get("file-question-submit");
  const status = get("file-question-status");
  const result = get("file-question-result");
  const selected = new Set();
  let files, controller;
  const recent = () => form.elements["file-scope"].value === "recent";

  function selection() {
    picker.hidden = recent();
    get("file-question-limit").hidden = !recent();
    get("file-question-selection").textContent = `${selected.size} of ${limit} selected`;
    scope.disabled = !files.length || !!controller;
    search.disabled = !!controller;
    question.readOnly = !!controller;
    list.querySelectorAll("input").forEach((input) => {
      input.disabled = !!controller || (selected.size === limit && !input.checked);
    });
    submit.disabled = !!controller || !files.length || (!recent() && !selected.size);
  }

  function renderFiles() {
    const query = search.value.trim().toLocaleLowerCase();
    const matches = files.filter((item) => item.ask_filename.toLocaleLowerCase().includes(query));
    list.replaceChildren(...matches.map((item) => {
      const label = node("label", "file-question-choice");
      const input = node("input");
      input.type = "checkbox";
      input.checked = selected.has(item.id);
      input.addEventListener("change", () => {
        if (input.checked) selected.add(item.id);
        else selected.delete(item.id);
        selection();
      });
      label.append(input, node("span", "", item.ask_filename));
      return label;
    }));
    if (!matches.length) list.append(node("p", "meta", "No matching Box files."));
    selection();
  }

  form.addEventListener("change", selection);
  search.addEventListener("input", renderFiles);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submit.disabled || !question.value.trim()) return;
    const body = { question: question.value.trim(), ...(recent() ? {} : { artifact_ids: [...selected] }) };
    const current = controller = new AbortController();
    selection();
    result.hidden = true;
    result.replaceChildren();
    status.textContent = "Reading your Box files…";
    try {
      const answer = await api("/api/artifacts/ask", body, current.signal);
      if (current.signal.aborted) return;
      const title = node("h3", "", "Answer");
      title.id = "file-answer-title";
      title.tabIndex = -1;
      const edit = node("button", "artifact-control", "Edit question");
      edit.type = "button";
      edit.addEventListener("click", () => {
        result.hidden = true;
        form.hidden = false;
        question.focus();
      });
      result.append(title, node("p", "meta file-answer-question", body.question),
        node("p", "file-answer-text", answer.answer), fileAnswerSources(answer, { showSource: false }), edit);
      form.hidden = true;
      result.hidden = false;
      status.textContent = "";
      title.focus();
      title.scrollIntoView({ block: "nearest" });
    } catch (error) {
      if (!current.signal.aborted) status.textContent = error.message;
    } finally {
      if (current === controller) {
        controller = undefined;
        selection();
      }
    }
  });
  get("file-question-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => {
    controller?.abort();
    controller = undefined;
    get("file-question-open").focus();
  });

  return {
    open(snapshot) {
      if (dialog.open) return;
      files = (snapshot?.artifacts || []).filter((row) => row.ask_filename)
        .sort((a, b) => a.ask_filename.localeCompare(b.ask_filename));
      form.reset();
      form.hidden = false;
      selected.clear();
      result.hidden = true;
      result.replaceChildren();
      status.textContent = snapshot?.box_error || (!snapshot ? "Refresh Artifacts to load your Box files."
        : !snapshot.connected ? "Connect Box in Settings to ask about your files."
          : !files.length ? "No supported Box files are available in Artifacts." : "");
      renderFiles();
      dialog.showModal();
      (files.length ? scope.querySelector("input") : get("file-question-close")).focus();
    },
  };
}
