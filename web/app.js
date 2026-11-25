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
const configTabs = ["configured", "not-configured"];
const connectionTabStorage = "hearth-connections-tab";
const connectionPanels = new Map();
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
let connectionTabPreference = localStorage.getItem(connectionTabStorage);
let newlyConfigured = new Set();
let brainSettings;
let brainBusy = false;
let modelRequest;
let routingRequest;
let poolRequest;
let poolModels = {};
let poolDraft = [];
let poolDirty = false;
let settingsSection = "brain";
let reindexPoll;
const preferences = { memory: {}, search: {} };
const memoryNames = { auto: "Auto", keyword: "Keyword", huggingface: "Hugging Face embeddings", pinecone: "Pinecone" };
const folderNames = { root: "Root · USER.md", people: "people/", topics: "topics/", daily: "daily/" };
const brainProvider = byId("brain-provider");
const brainModel = byId("brain-model");
const customModel = byId("brain-custom");
const poolProvider = byId("pool-provider");
const poolModel = byId("pool-model");

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
  if (message?.routing) {
    const route = message.routing;
    const chip = node("p", "routing-chip", `Routed to ${routedModel(route)} — ${route.reason}`);
    chip.title = route.label;
    body.append(chip);
  }
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
    timelineSection("Routing", (state.routing || []).slice().reverse().map((route) => timelineItem(
      route.label, `${route.order.map(routedModel).join(" → ")} — ${route.reason} · ${date(route.at)}`,
      threadSource(route))), "No turns routed yet."),
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
  if (newlyConfigured.delete(provider)) card.classList.add("newly-configured");

  const configured = entry.status === "connected";
  const check = entry.test_status === "passed" ? "ok" : entry.test_status ? "error" : "untested";
  const status = configured ? check : entry.status;
  const labels = {
    ok: "OK", error: "Error", untested: "Untested", unauthorized: "Found but not authorized",
    not_set_up: "Not set up", unknown: "Not checked",
  };
  const heading = node("div", "card-header");
  heading.append(node("h4", "", entry.name), node("span", `connection-status ${status}`, labels[status]));
  card.append(heading);
  if (entry.auth) card.append(node("p", "meta", entry.auth));
  card.append(node("p", "connection-description", entry.description));
  if (configured) {
    const uses = node("p", "connection-uses");
    uses.append(node("strong", "", "Used for"), ` ${entry.uses.join(" · ")}`);
    card.append(uses);
  }
  if (Object.hasOwn(connectorSettings, provider)) card.append(connectorForm(provider, entry, connectorSettings[provider]));
  if (entry.test_detail) card.append(node("p", `connection-test ${entry.test_status}`, entry.test_detail));

  const footer = node("div", "connector-footer");
  const access = node("span", "connector-access", entry.access_rule);
  const links = node("div", "connector-links");
  const flyLabel = configured ? "Open in Fly" : entry.status === "unauthorized" ? "Review in Fly" : "Add in Fly";
  links.append(externalLink(`${flyLabel} ↗`, entry.dashboard_url), externalLink("Docs ↗", entry.docs_url));
  footer.append(access, links);
  if (entry.can_test) {
    const test = button("Test", async () => {
      await updateConnections("test", { provider });
      if (view === "connections" && document.activeElement === document.body) byId(test.id)?.focus();
    });
    test.id = `test-connection-${provider}`;
    test.setAttribute("aria-label", `Test ${entry.name}`);
    if (!entry.test_path) test.title = "Check gateway authorization.";
    links.append(test);
  }
  card.append(footer);
  return card;
}

function connectionHash(tab = "") {
  return tab ? `#connections/${tab}` : "#connections";
}

function tabFromHash() {
  return configTabs.find((tab) => location.hash === connectionHash(tab));
}

function isConnectionsRoute() {
  return location.hash === connectionHash() || Boolean(tabFromHash());
}

function rememberConnectionTab(tab) {
  connectionTabPreference = tab;
  localStorage.setItem(connectionTabStorage, tab);
}

function selectConnectionTab(tab) {
  rememberConnectionTab(tab);
  if (location.hash !== connectionHash(tab)) history.pushState(history.state, "", connectionHash(tab));
  renderConnections();
  connectionPanels.get(tab).button.focus();
}

function syncConnectionRoute() {
  if (isConnectionsRoute()) {
    const tab = tabFromHash();
    if (tab) rememberConnectionTab(tab);
    if (view === "connections") renderConnections();
    else openView("connections", false);
  } else if (view === "connections") {
    openView(history.state?.hearthView || "chat", false);
  }
}

function renderConnections() {
  const entries = Object.entries(connectionState?.providers ?? {});
  const configured = entries.filter(([, entry]) => entry.status === "connected");
  const unconfigured = entries.filter(([, entry]) => entry.status !== "connected");
  const providersByTab = { configured, "not-configured": unconfigured };
  const defaultTab = configured.length ? "configured" : "not-configured";
  const activeConnectionTab = configTabs.includes(connectionTabPreference) ? connectionTabPreference : defaultTab;
  if (view === "connections" && (connectionState || connectionTabPreference === activeConnectionTab)
      && location.hash !== connectionHash(activeConnectionTab)) {
    history.replaceState(history.state, "", connectionHash(activeConnectionTab));
  }

  const categories = [...new Set(entries.map(([, entry]) => entry.category))].sort();
  for (const [tab, controls] of connectionPanels) {
    const selected = tab === activeConnectionTab;
    controls.button.setAttribute("aria-selected", String(selected));
    controls.button.tabIndex = selected ? 0 : -1;
    controls.badge.hidden = !connectionState;
    controls.badge.textContent = providersByTab[tab].length;
    controls.panel.hidden = !selected;
    if (!selected) controls.groups.replaceChildren();
    const filter = controls.filter;
    if (categories.join("|") !== filter.dataset.categories) {
      const category = filter.value;
      filter.replaceChildren(new Option("All categories", ""), ...categories.map((name) => new Option(name, name)));
      filter.value = categories.includes(category) ? category : "";
      filter.dataset.categories = categories.join("|");
    }
  }
  if (!connectionState) return;

  const controls = connectionPanels.get(activeConnectionTab);
  const terms = controls.search.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const matchesFilters = ([provider, entry]) => {
    if (controls.filter.value && controls.filter.value !== entry.category) return false;
    const searchable = [provider, entry.gateway_provider, entry.name, entry.category, entry.auth, entry.description,
      ...entry.uses].join(" ").toLowerCase();
    return terms.every((term) => searchable.includes(term));
  };
  const active = providersByTab[activeConnectionTab];
  const matches = active.filter(matchesFilters);
  const otherTab = configTabs.find((tab) => tab !== activeConnectionTab);
  const otherMatches = terms.length ? providersByTab[otherTab].filter(matchesFilters).length : 0;
  controls.count.textContent = matches.length ? `${matches.length} of ${active.length} providers`
    : active.length ? "No providers match your filters."
    : activeConnectionTab === "configured" ? "No configured connectors yet." : "All providers are configured.";
  controls.link.hidden = !otherMatches;
  controls.link.href = connectionHash(otherTab);
  controls.link.textContent = `${otherMatches} ${otherMatches === 1 ? "match" : "matches"} in the other tab`;
  controls.groups.replaceChildren(...connectionGroups(matches));
  if (connectionRequest) setConnectionsBusy(true);
}

function connectionGroups(entries) {
  const groups = new Map();
  for (const [provider, entry] of entries) {
    const group = entry.pinned ? "Hearth essentials" : entry.category;
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(connectionCard(provider, entry));
  }
  return [...groups].map(([name, cards]) => {
    const section = node("section", "connection-section");
    const grid = node("div", "connection-grid");
    grid.append(...cards);
    section.append(node("h3", "", name), grid);
    return section;
  });
}

function setConnectionsBusy(value) {
  byId("rescan-connections").setAttribute("aria-disabled", String(value));
  for (const control of byId("connections-view").querySelectorAll(".connection-grid button, .connection-grid input")) {
    control.disabled = value;
  }
}

function announceNewConnections(previous, current) {
  const promoted = Object.entries(current.providers).filter(([provider, entry]) =>
    entry.status === "connected" && previous.providers[provider]?.status !== "connected");
  newlyConfigured = new Set(promoted.map(([provider]) => provider));
  const notice = byId("connection-promotion");
  notice.hidden = !promoted.length;
  notice.replaceChildren();
  if (!promoted.length) return;
  const names = promoted.map(([, entry]) => entry.name);
  notice.append(names.length === 1 ? `${names[0]} moved to Configured. ` : `${names.length} connectors moved to Configured. `);
  const link = node("a", "", "Show configured");
  link.href = connectionHash("configured");
  link.addEventListener("click", (event) => {
    event.preventDefault();
    const controls = connectionPanels.get("configured");
    controls.search.value = controls.filter.value = "";
    selectConnectionTab("configured");
  });
  notice.append(link);
}

function updateConnections(operation, body = {}) {
  if (connectionRequest) return connectionRequest;
  const feedback = byId("connection-notice");
  const name = connectionState?.providers[body.provider]?.name;
  feedback.textContent = { rescan: "Checking connections…", test: `Testing ${name}…`, settings: "Saving settings…" }[operation];
  setConnectionsBusy(true);
  connectionRequest = (async () => {
    try {
      const previous = connectionState;
      connectionState = await api(`/api/connections/${operation}`, body);
      if (operation === "rescan" && previous && !connectionState.scan_error) {
        announceNewConnections(previous, connectionState);
      }
      if (operation === "settings") connectionDrafts.delete(body.provider);
      renderConnections();
      renderBrain(connectionState);
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
          renderBrain(connectionState);
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
    ...(poolDirty ? { pool: poolDraft } : {}),
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
  byId("routing-test").disabled = byId("brain-save").disabled;
  byId("brain-pool").disabled = locked;
  poolModel.disabled = !!poolRequest || !poolProvider.value;
  byId("pool-add").disabled = poolModel.disabled || !poolModel.value || poolDraft.length >= 32;
}

function routedModel(model) {
  if (!model) return "—";
  return `${model.name} · ${model.model || "Automatic model"}`;
}

function renderRoutingPreview(plans) {
  byId("routing-preview").replaceChildren(...plans.map((plan) => {
    const row = node("tr");
    const type = node("th", "", plan.label);
    type.scope = "row";
    const model = node("td", "", routedModel(plan.order[0]));
    model.title = plan.reason;
    row.append(type, model);
    return row;
  }));
}

async function previewRouting(prompt) {
  routingRequest?.abort();
  const result = byId("routing-result");
  result.hidden = true;
  if (byId("brain-save").disabled) return;
  const status = byId("routing-preview-status");
  const controller = routingRequest = new AbortController();
  status.textContent = "Updating routing preview…";
  try {
    const { preview, test } = await api("/api/brain/route", {
      ...brainDraft(), ...(prompt === undefined ? {} : { prompt }),
    }, controller.signal);
    if (routingRequest !== controller) return;
    renderRoutingPreview(preview);
    status.textContent = "";
    if (test) {
      const order = node("ol");
      order.append(...test.order.map((model) => node("li", "", routedModel(model))));
      result.replaceChildren(node("strong", "", test.label), node("p", "meta", test.reason), order);
      result.hidden = false;
    }
  } catch (error) {
    if (routingRequest === controller) status.textContent = error.message;
  } finally {
    if (routingRequest === controller) routingRequest = undefined;
  }
}

function updatePoolOptions() {
  const available = Object.keys(poolModels).filter((model) =>
    !poolDraft.some((entry) => entry.provider === poolProvider.value && entry.model === model));
  poolModel.replaceChildren(new Option(available.length ? "Choose a model…" : "No models to add", ""),
    ...available.map((model) => new Option(model, model)));
  setBrainControls();
}

async function loadPoolModels() {
  poolRequest?.abort();
  poolModels = {};
  const status = byId("pool-status");
  const provider = poolProvider.value;
  const controller = poolRequest = new AbortController();
  updatePoolOptions();
  status.textContent = provider ? "Loading live chat models…" : "Connect a chat provider to add models.";
  try {
    if (provider) {
      const { tags, detail } = await api(`/api/brain/models?provider=${encodeURIComponent(provider)}`,
        undefined, controller.signal);
      if (poolRequest !== controller) return;
      poolModels = tags || {};
      status.textContent = tags && Object.keys(tags).length ? "" : detail;
    }
  } catch (error) {
    if (poolRequest === controller) status.textContent = error.message;
  } finally {
    if (poolRequest === controller) {
      poolRequest = undefined;
      updatePoolOptions();
    }
  }
}

function poolChanged() {
  poolDirty = true;
  clearBrainTest();
  previewRouting();
}

function renderPool() {
  const rows = byId("brain-pool-rows");
  rows.replaceChildren(...poolDraft.map((entry, index) => {
    const item = node("details", "pool-entry");
    item.dataset.model = `${entry.provider}:${entry.model}`;
    const provider = brainSettings.providers.find((row) => row.provider === entry.provider);
    const name = provider?.name || modelNames[entry.provider] || entry.provider;
    const status = provider?.available ? "" : " (disconnected)";
    item.append(node("summary", "", routedModel({ ...entry, name }) + status));
    const stats = brainSettings.stats[item.dataset.model];
    if (stats) {
      const latency = stats.p50_ms === null ? "" : `${stats.p50_ms.toLocaleString()} ms median · `;
      const failure = stats.last_failure === null ? "" : ` · Last failure ${date(stats.last_failure * 1000)}`;
      item.append(node("p", "meta", `${latency}${Math.round(stats.error_rate * 100)}% errors${failure}`));
    }
    const tags = node("div", "pool-tags");
    for (const [key, label, values] of [
      ["speed", "Speed", ["slow", "balanced", "fast"]],
      ["cost", "Cost tier", ["low", "medium", "high"]],
      ["tools", "Tool reliability", ["low", "medium", "high"]],
      ["context", "Context (tokens)"],
      ["multilingual", "Multilingual"],
    ]) {
      const field = node("label", key === "multilingual" ? "check-label" : "", label);
      const control = node(values ? "select" : "input");
      if (values) {
        settingOptions(control, values.map((value) => [value, value]), entry.tags[key]);
      } else if (key === "multilingual") {
        control.type = "checkbox";
        control.checked = entry.tags[key];
      } else {
        control.type = "number";
        control.min = 1;
        control.max = 10_000_000;
        control.required = true;
        control.value = entry.tags[key];
      }
      control.addEventListener("change", () => {
        if (!control.reportValidity()) return;
        entry.tags[key] = values ? control.value : key === "context" ? control.valueAsNumber : control.checked;
        poolChanged();
      });
      if (key === "multilingual") field.prepend(control);
      else field.append(control);
      tags.append(field);
    }
    const remove = button("Remove model", () => {
      poolDraft.splice(index, 1);
      renderPool();
      updatePoolOptions();
      poolProvider.focus();
      poolChanged();
    });
    remove.setAttribute("aria-label", `Remove ${entry.model}`);
    item.append(tags, remove);
    return item;
  }));
  if (!poolDraft.length) rows.append(node("p", "meta", "An empty pool uses connected provider defaults."));
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
  byId("brain-pool").hidden = brainProvider.value !== "smart";
  if (!byId("brain-pool").hidden && !poolRequest && !poolProvider.options.length) {
    const providers = brainSettings.providers.filter((entry) => entry.available && entry.supported);
    poolProvider.replaceChildren(...providers.map((entry) => new Option(entry.name, entry.provider)));
    loadPoolModels();
  }
  if (!choice) {
    detail.textContent = {
      priority: "Try connected providers in a fixed order, beginning with Muse Spark when available.",
      smart: "Rank the pool for each turn using model tags and recent performance.",
      mock: "Use Hearth’s offline demo model.",
    }[brainProvider.value];
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
  routingRequest?.abort();
  routingRequest = undefined;
  poolRequest?.abort();
  poolRequest = undefined;
  poolProvider.replaceChildren();
  byId("brain-pool").hidden = true;
  byId("routing-result").hidden = true;
  byId("routing-preview").replaceChildren();
  byId("routing-preview-status").textContent = "Loading routing preview…";
  brainSettings = undefined;
  setBrainControls();
  brainFeedback();
  byId("brain-test-result").hidden = true;
  try {
    await updateConnections("rescan");
    if (view !== "settings") return;
    brainSettings = await api("/api/brain");
    const providers = brainSettings.providers.map((entry) => {
      const suffix = !entry.available ? " (disconnected)" : !entry.supported ? " (chat unavailable)" : "";
      const option = new Option(entry.name + suffix, entry.provider);
      option.disabled = !entry.supported;
      return option;
    });
    brainProvider.replaceChildren(new Option("Auto (priority)", "priority"), new Option("Smart routing", "smart"),
      ...providers, new Option("Mock", "mock"));
    brainProvider.value = brainSettings.mode;
    poolDraft = structuredClone(brainSettings.pool.length ? brainSettings.pool : brainSettings.default_pool);
    poolDirty = false;
    renderPool();
    renderRoutingPreview(brainSettings.preview);
    byId("routing-preview-status").textContent = "";
    renderBrain(brainSettings);
    brainFeedback(brainSettings.scan_error || "");
    await loadBrainModels();
  } catch (error) {
    byId("routing-preview-status").textContent = "";
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
  routingRequest?.abort();
  routingRequest = undefined;
  byId("routing-preview-status").textContent = "";
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
      poolDraft = structuredClone(result.pool.length ? result.pool : result.default_pool);
      poolDirty = false;
      renderPool();
      updatePoolOptions();
      renderRoutingPreview(result.preview);
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

async function openView(nextView, updateHistory = true) {
  if (updateHistory && nextView === "connections" && !isConnectionsRoute()) {
    history.replaceState({ ...history.state, hearthView: view }, "");
    history.pushState(null, "", connectionHash());
  } else if (updateHistory && nextView !== "connections" && isConnectionsRoute()) {
    history.pushState({ hearthView: nextView }, "", location.pathname + location.search);
  }
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
    renderConnections();
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
for (const tab of configTabs) {
  const panel = byId(`${tab}-panel`);
  const tabButton = byId(`${tab}-tab`);
  panel.append(byId("connection-content").content.cloneNode(true));
  const controls = {
    panel, button: tabButton, badge: tabButton.querySelector(".connection-badge"),
    search: panel.querySelector("input"), filter: panel.querySelector("select"),
    count: panel.querySelector(".connection-count"), link: panel.querySelector(".connection-match-link"),
    groups: panel.querySelector(".connection-groups"),
  };
  connectionPanels.set(tab, controls);
  controls.search.addEventListener("input", renderConnections);
  controls.filter.addEventListener("change", renderConnections);
  controls.link.addEventListener("click", (event) => {
    event.preventDefault();
    const otherTab = configTabs.find((item) => item !== tab);
    const other = connectionPanels.get(otherTab);
    other.search.value = controls.search.value;
    other.filter.value = controls.filter.value;
    selectConnectionTab(otherTab);
  });
  tabButton.addEventListener("click", () => selectConnectionTab(tab));
  tabButton.addEventListener("keydown", (event) => {
    const target = {
      ArrowLeft: configTabs.find((item) => item !== tab),
      ArrowRight: configTabs.find((item) => item !== tab),
      Home: configTabs[0], End: configTabs.at(-1),
    }[event.key];
    if (!target) return;
    event.preventDefault();
    selectConnectionTab(target);
  });
}
window.addEventListener("hashchange", syncConnectionRoute);
byId("rescan-connections").addEventListener("click", () => updateConnections("rescan"));
brainProvider.addEventListener("change", async () => {
  clearBrainTest();
  await loadBrainModels();
  previewRouting();
});
brainModel.addEventListener("change", () => {
  clearBrainTest();
  setBrainControls();
  if (!brainModel.value) customModel.focus();
  previewRouting();
});
customModel.addEventListener("input", () => {
  clearBrainTest();
  setBrainControls();
});
customModel.addEventListener("change", () => previewRouting());
poolProvider.addEventListener("change", loadPoolModels);
poolModel.addEventListener("change", setBrainControls);
byId("pool-add").addEventListener("click", () => {
  const model = poolModel.value;
  const key = `${poolProvider.value}:${model}`;
  poolDraft.push({ provider: poolProvider.value, model, tags: { ...poolModels[model] } });
  renderPool();
  updatePoolOptions();
  const summary = [...byId("brain-pool-rows").children].find((item) => item.dataset.model === key);
  summary?.querySelector("summary")?.focus();
  poolChanged();
});
byId("routing-test-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const prompt = byId("routing-prompt").value.trim();
  if (prompt) previewRouting(prompt);
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
openView("chat", false);
if (isConnectionsRoute()) syncConnectionRoute();
else updateConnections("rescan");
