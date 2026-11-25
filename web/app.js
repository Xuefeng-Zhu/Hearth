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
let state;
let view = "chat";
let selectedFile;
let busy = false;
let timelineTimer;
let connectionState;
let connectionRequest;
let brainSettings;
let brainBusy = false;
let modelRequest;
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
  setBrainControls();
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
  const notices = node("div");
  notices.setAttribute("role", "status");
  body.append(notices, text, cards);
  item.append(body);
  transcript.append(item);
  return { cards, notices, text };
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
  card.append(header);
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

function renderChat() {
  const actions = new Map(state.actions.map((action) => [action.id, action]));
  transcript.replaceChildren();
  byId("welcome").hidden = state.messages.length > 0;
  for (const message of state.messages) {
    const bubble = messageBubble(message.role, message.content);
    for (const notice of message.notices || []) bubble.notices.append(node("p", "model-warning", notice));
    for (const id of new Set(message.action_ids || [])) {
      if (actions.has(id)) bubble.cards.append(actionCard(actions.get(id)));
    }
  }
  scrollDown();
}

async function refreshState() {
  state = await api("/api/state", undefined, AbortSignal.timeout(6000));
  byId("environment-label").textContent = state.checkpoints === "sprite" ? "Private Sprite" : "Local workspace";
  renderBrain(state);
}

function renderBrain({ model, model_id: id }) {
  const name = modelNames[model] || "Unavailable";
  const label = id && model !== "mock" ? `${name} · ${id.split("/").at(-1)}` : name;
  const status = byId("model-status");
  status.textContent = `Brain · ${label}`;
  status.title = id && model !== "mock" ? `${name} · ${id}` : name;
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

async function refreshView() {
  await refreshState();
  if (view === "chat") renderChat();
  else if (view === "memory") await renderMemory();
  else if (view === "timeline") await renderTimeline();
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
  if (view === "connections") {
    await updateConnections("rescan");
  } else if (view === "settings") {
    await openBrainSettings();
  } else if (!busy) {
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
    await connectionRequest;
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
        if (name === "model_warning") reply.notices.append(node("p", "model-warning", payload.message));
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
    if (result.response) gatewayResults.set(action.id, result.response);
    await refreshView();
    const message = {
      sent: "Email sent.", simulated: "Simulated send recorded. Undo is available on the card.",
      unknown: "AgentMail could not confirm delivery. Check your inbox’s sent messages.",
    };
    showNotice(action.kind === "gateway"
      ? (result.status === "complete" ? "Connector request completed." : "The gateway could not confirm the request.")
      : message[result.status]);
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
updateConnections("rescan");
