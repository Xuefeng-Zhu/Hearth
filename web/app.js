const byId = (id) => document.getElementById(id);
const nav = [...document.querySelectorAll("[data-view]")];
const transcript = byId("transcript");
const input = byId("message");
const send = byId("send");
const notice = byId("notice");
const chatScroll = byId("chat-scroll");
const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const modelNames = { mock: "Mock model", meta: "Muse Spark", ollama: "Ollama Cloud", openrouter: "OpenRouter" };
let state;
let view = "chat";
let selectedFile;
let busy = false;
let timelineTimer;

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}

function button(label, action) {
  const item = node("button", "", label);
  item.type = "button";
  item.addEventListener("click", action);
  return item;
}

function showNotice(message = "") {
  notice.hidden = !message;
  notice.textContent = message;
}

async function api(path, data, signal) {
  const options = data === undefined ? { signal } : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data), signal,
  };
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || "Hearth is temporarily unavailable.");
  }
  return response.json();
}

function date(value) {
  return value ? dateFormat.format(new Date(value)) : "";
}

function setBusy(value) {
  busy = value;
  send.disabled = value;
  for (const item of document.querySelectorAll(".card button, [data-prompt]")) {
    item.disabled = value;
  }
}

function scrollDown() {
  chatScroll.scrollTop = chatScroll.scrollHeight;
}

function messageBubble(role, content) {
  const item = node("article", `message ${role}`);
  if (role === "assistant") {
    const avatar = node("span", "avatar", "✦");
    avatar.setAttribute("aria-label", "Hearth");
    item.append(avatar);
  }
  const body = node("div");
  const text = node("p", "", content);
  const cards = node("div", "cards");
  body.append(text, cards);
  item.append(body);
  transcript.append(item);
  return { cards, text };
}

function actionCard(action) {
  const card = node("article", "card");
  const header = node("div", "card-header");
  const statuses = {
    pending: "Awaiting approval", changing: "Interrupted", partial: "Partially applied",
    simulated: "Simulated send", unknown: "Delivery unknown", sending: "Delivery unknown",
    sent: "Sent", complete: "",
  };
  header.append(node("h4", "", action.title), node("span", "meta", statuses[action.status] || ""));
  card.append(header);
  if (action.kind === "email") {
    card.append(node("p", "", `To: ${action.email.to.join(", ")}`));
    card.append(node("p", "", `Subject: ${action.email.subject}`), node("pre", "", action.email.text));
    if (action.status === "pending") {
      if (action.mocked) card.append(node("p", "meta", "Approval records a simulated send."));
      card.append(button("Approve", () => approve(action)));
    }
  }
  if (action.paths) card.append(node("p", "", action.paths.join(", ")));
  if (action.job) card.append(node("p", "", action.job.message), node("p", "meta", date(action.job.next_at)));
  if (action.checkpoint) {
    card.append(node("p", "meta", `Checkpoint ${action.checkpoint.id}`));
    if (action.kind !== "email" || action.mocked) card.append(button("Undo", () => undo(action)));
  }
  for (const item of card.querySelectorAll("button")) item.disabled = busy;
  return card;
}

function renderChat() {
  const actions = new Map(state.actions.map((action) => [action.id, action]));
  transcript.replaceChildren();
  byId("welcome").hidden = state.messages.length > 0;
  for (const message of state.messages) {
    const bubble = messageBubble(message.role, message.content);
    for (const id of new Set(message.action_ids || [])) {
      if (actions.has(id)) bubble.cards.append(actionCard(actions.get(id)));
    }
  }
  scrollDown();
}

async function refreshState() {
  state = await api("/api/state", undefined, AbortSignal.timeout(6000));
  byId("environment-label").textContent = state.checkpoints === "sprite" ? "Private Sprite" : "Local workspace";
  byId("model-status").textContent = modelNames[state.model] || "Model unavailable";
}

async function selectFile(path) {
  selectedFile = path;
  for (const item of byId("files").children) {
    item.setAttribute("aria-pressed", String(item.textContent === path));
  }
  try {
    const file = await api(`/api/memory?path=${encodeURIComponent(path)}`);
    if (selectedFile !== path) return;
    byId("file-name").textContent = file.path;
    byId("file-content").textContent = file.content || "This note is empty.";
  } catch (error) {
    showNotice(error.message);
  }
}

async function renderMemory() {
  const { files } = await api("/api/memory");
  const list = byId("files");
  list.replaceChildren(...files.map((path) => button(path, () => selectFile(path))));
  const path = files.includes(selectedFile) ? selectedFile : files.includes("USER.md") ? "USER.md" : files[0];
  if (path) {
    await selectFile(path);
  } else {
    byId("file-name").textContent = "No memory files";
    byId("file-content").textContent = "";
  }
}

function timelineSection(title, items, fallback) {
  const section = node("section", "timeline-section");
  section.append(node("h3", "", title));
  section.append(...(items.length ? items : [node("p", "empty", fallback)]));
  return section;
}

function timelineItem(title, detail) {
  const item = node("article", "card");
  item.append(node("h4", "", title), node("p", "meta", detail));
  return item;
}

async function renderTimeline() {
  clearTimeout(timelineTimer);
  const timeline = byId("timeline");
  let checkpoints = [];
  let checkpointStatus = "No checkpoints yet.";
  try {
    ({ checkpoints } = await api("/api/checkpoints", undefined, AbortSignal.timeout(8000)));
  } catch (error) {
    checkpointStatus = error.message;
  }
  if (view !== "timeline") return;
  const reminders = state.reminders.slice().reverse().map((item) => timelineItem(item.message, `Due ${date(item.scheduled_at)}`));
  const scheduled = state.jobs.filter((job) => job.status === "scheduled")
    .sort((a, b) => a.next_at.localeCompare(b.next_at));
  reminders.push(...scheduled.map((job) => timelineItem(job.message,
    `Scheduled for ${date(job.next_at)}${job.cron ? ` · ${job.cron} UTC` : ""}`)));
  timeline.replaceChildren(
    timelineSection("Reminders", reminders, "No reminders scheduled."),
    timelineSection("Checkpoints", checkpoints.map((item) => timelineItem(
      item.comment || "Sprite checkpoint", [item.id, date(item.created_at)].filter(Boolean).join(" · "))), checkpointStatus),
    timelineSection("Actions", state.actions.slice().reverse().map(actionCard), "No actions yet."),
  );
  if (scheduled.length && !document.hidden) {
    const untilDue = new Date(scheduled[0].next_at).getTime() - Date.now();
    timelineTimer = setTimeout(() => {
      if (view === "timeline" && !busy && !document.hidden) {
        refreshState().then(renderTimeline).catch((error) => showNotice(error.message));
      }
    }, Math.max(3_000, Math.min(2_147_480_000, untilDue + 2_500)));
  }
}

async function refreshView() {
  await refreshState();
  if (view === "chat") renderChat();
  else if (view === "memory") await renderMemory();
  else await renderTimeline();
}

async function openView(nextView) {
  view = nextView;
  clearTimeout(timelineTimer);
  for (const item of nav) {
    const active = item.dataset.view === view;
    if (active) {
      item.setAttribute("aria-current", "page");
      byId("view-title").textContent = item.textContent.trim().split(/\s+/).at(-1);
    } else {
      item.removeAttribute("aria-current");
    }
    byId(`${item.dataset.view}-view`).hidden = !active;
  }
  if (!busy) {
    try {
      await refreshView();
    } catch (error) {
      showNotice(error.message);
    }
  }
}

async function chat(prompt) {
  if (!prompt.trim() || busy) return;
  setBusy(true);
  showNotice();
  input.value = "";
  resizeInput();
  byId("welcome").hidden = true;
  messageBubble("user", prompt);
  const reply = messageBubble("assistant", "Thinking…");
  scrollDown();
  try {
    const response = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: prompt }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error || "Hearth could not start this turn.");
    }
    let text = "";
    let buffered = "";
    let done = false;
    for await (const chunk of response.body.pipeThrough(new TextDecoderStream())) {
      buffered += chunk;
      let split;
      while ((split = buffered.indexOf("\n\n")) >= 0) {
        const packet = buffered.slice(0, split);
        buffered = buffered.slice(split + 2);
        const [event, data] = packet.split("\n");
        const name = event.slice(7);
        const payload = JSON.parse(data.slice(6));
        if (name === "token") reply.text.textContent = text += payload.text;
        if (name === "action") reply.cards.append(actionCard(payload));
        if (name === "reset") reply.text.textContent = (text = "") || payload.message || "Thinking…";
        if (name === "done") done = true;
        if (name === "error") throw new Error(payload.message);
        scrollDown();
      }
    }
    if (!done) throw new Error("The reply was interrupted. Check Timeline for any saved actions.");
    await refreshView();
  } catch (error) {
    if (!reply.text.textContent || reply.text.textContent === "Thinking…") reply.text.textContent = error.message;
    showNotice(error.message);
    if (view !== "chat") await refreshView().catch(() => {});
  } finally {
    setBusy(false);
  }
}

async function approve(action) {
  if (busy) return;
  setBusy(true);
  showNotice();
  try {
    const result = await api("/api/approve", { id: action.id });
    await refreshView();
    const message = {
      sent: "Email sent.", simulated: "Simulated send recorded. Undo is available on the card.",
      unknown: "AgentMail could not confirm delivery. Check your inbox’s sent messages.",
    };
    showNotice(message[result.status]);
  } catch (error) {
    showNotice(error.message);
  } finally {
    setBusy(false);
  }
}

async function undo(action) {
  if (busy || !window.confirm(`Restore checkpoint ${action.checkpoint.id}? This rolls back the workspace, including newer chat, memory, and reminders. Delivered email stays delivered.`)) return;
  setBusy(true);
  showNotice("Restoring checkpoint. Hearth may reconnect…");
  try {
    try {
      await api("/api/undo", { id: action.id }, AbortSignal.timeout(6000));
    } catch (error) {
      if (error.name === "Error") throw error;
    }
    const deadline = Date.now() + 100_000;
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 850));
      try {
        await refreshState();
      } catch {
        continue;
      }
      if (state.restore?.action_id === action.id && state.restore.status === "failed") {
        throw new Error("The checkpoint could not be restored.");
      }
      if (!state.actions.some((item) => item.id === action.id && item.checkpoint?.id === action.checkpoint.id)) {
        await refreshView();
        showNotice(`Restored checkpoint ${action.checkpoint.id}.`);
        return;
      }
    }
    throw new Error("Hearth could not confirm the restore. Refresh Timeline to check the result.");
  } catch (error) {
    showNotice(error.message);
  } finally {
    setBusy(false);
  }
}

function resizeInput() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 132)}px`;
}

byId("composer").addEventListener("submit", (event) => {
  event.preventDefault();
  chat(input.value);
});
input.addEventListener("input", resizeInput);
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    chat(input.value);
  }
});
for (const prompt of document.querySelectorAll("[data-prompt]")) {
  prompt.addEventListener("click", () => chat(prompt.dataset.prompt));
}
for (const item of nav) {
  item.addEventListener("click", () => openView(item.dataset.view));
}
document.addEventListener("visibilitychange", () => {
  if (view === "timeline" && !document.hidden && !busy) refreshView().catch((error) => showNotice(error.message));
});
openView("chat");
