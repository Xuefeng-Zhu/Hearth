const byId = (id) => document.getElementById(id);
const nav = [...document.querySelectorAll("[data-view]")];
const transcript = byId("transcript");
const input = byId("message");
const send = byId("send");
const notice = byId("notice");
const chatScroll = byId("chat-scroll");
const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const modelNames = {
  mock: "Mock", meta: "Muse Spark", openrouter: "OpenRouter", openai: "OpenAI", anthropic: "Claude",
  gemini: "Gemini", ollama: "Ollama Cloud", huggingface: "Hugging Face", digitalocean: "DigitalOcean Inference",
  fireworks: "Fireworks", nscale: "Nscale", parasail: "Parasail", zerogpu: "ZeroGPU", echo: "Echo by Fulcrum",
};
const connectorSettings = {
  pinecone: { field: "index", label: "Index name", placeholder: "hearth-memory", maxLength: 45 },
  agentmail: { field: "inbox_id", label: "Inbox ID", placeholder: "your-inbox@agentmail.to", maxLength: 254 },
};
const connectionLabels = {
  connected: "Connected", unauthorized: "Found but not authorized",
  not_set_up: "Not set up", unknown: "Not checked",
};
const connectionDrafts = new Map();
const gatewayResults = new Map();
const threadDrafts = new Map();
const turns = new Set();
const mainThread = { id: "main", title: "Main", busy: false };
let threadList = [mainThread];
let currentThread = sessionStorage.getItem("hearth-thread") || mainThread.id;
let selectionVersion = 0;
let stateRequest = 0;
let threadSignature;
let chatSignature;
let threadBusy = false;
let state;
let view = "chat";
let selectedFile;
let selectedSource;
let fileRequest = 0;
let memoryFindRequest = 0;
let busy = false;
let timelineTimer;
let connectionState;
let connectionRequest;
let brainSettings;
let brainBusy = false;
let modelRequest;
let settingsSection = "brain";
let reindexPoll;
const preferences = { memory: {}, search: {} };
const memoryNames = { auto: "Auto", keyword: "Keyword", huggingface: "Hugging Face embeddings", pinecone: "Pinecone" };
const folderNames = { root: "Root · USER.md", people: "people/", topics: "topics/", daily: "daily/" };
const brainProvider = byId("brain-provider");
const brainModel = byId("brain-model");
const customModel = byId("brain-custom");

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
  for (const item of document.querySelectorAll(".cards button, #timeline .card button, [data-prompt]")) {
    item.disabled = value;
  }
  renderThreads();
  setBrainControls();
}

function scrollDown() {
  chatScroll.scrollTop = chatScroll.scrollHeight;
}

function nearBottom() {
  return chatScroll.scrollHeight - chatScroll.scrollTop - chatScroll.clientHeight < 65;
}

function messageBubble(role, content, { message, status } = {}) {
  const item = node("article", `message ${role}`);
  if (role === "assistant") {
    const avatar = node("span", "avatar", "✦");
    avatar.setAttribute("aria-label", "Hearth");
    item.append(avatar);
  }
  const body = node("div");
  const text = node("p", "", content);
  const cards = node("div", "cards");
  const notices = node("div");
  notices.setAttribute("role", "status");
  if (status) notices.append(node("p", "queued-label", status));
  body.append(notices, text, cards);
  if (message?.remembered?.length) {
    const sources = node("details", "remembered");
    sources.append(node("summary", "", `Remembered · ${message.remembered.length}`));
    sources.append(...message.remembered.map((hit) => button(memoryLabel(hit), () => openMemorySource(hit))));
    body.append(sources);
  }
  if (message?.id && currentThread !== mainThread.id) {
    const threadId = currentThread;
    const share = button("Share to Main", () => changeThread("share", { thread_id: threadId, message_id: message.id }));
    share.className = "share-message";
    body.append(share);
  }
  item.append(body);
  transcript.append(item);
  return { cards, notices, text };
}

function threadSource(item, fallback = "Main") {
  return threadList.find((thread) => thread.id === item.thread_id)?.title || item.thread_title || fallback;
}

function actionCard(action) {
  const card = node("article", "card");
  const header = node("div", "card-header");
  const statuses = {
    pending: "Awaiting approval", changing: "Interrupted", partial: "Partially applied",
    simulated: "Simulated send", unknown: "Delivery unknown", sending: "Delivery unknown",
    sent: "Sent", complete: action.kind === "gateway" ? "Completed" : "", request_unknown: "Request unconfirmed",
  };
  header.append(node("h4", "", action.title), node("span", "meta", statuses[action.status] || ""));
  card.append(header, node("p", "thread-source", `From ${threadSource(action)}`));
  if (action.kind === "email") {
    card.append(node("p", "", `To: ${action.email.to.join(", ")}`));
    card.append(node("p", "", `Subject: ${action.email.subject}`), node("pre", "", action.email.text));
    if (action.status === "pending") {
      if (action.mocked) card.append(node("p", "meta", "Approval records a simulated send."));
      card.append(button("Approve", () => approve(action)));
    }
  }
  if (action.kind === "gateway") {
    const request = action.request;
    card.append(node("p", "", `${request.provider} · ${request.method} ${request.path}`));
    if (request.body !== null) card.append(node("pre", "", JSON.stringify(request.body, null, 2)));
    if (action.status === "pending") {
      card.append(node("p", "meta", "Hearth saves a checkpoint before the request. Provider changes can persist after a restore."));
      card.append(button("Approve", () => approve(action)));
    }
    if (action.http_status) card.append(node("p", "meta", `Gateway returned HTTP ${action.http_status}.`));
    if (gatewayResults.has(action.id)) {
      const details = node("details");
      details.append(node("summary", "meta", "Gateway response"),
        node("pre", "", JSON.stringify(gatewayResults.get(action.id), null, 2)));
      card.append(details);
    }
  }
  if (action.kind === "remember") {
    card.append(node("p", "", action.fact));
    if (action.status === "pending") card.append(button("Approve", () => approve(action)));
  }
  if (action.paths) card.append(node("p", "", action.paths.join(", ")));
  if (action.job) card.append(node("p", "", action.job.message), node("p", "meta", date(action.job.next_at)));
  if (action.detail) card.append(node("p", "", action.detail));
  if (action.checkpoint) {
    card.append(node("p", "meta", `Checkpoint ${action.checkpoint.id}`));
    if (action.kind !== "gateway" && (action.kind !== "email" || action.mocked)) card.append(button("Undo", () => undo(action)));
  }
  for (const item of card.querySelectorAll("button")) item.disabled = busy;
  return card;
}

function isWorking(thread) {
  return thread?.busy || [...turns].some((turn) => turn.threadId === thread?.id && !turn.finished);
}

function renderThreads() {
  const entries = threadList.map((item) => ({ ...item, busy: isWorking(item) }));
  const active = entries.find((item) => item.id === currentThread);
  const signature = JSON.stringify([entries, currentThread, busy, threadBusy]);
  if (signature === threadSignature) return;
  threadSignature = signature;
  const list = byId("threads");
  const focused = list.contains(document.activeElement) && document.activeElement.dataset.thread;
  list.replaceChildren(...entries.map((thread) => {
    const item = button("", () => selectThread(thread.id));
    item.className = "thread-link";
    item.dataset.thread = thread.id;
    item.title = thread.title;
    item.append(node("span", "", thread.title));
    if (thread.id === currentThread) item.setAttribute("aria-current", "true");
    if (thread.busy) {
      const dot = node("span", "thread-dot");
      dot.setAttribute("aria-hidden", "true");
      item.append(dot, node("span", "visually-hidden", " · Replying"));
    }
    return item;
  }));
  if (focused) [...list.children].find((item) => item.dataset.thread === focused)?.focus();
  const select = byId("thread-select");
  select.replaceChildren(...entries.map((thread) => new Option(`${thread.busy ? "● " : ""}${thread.title}`, thread.id)));
  select.value = currentThread;
  byId("thread-title").textContent = active?.title || (currentThread === mainThread.id ? "Main" : "Side chat");
  byId("thread-activity").hidden = !active?.busy;
  byId("thread-controls").hidden = !active || active.id === mainThread.id;
  byId("new-thread").disabled = busy || threadBusy;
  byId("rename-thread").disabled = busy || threadBusy;
  const remove = byId("delete-thread");
  remove.disabled = busy || threadBusy || !!active?.busy;
  remove.title = active?.busy ? "Wait for this chat to finish" : "Delete this side chat";
  send.title = active?.busy ? "Queue follow-up" : "Send message";
  send.setAttribute("aria-label", send.title);
}

function rememberThread(thread) {
  const index = threadList.findIndex((item) => item.id === thread.id);
  if (index < 0) threadList.push(thread);
  else threadList[index] = { ...threadList[index], ...thread };
}

function renderChat(force = false) {
  renderThreads();
  const actions = new Map((state?.actions || []).map((action) => [action.id, action]));
  const messages = state?.thread_id === currentThread ? state.messages : [];
  const local = [...turns].filter((turn) => turn.threadId === currentThread);
  const signature = JSON.stringify([currentThread, messages, threadList.map((thread) => thread.title), busy,
    messages.flatMap((message) => (message.action_ids || []).map((id) => actions.get(id)))]);
  if (!force && signature === chatSignature) return;
  chatSignature = signature;
  const follow = nearBottom();
  const saved = new Set(messages.map((message) => message.id));
  transcript.replaceChildren();
  byId("welcome").hidden = currentThread !== mainThread.id || !!(messages.length || local.length);
  byId("side-welcome").hidden = currentThread === mainThread.id || !!(messages.length || local.length);
  for (const message of messages) {
    const bubble = messageBubble(message.role, message.content, { message });
    for (const notice of message.notices || []) bubble.notices.append(node("p", "model-warning", notice));
    for (const id of new Set(message.action_ids || [])) {
      if (actions.has(id)) bubble.cards.append(actionCard(actions.get(id)));
    }
  }
  for (const turn of local) {
    turn.bubble = undefined;
    if (!saved.has(turn.user?.id)) {
      messageBubble("user", turn.user?.content || turn.prompt, {
        message: turn.user, status: turn.user ? undefined : "Queued",
      });
    }
    if (saved.has(turn.reply?.id) || (!turn.user && !turn.error)) continue;
    const content = turn.reply?.content || turn.text || turn.error || "Thinking…";
    turn.bubble = messageBubble("assistant", content, { message: turn.reply });
    for (const warning of turn.warnings) turn.bubble.notices.append(node("p", "model-warning", warning));
    for (const action of turn.actions.values()) turn.bubble.cards.append(actionCard(actions.get(action.id) || action));
  }
  if (follow) scrollDown();
}

async function refreshState() {
  const request = ++stateRequest;
  const thread = currentThread;
  const next = await api(`/api/state?thread=${encodeURIComponent(thread)}`, undefined, AbortSignal.timeout(6000));
  if (request !== stateRequest || thread !== currentThread) return false;
  state = next;
  threadList = state.threads;
  if (state.thread_id !== currentThread) {
    threadDrafts.delete(currentThread);
    activateThread(state.thread_id);
  }
  const saved = new Set(state.messages.map((message) => message.id));
  for (const turn of turns) if (saved.has(turn.reply?.id)) turns.delete(turn);
  byId("environment-label").textContent = state.checkpoints === "sprite" ? "Private Sprite" : "Local workspace";
  renderBrain(state);
  return true;
}

function renderBrain({ model, model_id: id }) {
  const name = modelNames[model] || "Unavailable";
  const label = id && model !== "mock" ? `${name} · ${id.split("/").at(-1)}` : name;
  const status = byId("model-status");
  status.textContent = `Brain · ${label}`;
  status.title = id && model !== "mock" ? `${name} · ${id}` : name;
}

function memoryLabel(hit) {
  return `${hit.thread_id ? hit.heading : hit.path} · line ${hit.line}`;
}

async function selectFile(path, hit) {
  selectedFile = path;
  selectedSource = hit;
  const request = ++fileRequest;
  for (const item of byId("files").children) {
    item.setAttribute("aria-pressed", String(item.textContent === path));
  }
  const forget = byId("forget-file");
  forget.hidden = true;
  try {
    const file = hit?.thread_id
      ? await api(`/api/memory/chat?thread=${encodeURIComponent(hit.thread_id)}&message=${encodeURIComponent(hit.message_id)}`)
      : await api(`/api/memory?path=${encodeURIComponent(path)}`);
    if (request !== fileRequest) return;
    byId("file-name").textContent = hit?.thread_id ? memoryLabel(file) : file.path;
    const preview = byId("file-content");
    if (hit?.thread_id || !hit || !file.content) {
      preview.textContent = file.excerpt || file.content || "This note is empty.";
    } else {
      preview.replaceChildren(...file.content.split(/\r?\n/).map((line, index) => {
        const active = index + 1 >= hit.line && index + 1 <= hit.end_line;
        return node("span", `file-line${active ? " is-highlighted" : ""}`, line || " ");
      }));
      preview.querySelector(".is-highlighted")?.scrollIntoView({ block: "nearest" });
    }
    forget.textContent = hit?.thread_id ? "Forget message" : "Forget note";
    forget.hidden = false;
  } catch (error) {
    if (request !== fileRequest) return;
    byId("file-name").textContent = "Memory unavailable";
    byId("file-content").textContent = error.message;
  }
}

async function renderMemory() {
  const { files } = await api("/api/memory");
  const list = byId("files");
  list.replaceChildren(...files.map((path) => button(path, () => selectFile(path))));
  const path = files.includes(selectedFile) || selectedSource?.thread_id ? selectedFile
    : files.includes("USER.md") ? "USER.md" : files[0];
  if (path) {
    await selectFile(path, selectedSource?.path === path ? selectedSource : undefined);
  } else {
    byId("forget-file").hidden = true;
    byId("file-name").textContent = "No memory files";
    byId("file-content").textContent = "";
  }
}

async function openMemorySource(hit) {
  showNotice();
  selectedFile = hit.path;
  selectedSource = hit;
  await openView("memory");
}

async function forgetMemory(hit, excerpt = false) {
  const question = hit.thread_id ? "Forget this message from recall?" : excerpt
    ? `Remove this excerpt from ${hit.path}?` : `Delete the note ${hit.path}?`;
  if (busy || !window.confirm(`${question} Hearth will save a checkpoint first.`)) return;
  setBusy(true);
  try {
    const body = { path: hit.path };
    if (hit.thread_id) body.message_id = hit.message_id;
    else if (excerpt) body.item_id = hit.id;
    await api("/api/memory/forget", body);
    selectedSource = undefined;
    await renderMemory();
    if (byId("memory-query").value.trim()) await findMemory();
    showNotice("Memory forgotten. Undo is available in Timeline.");
  } catch (error) {
    showNotice(error.message);
  } finally {
    setBusy(false);
  }
}

function renderRecall(container, result, allowForget = false) {
  const backend = memoryNames[result.backend];
  container.replaceChildren(node("p", "meta",
    `${backend} · ${result.results.length} ${result.results.length === 1 ? "hit" : "hits"} · ${result.latency_ms.toLocaleString()} ms`));
  for (const warning of result.warnings) container.append(node("p", "meta", warning));
  if (!result.results.length) container.append(node("p", "empty", "No memories matched."));
  for (const hit of result.results) {
    const article = node("article", "result");
    const open = button(memoryLabel(hit), () => openMemorySource(hit));
    open.className = "result-title";
    const score = hit.similarity === null ? `Keyword ${hit.keyword.toFixed(3)}`
      : `Score ${hit.score.toFixed(3)} · Similarity ${hit.similarity.toFixed(3)} · Keyword ${hit.keyword.toFixed(3)}`;
    article.append(open, node("p", "meta", score), node("p", "", hit.excerpt));
    if (allowForget) {
      const remove = button("Forget", () => forgetMemory(hit, true));
      remove.className = "forget-excerpt";
      remove.setAttribute("aria-label", `Forget ${memoryLabel(hit)}`);
      article.append(remove);
    }
    container.append(article);
  }
}

async function findMemory() {
  const container = byId("memory-find-results");
  const query = byId("memory-query").value.trim();
  const request = ++memoryFindRequest;
  container.hidden = !query;
  if (!query) return;
  container.replaceChildren(node("p", "meta", "Searching memory…"));
  try {
    const result = await api("/api/memory/search", { query });
    if (request === memoryFindRequest) renderRecall(container, result, true);
  } catch (error) {
    if (request === memoryFindRequest) container.replaceChildren(node("p", "meta", error.message));
  }
}

function timelineSection(title, items, fallback) {
  const section = node("section", "timeline-section");
  section.append(node("h3", "", title));
  section.append(...(items.length ? items : [node("p", "empty", fallback)]));
  return section;
}

function timelineItem(title, detail, origin) {
  const item = node("article", "card");
  item.append(node("h4", "", title), node("p", "meta", detail), node("p", "thread-source", `From ${origin}`));
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
  const reminders = state.reminders.slice().reverse().map((item) => timelineItem(item.message,
    `Due ${date(item.scheduled_at)}`, threadSource(item)));
  const scheduled = state.jobs.filter((job) => job.status === "scheduled")
    .sort((a, b) => a.next_at.localeCompare(b.next_at));
  reminders.push(...scheduled.map((job) => timelineItem(job.message,
    `Scheduled for ${date(job.next_at)}${job.cron ? ` · ${job.cron} UTC` : ""}`, threadSource(job))));
  timeline.replaceChildren(
    timelineSection("Reminders", reminders, "No reminders scheduled."),
    timelineSection("Checkpoints", checkpoints.map((item) => timelineItem(
      item.comment || "Sprite checkpoint", [item.id, date(item.created_at)].filter(Boolean).join(" · "),
      threadSource(item, "Workspace"))), checkpointStatus),
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

function externalLink(label, url) {
  const link = node("a", "", label);
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function connectorForm(provider, entry, info) {
  const form = node("form", "connector-settings");
  const inputId = `connection-${provider}`;
  const label = node("label", "", info.label);
  label.htmlFor = inputId;
  const field = node("input");
  field.id = inputId;
  field.type = info.field === "inbox_id" ? "email" : "text";
  field.required = info.field === "index";
  field.maxLength = info.maxLength;
  field.autocomplete = "off";
  field.spellcheck = false;
  field.placeholder = info.placeholder;
  field.value = connectionDrafts.get(provider) ?? entry.settings[info.field];
  field.addEventListener("input", () => connectionDrafts.set(provider, field.value));
  const save = node("button", "", "Save");
  save.type = "submit";
  save.setAttribute("aria-label", `Save ${entry.name} settings`);
  const controls = node("div", "connector-controls");
  controls.append(field, save);
  form.append(label, controls);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    updateConnections("settings", { provider, value: field.value });
  });
  return form;
}

function connectionCard(provider, entry) {
  const card = node("article", "card connection-card");
  card.dataset.provider = provider;
  const heading = node("div", "card-header");
  heading.append(node("h4", "", entry.name), node("span", `connection-status ${entry.status}`, connectionLabels[entry.status]));
  const metadata = [entry.category, entry.auth].filter(Boolean).join(" · ");
  card.append(heading, node("p", "meta", metadata), node("p", "connection-description", entry.description));
  if (Object.hasOwn(connectorSettings, provider)) card.append(connectorForm(provider, entry, connectorSettings[provider]));
  if (entry.test_detail) card.append(node("p", `connection-test ${entry.test_status}`, entry.test_detail));

  const footer = node("div", "connector-footer");
  const access = node("span", "connector-access", entry.access_rule);
  const links = node("div", "connector-links");
  links.append(externalLink("Open in Fly ↗", entry.dashboard_url), externalLink("Docs ↗", entry.docs_url));
  footer.append(access, links);
  if (entry.test_path) {
    const test = button("Test", () => updateConnections("test", { provider }));
    test.setAttribute("aria-label", `Test ${entry.name}`);
    test.dataset.canTest = String(entry.can_test);
    test.disabled = !entry.can_test;
    if (!entry.can_test) test.title = "Authorize this connector in Fly, then re-scan.";
    links.append(test);
  }
  card.append(footer);
  return card;
}

function renderConnections() {
  if (!connectionState) return;
  const entries = Object.entries(connectionState.providers);
  const filter = byId("connector-category");
  const category = filter.value;
  const categories = [...new Set(entries.map(([, entry]) => entry.category))].sort();
  if (categories.join("|") !== filter.dataset.categories) {
    filter.replaceChildren(new Option("All categories", ""), ...categories.map((name) => new Option(name, name)));
    filter.value = categories.includes(category) ? category : "";
    filter.dataset.categories = categories.join("|");
  }

  const terms = byId("connector-search").value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const pinned = [];
  const more = [];
  for (const [provider, entry] of entries) {
    const searchable = [provider, entry.gateway_provider, entry.name, entry.category, entry.auth, entry.description]
      .join(" ").toLowerCase();
    if ((filter.value && entry.category !== filter.value) || !terms.every((term) => searchable.includes(term))) continue;
    (entry.pinned ? pinned : more).push(connectionCard(provider, entry));
  }
  byId("pinned-section").hidden = !pinned.length;
  byId("catalog-section").hidden = !more.length;
  byId("pinned-connections").replaceChildren(...pinned);
  byId("catalog-connections").replaceChildren(...more);
  const count = byId("connector-count");
  const matches = pinned.length + more.length;
  count.hidden = false;
  count.textContent = matches ? `${matches} of ${entries.length} providers` : "No providers match your filters.";
  if (connectionRequest) setConnectionsBusy(true);
  renderBrain(connectionState);
}

function setConnectionsBusy(value) {
  byId("rescan-connections").disabled = value;
  for (const control of byId("connections-view").querySelectorAll(".connection-grid button, .connection-grid input")) {
    control.disabled = value || control.dataset.canTest === "false";
  }
}

function updateConnections(operation, body = {}) {
  if (connectionRequest) return connectionRequest;
  const feedback = byId("connection-notice");
  const name = connectionState?.providers[body.provider]?.name;
  feedback.textContent = { rescan: "Checking connections…", test: `Testing ${name}…`, settings: "Saving settings…" }[operation];
  setConnectionsBusy(true);
  connectionRequest = (async () => {
    try {
      connectionState = await api(`/api/connections/${operation}`, body);
      if (operation === "settings") connectionDrafts.delete(body.provider);
      renderConnections();
      const entry = connectionState.providers[body.provider];
      feedback.textContent = {
        rescan: connectionState.scan_error || `Last checked ${date(connectionState.last_scan)}.`,
        test: entry ? `${name} · ${entry.test_detail}` : "",
        settings: `${name} settings saved.`,
      }[operation];
    } catch (error) {
      feedback.textContent = error.message;
      if (!connectionState) {
        try {
          connectionState = await api("/api/connections");
          renderConnections();
        } catch {
          // The request message remains visible until a re-scan succeeds.
        }
      }
    } finally {
      connectionRequest = undefined;
      setConnectionsBusy(false);
    }
  })();
  return connectionRequest;
}

function brainChoice() {
  return brainSettings?.providers.find((entry) => entry.provider === brainProvider.value);
}

function brainDraft() {
  return {
    provider: brainProvider.value,
    model: brainChoice() ? brainModel.value || customModel.value.trim() : "",
  };
}

function setBrainControls() {
  const choice = brainChoice();
  const locked = !brainSettings || brainBusy || busy;
  const usable = !choice || (choice.available && choice.supported);
  const custom = !!choice && !brainModel.value;
  const needsModel = !!choice && !brainDraft().model;
  brainProvider.disabled = locked;
  brainModel.disabled = locked || !usable || !!modelRequest;
  customModel.disabled = brainModel.disabled;
  byId("brain-custom-field").hidden = !custom;
  byId("brain-test").disabled = byId("brain-save").disabled = locked || !usable || !!modelRequest || needsModel;
}

function brainFeedback(message = "") {
  byId("brain-feedback").hidden = !message;
  byId("brain-feedback").textContent = message;
}

async function loadBrainModels() {
  modelRequest?.abort();
  modelRequest = undefined;
  const choice = brainChoice();
  const detail = byId("brain-provider-detail");
  const modelDetail = byId("brain-model-detail");
  byId("brain-model-fields").hidden = !choice;
  if (!choice) {
    detail.textContent = brainProvider.value === "auto"
      ? "Hearth tries Muse Spark first, then other connected chat providers, then Mock."
      : "Use Hearth’s offline demo model.";
    setBrainControls();
    return;
  }
  detail.textContent = choice.available ? "Connected through Fly Sprites." : "This saved provider is disconnected.";
  const saved = brainSettings.selection;
  const selected = saved.provider === choice.provider ? saved.model : choice.default_model;
  brainModel.replaceChildren(new Option("Enter a model ID…", ""));
  customModel.value = selected;
  modelDetail.textContent = choice.available ? "Loading chat models…" : "Re-scan in Connections after authorizing this provider.";
  if (!choice.available || !choice.supported) {
    setBrainControls();
    return;
  }
  const controller = modelRequest = new AbortController();
  setBrainControls();
  try {
    const { models, detail } = await api(`/api/brain/models?provider=${encodeURIComponent(choice.provider)}`,
      undefined, controller.signal);
    if (modelRequest !== controller) return;
    brainModel.prepend(...models.map((model) => new Option(model, model)));
    brainModel.value = models.includes(selected) ? selected : selected ? "" : models[0] || "";
    modelDetail.textContent = detail || `${models.length} chat models available.`;
  } catch (error) {
    if (modelRequest === controller) modelDetail.textContent = error.message;
  } finally {
    if (modelRequest === controller) {
      modelRequest = undefined;
      setBrainControls();
    }
  }
}

async function openBrainSettings() {
  if (brainBusy) return;
  brainSettings = undefined;
  setBrainControls();
  brainFeedback();
  byId("brain-test-result").hidden = true;
  try {
    await updateConnections("rescan");
    if (view !== "settings") return;
    brainSettings = await api("/api/brain");
    const saved = brainSettings.selection.provider;
    const providers = brainSettings.providers.map((entry) => {
      const suffix = !entry.available ? " (disconnected)" : !entry.supported ? " (chat unavailable)" : "";
      const option = new Option(entry.name + suffix, entry.provider);
      option.disabled = !entry.supported;
      return option;
    });
    brainProvider.replaceChildren(new Option("Auto", "auto"), ...providers, new Option("Mock", "mock"));
    brainProvider.value = saved;
    renderBrain(brainSettings);
    brainFeedback(brainSettings.scan_error || "");
    await loadBrainModels();
  } catch (error) {
    brainFeedback(error.message);
  }
}

function clearBrainTest() {
  brainFeedback();
  byId("brain-test-result").hidden = true;
}

async function updateBrain(operation) {
  if (brainBusy || busy || modelRequest) return;
  const draft = brainDraft();
  brainBusy = true;
  setBrainControls();
  if (operation === "test") byId("brain-test-result").hidden = true;
  brainFeedback(operation === "test" ? "Testing the selected model…" : "Saving brain settings…");
  try {
    const result = await api(`/api/brain/${operation}`, draft);
    if (operation === "test") {
      byId("brain-test-latency").textContent = `Test reply · ${result.latency_ms.toLocaleString()} ms`;
      byId("brain-test-reply").textContent = result.reply;
      byId("brain-test-result").hidden = false;
      brainFeedback();
    } else {
      brainSettings = result;
      renderBrain(result);
      brainFeedback("Brain settings saved.");
    }
  } catch (error) {
    brainFeedback(error.message);
  } finally {
    brainBusy = false;
    setBrainControls();
  }
}

function settingOptions(select, options, selected) {
  select.replaceChildren(...options.map(([value, label, disabled]) => {
    const option = new Option(label, value);
    option.disabled = !!disabled && value !== selected;
    return option;
  }));
  select.value = selected;
}

function renderMemoryPreferences(info) {
  const choice = info.selection;
  settingOptions(byId("memory-backend"), Object.entries(memoryNames).map(([value, name]) => {
    const disconnected = value !== "auto" && !info.available[value];
    return [value, disconnected ? `${name} · Connect in Connections` : name, disconnected];
  }), choice.backend);
  settingOptions(byId("memory-model"), Object.entries(info.models), choice.model);
  byId("memory-top-k").value = choice.top_k;
  byId("memory-similarity").value = choice.min_similarity;
  byId("memory-chat-history").checked = choice.include_chat;
  byId("memory-remember").value = choice.auto_remember;
  const header = node("div", "scope-row");
  header.append(node("span", "", "Folder"), node("span", "", "Include"), node("span", "", "Exclude"));
  const scope = byId("memory-folders");
  scope.replaceChildren(header, ...info.folders.map((folder) => {
    const row = node("div", "scope-row");
    row.append(node("span", "", folderNames[folder]));
    for (const field of ["include", "exclude"]) {
      const check = node("input");
      check.type = "checkbox";
      check.checked = choice[field].includes(folder);
      check.dataset[field] = folder;
      check.setAttribute("aria-label", `${field === "include" ? "Include" : "Exclude"} ${folderNames[folder]}`);
      row.append(check);
    }
    return row;
  }));
  updateReindex(info.reindex);
}

function renderSearchPreferences(info) {
  const choice = info.selection;
  const options = info.providers.map((entry) => [entry.provider, entry.connected ? entry.name
    : `${entry.name} · Connect in Connections`, !entry.connected]);
  settingOptions(byId("search-provider"), [["auto", "Auto"], ["off", "Off"], ...options], choice.provider);
  byId("search-limit").value = choice.max_results;
  byId("search-recency").value = choice.recency;
  byId("search-safe").checked = choice.safe_search;
  byId("search-include").value = choice.include_domains.join(", ");
  byId("search-exclude").value = choice.exclude_domains.join(", ");
  byId("search-connections").replaceChildren(...info.providers.map((entry) => {
    const row = node("li");
    row.append(node("span", "", entry.name), entry.connected ? node("span", "meta", "Connected")
      : button("Connect in Connections", () => openView("connections")));
    return row;
  }));
}

function updatePreferenceControls(feature) {
  const { info, pending, indexing } = preferences[feature];
  byId(`${feature}-fields`).disabled = !info || !!pending || !!indexing;
  const test = byId(`${feature}-test-form`).querySelector("button");
  test.disabled = !info || !!pending || !!indexing;
  if (!info) return;
  if (feature === "memory") {
    const backend = byId("memory-backend").value;
    byId("memory-backend-detail").textContent = {
      auto: "Pinecone → Hugging Face → Keyword",
      keyword: "Matches words locally and works offline.",
      huggingface: "Embeds queries and in-scope text via the Sprite gateway.",
      pinecone: "Uses Pinecone inference first, with Hugging Face embeddings if compatible.",
    }[backend];
    byId("memory-model").disabled = backend === "keyword";
    byId("memory-similarity").disabled = backend === "keyword";
    byId("memory-reindex").disabled = !!pending || !!indexing;
  } else {
    const provider = byId("search-provider").value;
    const connected = info.providers.filter((entry) => entry.connected);
    const active = provider === "auto" ? connected[0] : connected.find((entry) => entry.provider === provider);
    test.disabled ||= !active;
    byId("search-safe-detail").hidden = !byId("search-safe").checked || !active || active.native_safe;
    byId("search-provider-detail").textContent = provider === "off" ? "Web search is off."
      : active ? provider === "auto" ? `Auto starts with ${active.name}.` : `${active.name} is connected.`
        : "No selected provider is connected. Connect in Connections.";
  }
}

function updateReindex(job) {
  clearTimeout(reindexPoll);
  const status = byId("memory-index-status");
  const progress = byId("memory-index-progress");
  const running = job?.status === "running";
  preferences.memory.indexing = running;
  progress.hidden = !running;
  if (job?.unique) {
    progress.max = job.unique;
    progress.value = job.embedded + job.reused;
  } else {
    progress.removeAttribute("value");
  }
  if (!job) status.textContent = "New and edited text is indexed as Hearth recalls it.";
  else if (running) {
    status.textContent = job.phase === "checkpoint" ? "Saving checkpoint…"
      : job.unique ? `Indexing · ${job.embedded + job.reused} of ${job.unique} distinct excerpts` : "Scanning excerpts…";
  } else if (job.status === "failed") status.textContent = job.error;
  else {
    status.textContent = `${memoryNames[job.backend]} · ${job.total} excerpts · ${job.embedded} embedded · ${job.reused} reused · ${job.latency_ms.toLocaleString()} ms`;
    if (job.warnings?.length) status.textContent += ` ${job.warnings.join(" ")}`;
  }
  updatePreferenceControls("memory");
  if (running && view === "settings" && settingsSection === "memory") {
    reindexPoll = setTimeout(async () => {
      try {
        updateReindex((await api("/api/memory/reindex")).reindex);
      } catch (error) {
        status.textContent = error.message;
        preferences.memory.indexing = false;
        updatePreferenceControls("memory");
      }
    }, 650);
  }
}

function readPreferences(feature) {
  if (feature === "search") {
    const domains = (id) => byId(id).value.split(/[\s,]+/).filter(Boolean);
    return { provider: byId("search-provider").value, max_results: byId("search-limit").valueAsNumber,
      recency: byId("search-recency").value, safe_search: byId("search-safe").checked,
      include_domains: domains("search-include"), exclude_domains: domains("search-exclude") };
  }
  const scope = (field) => [...byId("memory-folders").querySelectorAll(`[data-${field}]:checked`)]
    .map((element) => element.dataset[field]);
  return { backend: byId("memory-backend").value, model: byId("memory-model").value,
    top_k: byId("memory-top-k").valueAsNumber, min_similarity: byId("memory-similarity").valueAsNumber,
    include_chat: byId("memory-chat-history").checked, auto_remember: byId("memory-remember").value,
    include: scope("include"), exclude: scope("exclude") };
}

async function openSettings(section) {
  settingsSection = section;
  clearTimeout(reindexPoll);
  for (const item of document.querySelectorAll("[data-settings]")) {
    const active = item.dataset.settings === section;
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
    byId(`settings-${item.dataset.settings}`).hidden = !active;
  }
  if (section === "brain") return openBrainSettings();
  if (preferences[section].pending) return;
  try {
    const info = await api(`/api/${section}/settings`);
    if (view !== "settings" || settingsSection !== section || preferences[section].pending) return;
    preferences[section].info = info;
    if (section === "memory") renderMemoryPreferences(info);
    else renderSearchPreferences(info);
    updatePreferenceControls(section);
  } catch (error) {
    byId(`${section}-feedback`).textContent = error.message;
  }
}

function renderSearchTest(container, result) {
  const provider = preferences.search.info.providers.find((item) => item.provider === result.provider);
  container.replaceChildren(node("p", "meta", `${provider?.name || result.provider} · ${result.results.length} results · ${result.latency_ms.toLocaleString()} ms`));
  for (const warning of result.warnings) container.append(node("p", "meta", warning));
  if (!result.results.length) container.append(node("p", "empty", "No search results."));
  for (const hit of result.results) {
    const article = node("article", "result");
    const link = node("a", "result-title", hit.title);
    link.href = hit.url;
    link.target = "_blank";
    link.rel = "noreferrer noopener";
    article.append(link, node("p", "meta", hit.published ? `${hit.url} · ${hit.published}` : hit.url));
    if (hit.snippet) article.append(node("p", "", hit.snippet));
    container.append(article);
  }
}

async function changePreferences(feature, operation) {
  const state = preferences[feature];
  const form = byId(`${feature}-settings-form`);
  if (!state.info || state.pending || state.indexing || busy) return;
  if (operation !== "reindex" && !form.reportValidity()) return;
  const selection = readPreferences(feature);
  const feedback = byId(`${feature}-feedback`);
  const results = byId(`${feature}-test-results`);
  const query = operation === "test" ? byId(`${feature}-test-query`).value.trim() : "";
  if (operation === "test" && !query) return;
  state.pending = operation;
  updatePreferenceControls(feature);
  feedback.textContent = "";
  if (operation === "test") results.replaceChildren(node("p", "meta", "Testing…"));
  if (operation === "settings") feedback.textContent = "Saving settings…";
  try {
    const result = await api(`/api/${feature}/${operation}`, operation === "test" ? { selection, query }
      : operation === "reindex" ? {} : selection);
    if (operation === "reindex") {
      updateReindex(result);
    } else if (operation === "test") {
      if (feature === "memory") renderRecall(results, result);
      else renderSearchTest(results, result);
    } else {
      state.info = result;
      if (feature === "memory") renderMemoryPreferences(result);
      else renderSearchPreferences(result);
      feedback.textContent = "Settings saved.";
    }
  } catch (error) {
    const target = operation === "test" ? results : feedback;
    target.textContent = error.message;
  } finally {
    state.pending = undefined;
    updatePreferenceControls(feature);
  }
}

async function refreshView() {
  if (!await refreshState()) return;
  if (view === "chat") renderChat();
  else if (view === "memory") await renderMemory();
  else if (view === "timeline") await renderTimeline();
}

async function openView(nextView) {
  view = nextView;
  clearTimeout(timelineTimer);
  clearTimeout(reindexPoll);
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
  if (view === "connections") {
    await updateConnections("rescan");
  } else if (view === "settings") {
    await openSettings(settingsSection);
  } else if (!busy) {
    try {
      await refreshView();
    } catch (error) {
      showNotice(error.message);
    }
  }
}

function activateThread(threadId) {
  if (currentThread === threadId) return;
  threadDrafts.set(currentThread, input.value);
  currentThread = threadId;
  selectionVersion++;
  sessionStorage.setItem("hearth-thread", threadId);
  input.value = threadDrafts.get(threadId) || "";
  input.placeholder = threadId === mainThread.id ? "Message Hearth…" : "Message this side chat…";
  resizeInput();
  renderChat(true);
  scrollDown();
}

async function selectThread(threadId, focus = false) {
  activateThread(threadId);
  showNotice();
  if (focus && view === "chat") input.focus();
  try {
    await refreshView();
  } catch (error) {
    if (currentThread === threadId) showNotice(error.message);
  }
}

async function changeThread(operation, body = {}) {
  if (threadBusy || busy) return;
  threadBusy = true;
  renderThreads();
  const selection = selectionVersion;
  try {
    await connectionRequest;
    const result = await api(`/api/threads/${operation}`, body);
    if (operation === "create" || operation === "rename") rememberThread(result);
    if (operation === "create" && selection === selectionVersion) {
      await selectThread(result.id, true);
    } else if (operation === "delete") {
      threadList = threadList.filter((item) => item.id !== body.thread_id);
      if (currentThread === body.thread_id) activateThread(mainThread.id);
      threadDrafts.delete(body.thread_id);
      for (const turn of turns) if (turn.threadId === body.thread_id) turns.delete(turn);
      await refreshView();
      showNotice("Side chat deleted. Its checkpoint is in Timeline.");
    } else {
      await refreshView();
      if (operation === "share") showNotice("Shared to Main.");
    }
  } catch (error) {
    showNotice(error.message);
  } finally {
    threadBusy = false;
    renderThreads();
  }
}

function readChatEvent(turn, name, payload) {
  if (name === "queued") {
    turn.threadId = payload.thread.id;
    turn.prompt = payload.prompt;
    rememberThread(payload.thread);
    if (turn.command && turn.selection === selectionVersion) {
      activateThread(turn.threadId);
      if (view === "chat") input.focus();
    }
  } else if (name === "started") {
    turn.user = payload.message;
    rememberThread(payload.thread);
  } else if (name === "token" || name === "reset") {
    const follow = turn.threadId === currentThread && nearBottom();
    turn.text = name === "reset" ? "" : turn.text + payload.text;
    if (turn.bubble) turn.bubble.text.textContent = turn.text || payload.message || "Thinking…";
    if (follow) scrollDown();
    return;
  } else if (name === "action") {
    turn.actions.set(payload.id, payload);
  } else if (name === "model_warning") {
    turn.warnings.push(payload.message);
  } else if (name === "done") {
    turn.reply = payload.message;
  } else if (name === "error") {
    throw new Error(payload.message);
  }
  if (turn.threadId === currentThread) renderChat(true);
  else renderThreads();
}

async function chat(prompt) {
  prompt = prompt.trim();
  if (!prompt || busy) return;
  const source = currentThread;
  const command = source === mainThread.id && /^\/(side|btw)(?:\s|$)/i.test(prompt);
  const turn = { threadId: command ? undefined : source, selection: selectionVersion, command,
    prompt, text: "", warnings: [], actions: new Map() };
  for (const previous of turns) if (previous.threadId === source && previous.error) turns.delete(previous);
  turns.add(turn);
  showNotice();
  input.value = "";
  resizeInput();
  renderChat(true);
  scrollDown();
  try {
    await connectionRequest;
    const response = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: prompt, thread_id: source }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error || "Hearth could not start this turn.");
    }
    let buffered = "";
    for await (const chunk of response.body.pipeThrough(new TextDecoderStream())) {
      buffered += chunk;
      let split;
      while ((split = buffered.indexOf("\n\n")) >= 0) {
        const packet = buffered.slice(0, split);
        buffered = buffered.slice(split + 2);
        const [event, data] = packet.split("\n");
        if (event.startsWith("event: ") && data?.startsWith("data: ")) {
          readChatEvent(turn, event.slice(7), JSON.parse(data.slice(6)));
        }
      }
    }
    if (!turn.reply) throw new Error("The reply was interrupted. Check Timeline for any saved actions.");
  } catch (error) {
    turn.error = error.message;
    if (!turn.user) {
      turns.delete(turn);
      if (source === currentThread && !input.value) {
        input.value = prompt;
        resizeInput();
      }
    }
    if ((turn.threadId || source) === currentThread) showNotice(error.message);
  } finally {
    turn.finished = true;
    if (turn.threadId === currentThread || !turn.threadId) renderChat(true);
    else renderThreads();
    await refreshView().catch(() => {});
  }
}

async function approve(action) {
  if (busy) return;
  setBusy(true);
  showNotice();
  try {
    const result = await api("/api/approve", { id: action.id });
    if (result.response) gatewayResults.set(action.id, result.response);
    await refreshView();
    const message = {
      sent: "Email sent.", simulated: "Simulated send recorded. Undo is available on the card.",
      unknown: "AgentMail could not confirm delivery. Check your inbox’s sent messages.",
    };
    if (action.kind === "remember") showNotice("Fact remembered.");
    else if (action.kind === "gateway") showNotice(result.status === "complete"
      ? "Connector request completed." : "The gateway could not confirm the request.");
    else showNotice(message[result.status]);
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
    const deadline = Date.now() + 115_000;
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
byId("thread-select").addEventListener("change", (event) => selectThread(event.target.value));
byId("new-thread").addEventListener("click", () => changeThread("create"));
byId("rename-thread").addEventListener("click", () => {
  const thread = threadList.find((item) => item.id === currentThread);
  if (!thread) return;
  const title = window.prompt("Rename side chat", thread.title)?.trim();
  if (title && title !== thread.title) changeThread("rename", { thread_id: thread.id, title });
});
byId("delete-thread").addEventListener("click", () => {
  const thread = threadList.find((item) => item.id === currentThread);
  if (thread && window.confirm(`Delete “${thread.title}”? Hearth will save a checkpoint first.`)) {
    changeThread("delete", { thread_id: thread.id });
  }
});
byId("connector-search").addEventListener("input", renderConnections);
byId("connector-category").addEventListener("change", renderConnections);
byId("rescan-connections").addEventListener("click", () => updateConnections("rescan"));
brainProvider.addEventListener("change", () => {
  clearBrainTest();
  loadBrainModels();
});
brainModel.addEventListener("change", () => {
  clearBrainTest();
  setBrainControls();
  if (!brainModel.value) customModel.focus();
});
customModel.addEventListener("input", () => {
  clearBrainTest();
  setBrainControls();
});
byId("brain-test").addEventListener("click", () => updateBrain("test"));
byId("brain-form").addEventListener("submit", (event) => {
  event.preventDefault();
  updateBrain("settings");
});
byId("memory-find").addEventListener("submit", (event) => {
  event.preventDefault();
  findMemory();
});
byId("memory-query").addEventListener("input", (event) => {
  if (!event.target.value) findMemory();
});
byId("forget-file").addEventListener("click", () => {
  if (selectedFile) forgetMemory(selectedSource || { path: selectedFile });
});
for (const tab of document.querySelectorAll("[data-settings]")) {
  tab.addEventListener("click", () => openSettings(tab.dataset.settings));
}
for (const feature of ["memory", "search"]) {
  byId(`${feature}-settings-form`).addEventListener("submit", (event) => {
    event.preventDefault();
    changePreferences(feature, "settings");
  });
  byId(`${feature}-settings-form`).addEventListener("change", () => updatePreferenceControls(feature));
  byId(`${feature}-test-form`).addEventListener("submit", (event) => {
    event.preventDefault();
    changePreferences(feature, "test");
  });
}
byId("memory-reindex").addEventListener("click", () => changePreferences("memory", "reindex"));
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
  if ((view === "chat" || view === "timeline") && !document.hidden && !busy) {
    refreshView().catch((error) => showNotice(error.message));
  }
});
let polling = false;
setInterval(async () => {
  if (view !== "chat" || busy || threadBusy || document.hidden || polling) return;
  polling = true;
  try {
    await refreshView();
  } catch {
    // A transient connection failure leaves the visible conversation intact.
  } finally {
    polling = false;
  }
}, 3_000);
renderChat(true);
openView("chat");
updateConnections("rescan");
