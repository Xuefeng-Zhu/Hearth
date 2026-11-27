import { createTimeline } from "./timeline.js";
import { artifactFilterFromHash, createArtifacts } from "./artifacts.js";
import { createReminders } from "./reminders.js";
import { button, node, slashSearchShortcut, updateText } from "./dom.js";
import { confirmControl, moveNavHighlight, showLoading, transitionView } from "./motion.js";
import { setupSearchableSelects } from "./combobox.js";
import { createListSearch, listSearchHash, listSearchRoute } from "./list-search.js";
import { icon, mountIcons } from "./icons.js";
import { setTimeZone, timeFormatter } from "./time.js";
import { createFeed } from "./feed.js";
import { createHome } from "./home.js";
import { createProactivity } from "./proactivity.js";
import { createAutomation } from "./automation.js";
import { createSkills } from "./skills.js";
import { createWorkersCard } from "./workers.js";
import { createMemory } from "./memory.js";
import { createMemoryReview } from "./memory-review.js";
import { githubSettings } from "./self-update.js";

import { configTabs, connectionHash, createSettings, settingsHash, settingsRoute } from "./settings/workspace.js";
import { createBrain, modelNames } from "./settings/brain.js";
import { createChatWorkspace, mainThread } from "./chat/workspace.js";

const settings = createSettings(openSettingsSection, { api, renderRefreshStatus });
mountIcons();
setupSearchableSelects();

const byId = (id) => document.getElementById(id);
const notice = byId("notice");
const nav = [...document.querySelectorAll("[data-view]")];
const connectionsLabel = "Settings → Connections";
const dateFormat = timeFormatter({ dateStyle: "medium", timeStyle: "short" });
const connectorSettings = {
  pinecone: { field: "index", label: "Index name", placeholder: "hearth-memory", maxLength: 45 },
  agentmail: { field: "inbox_id", label: "Inbox ID", placeholder: "your-inbox@agentmail.to", maxLength: 254 },
};
const connectionTabStorage = "hearth-connections-tab";
const connectionPanels = new Map();
const connectionDrafts = new Map();
const gatewayResults = new Map();
let homeCache;
let homeSequence = 0;
let homeActive = false;
let view = "home";
let viewRequest = 0;
const listSearches = Object.fromEntries(["reminders", "inbox", "skills"].map((name) =>
  [name, createListSearch(name, (query) => {
    const hash = listSearchHash(name, query, listSearchRoute(location.hash)?.target);
    if (hash !== location.hash) history.pushState(history.state, "", hash);
    void refreshView();
  })]));
let memoryFindRequest = 0;
let connectionState;
let workspaceModel;
let workspaceConnectorError = false;
let homeConnectorError = false;
const workspaceStatusLabels = document.querySelectorAll("[data-workspace-status]");
const refreshStatus = new Map();
const viewRefreshPaths = { chat: "/api/state", home: "/api/home", inbox: "/api/inbox",
  reminders: "/api/reminders", timeline: "/api/timeline" };
let connectionRequest;
let connectionTabPreference = localStorage.getItem(connectionTabStorage);
let newlyConfigured = new Set();
let reindexPoll;
const preferences = { memory: {}, search: {} };
const brain = createBrain({
  byId, api, date, updateConnections, renderBrain,
  isBusy: () => chatWorkspace.busy, isActive: () => isSetting("brain"),
});
const requestedThread = new URLSearchParams(location.search).get("thread");
const chatWorkspace = createChatWorkspace({
  requestedThread, byId, api, trackRefresh, readResponse, showNotice, showConnectionGuidance, date,
  currentView: () => view, currentSettings: () => settings.section,
  getConnections: () => connectionState, getConnectionRequest: () => connectionRequest,
  openView, refreshView, getArtifacts: () => artifactLibrary,
  onThreadsChanged: () => { if (isSetting("memory")) renderMemoryThreadOptions(); },
  renderBrain, schedulePoll, approvalCard: (action) => automation.approvalCard(action),
  approve, undo, gatewayResults, memoryLabel, openMemorySource, stopWorkers, openVoiceAction, openConnections,
});
const { activateThread, openArtifactThread, openDemo, openMainChat, openPanelChat, openSkillChat,
  sendPanelPrompt, mobile, voiceCall, refreshState, refreshVisibleHistory, renderChat, paintAvatars,
  showVoiceEngine, syncVoiceSettings } = chatWorkspace;
const timelineErrorRoute = "#timeline/errors";
const timeline = createTimeline({
  api, refreshAPI, approve, undo, gatewayResults, isBusy: () => chatWorkspace.busy,
  onFilter() {
    if (location.hash === timelineErrorRoute) {
      history.replaceState({ hearthView: "timeline" }, "", location.pathname + location.search);
    }
  },
});
const artifactLibrary = createArtifacts({
  api, showNotice, openThread: openArtifactThread,
  refreshChat: async () => { if (view === "chat") await refreshView(); },
  onFilter: selectArtifactFilter,
});
const automation = createAutomation({
  api, refreshAPI, refresh: refreshView, undo, openInbox: () => openView("inbox"), openThread: async (thread) => {
    activateThread(thread);
    await openView("chat");
  },
});
const skills = createSkills({
  api, openChat: openSkillChat, search: listSearches.skills,
  onLinkedClose(id) {
    const route = listSearchRoute(location.hash);
    if (route?.view === "skills" && route.target === id) {
      history.replaceState(history.state, "", listSearchHash("skills", route.query));
    }
  },
});
const homeWorkers = createWorkersCard({
  heading: "Running now", stop: stopWorkers,
  openThread: async (thread) => {
    activateThread(thread);
    await openView("chat");
  },
});
const proactivity = createProactivity({ api });
const feed = createFeed({
  api, approvalCard: automation.approvalCard, refreshHome: () => homePage.load(), runSuggestion: (id) => chatWorkspace.send("", { keepDraft: true, suggestion: id }),
  openReview: async (id) => {
    memoryPage.selectReview(id);
    await openView("memory");
  },
  openSettings: () => openSettingsSection("feed"),
  async openChat(thread, draft) {
    await openSkillChat(thread);
    chatWorkspace.fillDraft(draft);
  },
  async openSource(source) {
    const id = source.ref;
    if (source.kind === "memory") return openMemorySource({ path: id, line: 1 });
    if (source.kind === "chat") return openArtifactThread(...id.split("/"));
    if (["page", "artifact"].includes(source.kind)) {
      await openView("artifacts");
      return artifactLibrary.open(id);
    }
    const next = source.kind === "inbox" ? "inbox" : "reminders";
    await openView(next);
    if (source.kind === "task") return automation.openTask(id);
    if (source.kind === "reminder" && automation.tasksActive()) await automation.openReminders();
    if (source.kind === "reminder" || source.kind === "inbox") {
      const attribute = source.kind === "reminder" ? "data-reminder" : "data-inbox";
      const card = document.querySelector(`[${attribute}="${CSS.escape(id)}"]`);
      if (card) {
        card.tabIndex = -1;
        card.focus();
      }
    }
  },
});
const homePage = createHome({
  api, refreshAPI, openView, openWeatherSettings, openConnections, openPanelChat, openDemo, sendPanelPrompt, openMainChat,
  feed, approvalCard: automation.approvalCard,
  openFile: (file, trigger) => artifactLibrary.open(file.id, trigger, file),
  onData(data) {
    setTimeZone(data.timezone);
    if (feed.root.isConnected) feed.show();
    automation.home(data.approvals || []);
    const workers = data.workers || [];
    homeActive = data.active_work;
    schedulePoll();
    const target = byId("home-workers");
    homeWorkers.update(workers);
    if (!homeWorkers.card.isConnected) target.append(homeWorkers.card);
    target.hidden = !workers.length;
    const connections = data.builtin.connections;
    homeConnectorError = !!connections.error || connections.items.some((entry) => entry.status === "error");
    renderBrain(data);
  },
});
const delivery = createReminders({
  api, refreshAPI, openView, openSettings: openSettingsSection, onInbox: automation.inbox, currentView: () => view, currentSettings: () => settings.section,
  reminderSearch: listSearches.reminders, inboxSearch: listSearches.inbox,
  startSending: () => chatWorkspace.reminderSending(true),
  stopSending: () => chatWorkspace.reminderSending(false),
});
const memoryNames = { auto: "Auto", pinecone: "Pinecone", local: "Local", keyword: "Local", huggingface: "Local · Hugging Face embeddings" };
const folderNames = { root: "Profile and approvals", people: "people/", locations: "locations/",
  topics: "Topic notes", projects: "projects/", daily: "daily/" };
function showNotice(message = "") {
  chatWorkspace.clearNoticeTurn();
  const target = byId("workspace-drawer").open ? byId("drawer-notice") : notice;
  target.hidden = !message;
  showConnectionGuidance(target, String(message ?? ""));
}

function showConnectionGuidance(target, message) {
  const start = message.indexOf(connectionsLabel);
  if (start === -1) {
    target.textContent = message;
    return;
  }
  const link = node("a", "connection-guidance", connectionsLabel);
  link.href = connectionHash();
  target.replaceChildren(message.slice(0, start), link, message.slice(start + connectionsLabel.length));
}

async function api(path, data, signal) {
  if (path === "/api/home" && data === undefined) {
    const sequence = ++homeSequence;
    const cached = homeCache;
    const response = await fetch(path, { signal, headers: cached?.tag ? { "If-None-Match": cached.tag } : {} });
    if (response.status === 304) return cached.data;
    const snapshot = await readResponse(response);
    if (sequence === homeSequence) homeCache = { data: snapshot, tag: response.headers.get("ETag") };
    return snapshot;
  }
  const options = data === undefined ? { signal } : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data), signal,
  };
  return readResponse(await fetch(path, options));
}

async function readResponse(response) {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || "Hearth is temporarily unavailable.");
  }
  return response.json();
}

function refreshAPI(path, { background, signal } = {}) {
  return trackRefresh(path.split("?")[0], background, () => api(path, undefined, signal));
}

async function trackRefresh(path, background, load) {
  if (!refreshStatus.has(path)) refreshStatus.set(path, { attempt: 0, failures: 0 });
  const status = refreshStatus.get(path);
  const attempt = ++status.attempt;
  try {
    const data = await load();
    if (attempt === status.attempt && status.failures) {
      status.failures = 0;
      renderRefreshStatus();
    }
    return data;
  } catch (error) {
    if (background && attempt === status.attempt && error.name !== "AbortError") {
      status.failures = Math.min(status.failures + 1, 2);
      status.disconnected = error instanceof TypeError || error.name === "TimeoutError";
      renderRefreshStatus();
    }
    throw error;
  }
}

function renderRefreshStatus() {
  let path = viewRefreshPaths[view];
  if (view === "reminders" && automation.tasksActive()) path = "/api/tasks";
  if (isSetting("connections")) path = "/api/connections";
  if (isSetting("automations")) path = "/api/event-automations";
  const status = refreshStatus.get(path);
  const label = status?.failures === 2
    ? `Stale · ${status.disconnected ? (navigator.onLine ? "Disconnected" : "Offline") : "Server error"}` : "";
  updateText(byId("refresh-status"), label);
}

function date(value) {
  return value && Number.isFinite(Date.parse(value)) ? dateFormat.format(new Date(value)) : "";
}

function setBusy(value) {
  chatWorkspace.setBusy(value);
  for (const item of document.querySelectorAll(".cards button, [data-prompt]")) {
    item.disabled = value;
  }
  timeline.setBusy();
  brain.updateControls();
  schedulePoll();
}

async function stopWorkers(turnId, id) {
  await api("/api/workers/stop", { turn_id: turnId, ...(id ? { id } : {}) });
  await refreshView();
}

function renderBrain({ model, model_id: id }) {
  workspaceModel = model;
  const name = modelNames[model] || connectionState?.providers[model]?.name || model || "Unavailable";
  byId("brain-active-model").textContent = id && model !== "mock" ? `${name} · ${id}` : name;
  renderWorkspaceStatus();
}

function renderWorkspaceStatus() {
  const connectorError = workspaceConnectorError || (view === "home" && homeConnectorError);
  const showWarning = navigator.onLine && connectorError;
  const status = !navigator.onLine ? "Offline" : !showWarning && workspaceModel === "mock" ? "Mock mode" : "";
  for (const label of workspaceStatusLabels) {
    const container = label.parentElement;
    updateText(label, status);
    label.hidden = !status;
    container.querySelector("[data-connection-warning]").hidden = !showWarning;
    container.hidden = !status && !showWarning;
  }
}

function connectorHasError(entry) {
  return entry?.uses.length > 0 && (entry.status === "unauthorized" || ["failed", "denied"].includes(entry.test_status)
    || entry.index_state === "Unavailable");
}

function applyConnections(data) {
  connectionState = data;
  workspaceConnectorError = !!data.scan_error || Object.values(data.providers).some(connectorHasError);
  renderConnections();
  renderBrain(data);
}

async function refreshPineconeHealth() {
  const previous = connectionState;
  const entry = previous?.providers.pinecone;
  if (connectionRequest || entry?.status !== "connected" ||
      (entry.index_state === "Ready" && !connectorHasError(entry))) return;
  const data = await refreshAPI("/api/connections", { background: true, signal: AbortSignal.timeout(6000) });
  if (isSetting("connections") && !connectionRequest && connectionState === previous &&
      JSON.stringify(data.providers.pinecone) !== JSON.stringify(entry)) {
    applyConnections(data);
  }
}

function memoryLabel(hit) {
  if (hit.artifact_id) return hit.heading || "Artifact";
  return `${hit.message_id ? hit.heading : hit.path} · line ${hit.line}`;
}

const memoryReview = createMemoryReview({ api });
const memoryPage = createMemory({
  api,
  forget: (hit) => forgetMemory(hit),
  approvals: () => openSettingsSection("approvals"),
  renderReview: memoryReview.render,
});

async function renderMemory() {
  await memoryPage.load();
}

async function openMemorySource(hit) {
  showNotice();
  if (hit.artifact_id) {
    await openView("artifacts");
    return artifactLibrary.open(hit.artifact_id);
  }
  memoryPage.selectSource(hit);
  await openView("memory");
}

async function forgetMemory(hit, excerpt = false) {
  const question = hit.message_id ? "Forget this message from recall?" : excerpt
    ? `Remove this excerpt from ${hit.path}?` : `Delete the note ${hit.path}?`;
  if (chatWorkspace.busy || !window.confirm(`${question} Hearth will save a checkpoint first.`)) return;
  setBusy(true);
  try {
    const body = { path: hit.path };
    if (hit.message_id) body.message_id = hit.message_id;
    else if (excerpt) body.item_id = hit.id;
    else if (hit.revision) body.revision = hit.revision;
    await api("/api/memory/forget", body);
    memoryPage.clearSource();
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
    const score = hit.backend === "pinecone"
      ? `Score ${hit.score.toFixed(3)} · ${result.reranked ? "Reranked" : "Cosine similarity"}`
      : hit.similarity === null ? `Keyword ${hit.keyword.toFixed(3)}`
        : `Score ${hit.score.toFixed(3)} · Similarity ${hit.similarity.toFixed(3)} · Keyword ${hit.keyword.toFixed(3)}`;
    article.append(open, node("p", "meta", score), node("p", "", hit.excerpt));
    if (allowForget && !hit.artifact_id && !hit.profile_fields && hit.path !== "APPROVAL_PREFERENCES.md") {
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
  container.replaceChildren(showLoading(node("p", "meta"), "Searching memory…"));
  try {
    const result = await api("/api/memory/search", { query });
    if (request === memoryFindRequest) renderRecall(container, result, true);
  } catch (error) {
    if (request === memoryFindRequest) container.replaceChildren(node("p", "meta", error.message));
  }
}

async function openVoiceAction(action, payload) {
  await openView("timeline");
  if (view !== "timeline") return;
  if (action === "show_reminder" && timeline.focusReminder(payload)) return;
  const heading = byId("timeline-view").querySelector("h2");
  heading.tabIndex = -1;
  heading.focus();
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
  const used = entry.uses.length > 0;
  const check = connectorHasError(entry) ? "error"
    : entry.index_state === "Ready" ? "ready" : entry.index_state === "Connecting" ? "checking"
      : entry.test_status === "passed" ? "ok" : entry.test_status ? "error" : "untested";
  const status = used ? (configured ? check : entry.status) : "not_used";
  const labels = {
    ok: "OK", ready: "Ready", checking: "Checking", error: "Error", untested: "Untested", unauthorized: "Found but not authorized",
    not_set_up: "Not set up", unknown: "Not checked", not_used: "Not used by Hearth",
  };
  const heading = node("div", "card-header");
  const tone = status === "ready" ? "ok" : status === "checking" ? "untested" : status;
  heading.append(node("h4", "", entry.name), node("span", `connection-status ${tone}`, labels[status]));
  card.append(heading);
  if (entry.auth) card.append(node("p", "meta", entry.auth));
  card.append(node("p", "connection-description", entry.description));
  if (configured && used) {
    const uses = node("p", "connection-uses");
    uses.append(node("strong", "", "Used for"), ` ${entry.uses.join(" · ")}`);
    card.append(uses);
  }
  if (Object.hasOwn(connectorSettings, provider)) card.append(connectorForm(provider, entry, connectorSettings[provider]));
  if (provider === "github" && connectionState.self_update) {
    card.append(githubSettings(connectionState.self_update, async (settings) => {
      applyConnections(await api("/api/self-update/settings", settings));
      byId("connection-notice").textContent = "GitHub settings saved.";
      document.querySelector('[data-provider="github"] input')?.focus();
    }));
  }
  if (entry.index_error) card.append(node("p", "connection-test failed", entry.index_error));
  else if (entry.test_detail) card.append(node("p", used ? `connection-test ${entry.test_status}` : "meta", entry.test_detail));

  const footer = node("div", "connector-footer");
  const access = node("span", "connector-access", entry.access_rule);
  const links = node("div", "connector-links");
  const flyLabel = configured ? "Open in Fly" : entry.status === "unauthorized" ? "Review in Fly" : "Add in Fly";
  for (const [label, url] of [[flyLabel, entry.dashboard_url], ["Docs", entry.docs_url]]) {
    const link = externalLink(label, url);
    if (url) link.append(" ", icon("external", 14));
    links.append(link);
  }
  footer.append(access, links);
  if (entry.can_test) {
    const test = button("Test", async () => {
      await updateConnections("test", { provider });
      if (isSetting("connections") && document.activeElement === document.body) byId(test.id)?.focus();
    });
    test.id = `test-connection-${provider}`;
    test.setAttribute("aria-label", `Test ${entry.name}`);
    if (!entry.test_path) test.title = "Check gateway authorization.";
    links.append(test);
  }
  card.append(footer);
  return card;
}

function isSetting(section) {
  return view === "settings" && settings.section === section;
}

function workspaceRoute() {
  const hash = location.hash;
  const route = settingsRoute(hash) || listSearchRoute(hash);
  if (route) return route;
  const filter = artifactFilterFromHash(hash);
  if (filter) return { view: "artifacts", hash: artifactHash(filter) };
  if (hash === timelineErrorRoute) return { view: "timeline", hash };
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

function artifactHash(filter = "all") {
  return filter === "all" ? "#artifacts" : `#artifacts/${filter}`;
}

function selectArtifactFilter(filter) {
  if (location.hash !== artifactHash(filter)) history.pushState(history.state, "", artifactHash(filter));
  artifactLibrary.selectFormat(filter);
}

function syncWorkspaceRoute() {
  const route = workspaceRoute();
  if (!route) {
    const previous = history.state?.hearthView;
    openView(nav.some((item) => item.dataset.view === previous) ? previous : requestedThread ? "chat" : "home", false);
    return;
  }
  if (location.hash !== route.hash) history.replaceState(history.state, "", route.hash);
  if (route.view === "artifacts" && view === "artifacts") {
    artifactLibrary.selectFormat(artifactFilterFromHash(route.hash));
    return;
  }
  if (route.section === "connections") {
    if (route.target) rememberConnectionTab(route.target);
    if (isSetting("connections")) {
      renderConnections();
      return;
    }
  }
  const focusSection = route.section && !isSetting(route.section);
  openView(route.view, false, route.section, focusSection);
}

function renderConnections() {
  const entries = Object.entries(connectionState?.providers ?? {});
  const configured = entries.filter(([, entry]) => entry.status === "connected");
  const unconfigured = entries.filter(([, entry]) => entry.status !== "connected");
  const providersByTab = { configured, "not-configured": unconfigured };
  const defaultTab = configured.length ? "configured" : "not-configured";
  const activeConnectionTab = configTabs.includes(connectionTabPreference) ? connectionTabPreference : defaultTab;
  if (isSetting("connections") && location.hash === connectionHash()
      && (connectionState || connectionTabPreference === activeConnectionTab)) {
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
  const unused = [];
  for (const [provider, entry] of entries) {
    const card = connectionCard(provider, entry);
    if (!entry.uses.length) {
      unused.push(card);
      continue;
    }
    const group = entry.pinned ? "Hearth essentials" : entry.category;
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(card);
  }
  if (unused.length) groups.set("Available, not used", unused);
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
  for (const control of byId("settings-connections").querySelectorAll(".connection-grid button, .connection-grid input")) {
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
      const data = await trackRefresh("/api/connections", false, () => api(`/api/connections/${operation}`, body));
      if (operation === "rescan" && previous && !data.scan_error) {
        announceNewConnections(previous, data);
      }
      if (operation === "settings") connectionDrafts.delete(body.provider);
      applyConnections(data);
      if (view === "settings" && settings.section === "voice") {
        showVoiceEngine();
        voiceCall.refreshSettings();
      }
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
          applyConnections(await refreshAPI("/api/connections"));
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

function settingOptions(select, options, selected) {
  select.replaceChildren(...options.map(([value, label, disabled]) => {
    const option = new Option(label, value);
    option.disabled = !!disabled && value !== selected;
    return option;
  }));
  select.value = selected;
}

function renderMemoryThreadOptions() {
  const select = byId("memory-test-thread");
  settingOptions(select, [["", "All threads"], ...chatWorkspace.threads.map(({ id, title }) => [id, title])], select.value);
}

function renderMemoryPreferences(info) {
  const choice = info.selection;
  const stores = choice.backend === "huggingface" ? ["auto", "pinecone", "local", "huggingface"]
    : ["auto", "pinecone", "local"];
  settingOptions(byId("memory-backend"), stores.map((value) => [value, memoryNames[value]]),
    choice.backend === "keyword" ? "local" : choice.backend);
  settingOptions(byId("memory-model"), Object.entries(info.models), choice.model);
  settingOptions(byId("memory-test-kind"), [["", "All kinds"], ...info.kinds.map((kind) =>
    [kind, kind[0].toUpperCase() + kind.slice(1)])], byId("memory-test-kind").value);
  renderMemoryThreadOptions();
  byId("memory-top-k").value = choice.top_k;
  byId("memory-similarity").value = choice.min_similarity;
  byId("memory-chat-history").checked = choice.include_chat;
  byId("memory-summarize-chats").checked = choice.summarize_long_chats;
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
      const target = node("label", "scope-choice");
      target.append(check);
      row.append(target);
    }
    return row;
  }));
  updateMemoryJobs(info);
}

function renderSearchPreferences(info) {
  const choice = info.selection;
  const browsing = byId("allow-browsing");
  browsing.checked = info.browsing.allowed;
  browsing.disabled = false;
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
      : button("Connect in Connections", openConnections));
    return row;
  }));
}

byId("allow-browsing").addEventListener("change", async (event) => {
  const input = event.currentTarget;
  const feedback = byId("browsing-feedback");
  const allowed = input.checked;
  input.disabled = true;
  feedback.textContent = "Saving…";
  try {
    const result = await api("/api/browse/settings", { allowed });
    if (preferences.search.info) preferences.search.info.browsing = result;
    input.checked = result.allowed;
    feedback.textContent = result.allowed ? "Web browsing is on." : "Web browsing is off.";
  } catch (error) {
    input.checked = !allowed;
    feedback.textContent = error.message;
  } finally {
    input.disabled = false;
  }
});

function updatePreferenceControls(feature) {
  const { info, pending, indexing } = preferences[feature];
  byId(`${feature}-fields`).disabled = !info || !!pending || !!indexing;
  const test = byId(`${feature}-test-form`).querySelector("button");
  test.disabled = !info || !!pending || !!indexing;
  if (!info) return;
  if (feature === "memory") {
    const backend = byId("memory-backend").value;
    byId("memory-backend-detail").textContent = {
      auto: "Try Pinecone first. Use Local if it’s unavailable or slow.",
      local: "Search the workspace’s notes and saved artifacts offline.",
      huggingface: "Rank local excerpts with Hugging Face embeddings.",
      pinecone: "Search the Pinecone index with Local fallback.",
    }[backend];
    byId("memory-model-field").hidden = backend !== "huggingface";
    byId("memory-similarity").disabled = backend === "local";
    byId("memory-sync").disabled = !!pending || !!preferences.memory.syncing || !info.available.pinecone;
    byId("memory-reindex").disabled = !!pending || !!indexing || !!preferences.memory.syncing;
  } else {
    const provider = byId("search-provider").value;
    const connected = info.providers.filter((entry) => entry.connected);
    const active = provider === "auto" ? connected[0] : connected.find((entry) => entry.provider === provider);
    test.disabled ||= !active;
    byId("search-safe-detail").hidden = !byId("search-safe").checked || !active || active.native_safe;
    byId("search-provider-detail").textContent = provider === "off" ? "Web search is off."
      : active ? provider === "auto" ? `Auto starts with ${active.name}.` : `${active.name} is connected.`
        : "No selected provider is connected. Open Settings → Connections.";
  }
}

function updateMemoryJobs({ pinecone, sync, reindex }) {
  clearTimeout(reindexPoll);
  const status = byId("memory-index-status");
  const progress = byId("memory-index-progress");
  const job = pinecone.connected ? sync : reindex;
  preferences.memory.syncing = sync?.status === "running";
  preferences.memory.indexing = reindex?.status === "running";
  const running = job?.status === "running";
  const details = byId("pinecone-index-details");
  const mode = pinecone.integrated && !pinecone.vector_transport ? "integrated" : "dense";
  const synced = pinecone.last_sync ? date(pinecone.last_sync) : "Pending";
  details.replaceChildren(...[
    ["Index", pinecone.name],
    ["Namespace", pinecone.namespace],
    ["Model", pinecone.embedding_model ? `${pinecone.embedding_model} · ${mode}` : undefined],
    ["Dimension", pinecone.dimension],
    ["Records", pinecone.record_count?.toLocaleString()],
    ["Last sync", synced],
  ].flatMap(([label, value]) => [node("dt", "", label), node("dd", "", value ?? "—")]));

  progress.hidden = !running;
  if (running && (job.work || job.unique)) {
    progress.max = job.work || job.unique;
    progress.value = job.work ? job.upserted + job.deleted : job.embedded + job.reused;
  } else {
    progress.removeAttribute("value");
  }
  if (running) {
    status.textContent = job.phase === "checkpoint" ? "Saving checkpoint…"
      : job.phase === "connecting" ? "Checking the Pinecone connection…"
        : job.work ? `Syncing · ${job.upserted + job.deleted} of ${job.work} changes` : "Checking saved excerpts…";
  } else if (job?.status === "failed") {
    status.textContent = job.error;
  } else if (job && pinecone.connected) {
    status.textContent = `${job.upserted} upserted · ${job.deleted} deleted · ${job.unchanged} unchanged`;
  } else if (job) {
    status.textContent = `Local index · ${job.total} excerpts · ${job.embedded} embedded`;
  } else {
    status.textContent = pinecone.connected ? "Ready to sync memories." : "Pinecone is disconnected.";
  }
  byId("memory-connect").hidden = pinecone.connected && !connectorHasError(connectionState?.providers.pinecone);

  updatePreferenceControls("memory");
  if (running && view === "settings" && settings.section === "memory") {
    reindexPoll = setTimeout(async () => {
      try {
        updateMemoryJobs(await api("/api/memory/reindex"));
      } catch (error) {
        status.textContent = error.message;
        preferences.memory.indexing = false;
        preferences.memory.syncing = false;
        updatePreferenceControls("memory");
      }
    }, 500);
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
    include_chat: byId("memory-chat-history").checked, summarize_long_chats: byId("memory-summarize-chats").checked,
    auto_remember: byId("memory-remember").value,
    include: scope("include"), exclude: scope("exclude") };
}

async function loadSettings(section) {
  if (section === "connections") {
    renderConnections();
    const mailCard = delivery.connections();
    await updateConnections("rescan");
    await mailCard;
    if (isSetting("connections")) delivery.poll();
    return;
  }
  if (section === "brain") return brain.open();
  if (section === "appearance") return;
  if (section === "artifacts") return artifactLibrary.settings();
  if (section === "home") return homePage.settings();
  if (section === "feed") return feed.settings();
  if (section === "proactivity") return proactivity.settings();
  if (section === "approvals") return automation.settings();
  if (section === "automations") return automation.eventSettings();
  if (section === "watchers") return;
  if (section === "reminders") return delivery.settings();
  if (section === "voice") {
    syncVoiceSettings();
    return voiceCall.syncSettings();
  }
  if (preferences[section].pending) return;
  if (section === "memory") {
    memoryReview.settings();
    if (!chatWorkspace.busy && !chatWorkspace.threadBusy) {
      refreshState(undefined, { background: true }).catch(() => {
        // The recall form can still search across all threads.
      });
    }
  }
  try {
    const info = await api(`/api/${section}/settings`);
    if (view !== "settings" || settings.section !== section || preferences[section].pending) return;
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
  if (!state.info || state.pending || state.indexing || chatWorkspace.busy) return;
  const indexAction = operation === "reindex" || operation === "sync";
  if (!indexAction && !form.reportValidity()) return;
  const selection = readPreferences(feature);
  const filters = {};
  if (feature === "memory" && operation === "test") {
    const kind = byId("memory-test-kind").value;
    const thread = byId("memory-test-thread").value;
    if (kind) filters.kind = kind;
    if (thread) filters.thread_id = thread;
  }
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
    const result = await api(`/api/${feature}/${operation}`, operation === "test" ? { selection, query, ...filters }
      : indexAction ? {} : selection);
    if (indexAction) {
      updateMemoryJobs(await api("/api/memory/reindex"));
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

async function refreshView(options) {
  renderRefreshStatus();
  if (view === "home") return homePage.load(options);
  if (view === "timeline") return timeline.show(options);
  if (view === "artifacts") return artifactLibrary.show();
  if (view === "skills") return skills.load();
  if (view === "reminders") return automation.tasksActive() ? automation.loadTasks(options) : delivery.reminders(options);
  if (view === "inbox") return delivery.inbox(options);
  if (isSetting("automations")) return automation.eventSettings(options);
  if (!await refreshState()) return;
  if (view === "chat") {
    renderChat();
    await refreshVisibleHistory();
  }
  else if (view === "memory") await renderMemory();
}

async function openView(nextView, updateHistory = true, section, focusSection = false) {
  const request = ++viewRequest;
  const previousView = view;
  const fromDrawer = mobile.closeDrawer({ restoreFocus: false });
  if (nextView !== previousView) chatWorkspace.closeThreadMenu({ restoreFocus: false });
  if (nextView !== previousView) listSearches[previousView]?.cancel();
  if (previousView === "home" && nextView !== "home") homePage.closeAdd({ restoreFocus: false });
  if (nextView !== previousView) showNotice();
  if (nextView !== "chat") {
    chatWorkspace.closeSearch({ restoreFocus: false });
    chatWorkspace.cancelVoice();
  }
  if (updateHistory) {
    const route = listSearchRoute(location.hash);
    const hash = nextView === "settings" ? settingsHash(section) : nextView === "artifacts" ? artifactHash()
      : listSearches[nextView] ? listSearchHash(nextView, route?.view === nextView ? route.query : "") : "";
    const sameArtifactsView = nextView === "artifacts" && workspaceRoute()?.view === "artifacts";
    if (hash !== location.hash && !sameArtifactsView) {
      history.pushState({ hearthView: nextView }, "", hash || location.pathname + location.search);
    }
  }
  history.replaceState({ ...history.state, hearthView: nextView }, "");
  if (view === "timeline" && nextView !== view) timeline.hide();
  if (nextView !== "skills") skills.clearLink();
  const searchRoute = listSearchRoute(location.hash);
  const update = () => {
    if (request !== viewRequest) return;
    if (previousView !== nextView) moveNavHighlight(nav, nextView);
    view = nextView;
    listSearches[view]?.sync(searchRoute?.view === view ? searchRoute.query : "");
    schedulePoll();
    byId("start-call").hidden = view !== "chat";
    byId("view-title").textContent = view[0].toUpperCase() + view.slice(1);
    clearTimeout(reindexPoll);
    for (const item of nav) {
      const active = item.dataset.view === view;
      if (active) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
      byId(`${item.dataset.view}-view`).hidden = !active;
    }
    if (fromDrawer) byId("view-title").focus({ preventScroll: true });
    if (previousView !== nextView && ["home", "settings", "skills"].includes(view)) byId(`${view}-view`).scrollTop = 0;
    paintAvatars();
    renderWorkspaceStatus();
    if (view !== "settings") renderRefreshStatus();
  };
  const switching = transitionView(update, request > 1 && previousView !== nextView);
  if (switching) await switching;
  if (request !== viewRequest) return;
  if (view === "timeline") timeline.setTodayErrors(location.hash === timelineErrorRoute);
  if (view === "settings") {
    await settings.open(section, focusSection, loadSettings);
  } else if (view === "home") {
    await homePage.load();
    if (previousView !== "home" && feed.root.isConnected) feed.show(true);
  } else if (view === "skills") {
    await skills.loadLinked(searchRoute?.target);
  } else if (view === "artifacts") {
    artifactLibrary.selectFormat(artifactFilterFromHash(location.hash) || "all");
    await artifactLibrary.show();
  } else if (view === "reminders" || view === "inbox") {
    if (view === "reminders" && !updateHistory && searchRoute?.query && automation.tasksActive()) {
      await automation.openReminders();
    } else await refreshView();
    if (view === "inbox") delivery.poll();
  } else if (!chatWorkspace.busy) {
    try {
      await refreshView();
    } catch (error) {
      showNotice(error.message);
    }
  }
}

function openSettingsSection(section) {
  return openView("settings", true, section);
}

function openWeatherSettings() {
  return openSettingsSection("home");
}

function openConnections() {
  return openView("settings", true, "connections", true);
}

async function approve(action) {
  if (chatWorkspace.busy) return;
  setBusy(true);
  showNotice();
  const threadId = action.thread_id || mainThread.id;
  chatWorkspace.signalAvatar(threadId, { type: "approval_started", title: action.title });
  try {
    const result = await api("/api/approve", { id: action.id });
    if (result.response) gatewayResults.set(action.id, result.response);
    chatWorkspace.signalAvatar(threadId, { type: "approval_done", success: ["complete", "sent", "simulated"].includes(result.status) });
    await refreshView();
    const message = {
      sent: "Email sent.", simulated: "Simulated send recorded. Undo is available on the card.",
      unknown: "AgentMail could not confirm delivery. Check your inbox’s sent messages.",
    };
    if (action.kind === "panel") showNotice("Panels added to Home.");
    else if (action.kind === "remember") showNotice("Fact remembered.");
    else if (action.kind === "gateway") showNotice(result.status === "complete"
      ? "Connector request completed." : "The gateway could not confirm the request.");
    else showNotice(message[result.status]);
  } catch (error) {
    chatWorkspace.signalAvatar(threadId, { type: "approval_done", success: false });
    showNotice(error.message);
  } finally {
    setBusy(false);
  }
}

async function undo(action, { confirmed = false, timelineTitle, redo = false } = {}) {
  if (action.job || action.inbox_id || action.undo_task || action.undo_automation || action.automation_id) {
    if (chatWorkspace.busy) return;
    setBusy(true);
    try {
      await api(action.inbox_id ? "/api/inbox/undo" : "/api/undo", { id: action.inbox_id || action.id });
      await refreshView();
      showNotice(action.inbox_id ? "Email acceptance undone." : action.undo_task ? "Task restored."
        : action.undo_automation ? "Automation restored." : action.automation_id ? "Run changes undone." : "Reminder canceled.");
    } catch (error) {
      showNotice(error.message);
    } finally {
      setBusy(false);
    }
    return;
  }
  if (action.memory_change) {
    if (chatWorkspace.busy || (!confirmed && !window.confirm("Undo this memory change?"))) return;
    setBusy(true);
    try {
      await api(redo ? "/api/redo" : "/api/undo", { id: action.id });
      await refreshView();
      showNotice(redo ? "Memory change redone." : "Memory change undone.");
    } catch (error) {
      showNotice(error.message);
    } finally {
      setBusy(false);
    }
    return;
  }
  if (["page", "skill", "goal"].includes(action.kind)) {
    if (chatWorkspace.busy || (["skill", "goal"].includes(action.kind) && !confirmed && !window.confirm(`Undo this ${action.kind} change?`))) return;
    setBusy(true);
    try {
      await api("/api/undo", { id: action.id });
      await refreshView();
      showNotice({ skill: "Skill change undone.", goal: "Goal change undone.", page: "Page change undone." }[action.kind]);
    } catch (error) {
      showNotice(error.message);
    } finally {
      setBusy(false);
    }
    return;
  }
  if (action.artifact_id) {
    if (chatWorkspace.busy) return;
    setBusy(true);
    try {
      await api("/api/artifacts/undo", { id: action.id });
      await refreshView();
      showNotice("Artifact change undone.");
    } catch (error) {
      showNotice(error.message);
    } finally {
      setBusy(false);
    }
    return;
  }
  if (chatWorkspace.busy || (!confirmed && !window.confirm(`Restore checkpoint ${action.checkpoint.id}? This rolls back the workspace, including newer chat, memory, and reminders. Delivered email stays delivered.`))) return;
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
        if (!await refreshState(action.id)) continue;
      } catch {
        continue;
      }
      if (chatWorkspace.snapshot.restore?.action_id === action.id && chatWorkspace.snapshot.restore.status === "failed") {
        throw new Error("The checkpoint could not be restored.");
      }
      if (!chatWorkspace.snapshot.actions.some((item) => item.id === action.id && item.checkpoint?.id === action.checkpoint.id)) {
        timeline.restored(action, timelineTitle);
        await refreshView();
        showNotice("Workspace restored.");
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

document.addEventListener("keydown", (event) => {
  if (voiceCall.open || chatWorkspace.searchShortcut(event)) return;
  if (listSearches[view] && slashSearchShortcut(event) && !document.querySelector("dialog[open]")
      && listSearches[view].focus()) {
    event.preventDefault();
    return;
  }
  chatWorkspace.composerShortcut(event);
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
window.addEventListener("hashchange", syncWorkspaceRoute);
byId("rescan-connections").addEventListener("click", () => updateConnections("rescan"));
byId("memory-find").addEventListener("submit", (event) => {
  event.preventDefault();
  findMemory();
});
byId("memory-query").addEventListener("input", (event) => {
  if (!event.target.value) findMemory();
});
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
byId("memory-sync").addEventListener("click", () => changePreferences("memory", "sync"));
byId("memory-reindex").addEventListener("click", () => {
  const connected = preferences.memory.info?.available.pinecone;
  const question = connected ? "Rebuild the Pinecone index for this profile from saved memories?"
    : "Rebuild the local index from saved memories?";
  if (window.confirm(question)) changePreferences("memory", "reindex");
});
for (const link of document.querySelectorAll("[data-connection-warning]")) {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    openConnections();
  });
}
for (const item of nav) {
  item.addEventListener("click", () => openView(item.dataset.view));
}
document.addEventListener("change", (event) => {
  if (event.target.matches('input[type="checkbox"], input[type="radio"]')) confirmControl(event.target);
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    chatWorkspace.cancelVoice({ releaseKey: true });
    if (view === "timeline") timeline.hide();
  }
  if (!document.hidden) delivery.poll();
  schedulePoll(true);
});
let polling = false, pollTimer, pollDelay, resumePoll = false;
function schedulePoll(immediate = false) {
  if (document.hidden) {
    clearTimeout(pollTimer);
    pollTimer = undefined;
    resumePoll = false;
    return;
  }
  if (polling) {
    resumePoll ||= immediate;
    return;
  }
  const active = chatWorkspace.busy || chatWorkspace.threadBusy || chatWorkspace.hasPendingTurns ||
    (view === "home" ? homeActive : view === "chat" ? chatWorkspace.snapshot?.active_work : true);
  const delay = immediate ? 0 : active ? 3000 : 12000;
  if (pollTimer !== undefined && pollDelay <= delay) return;
  clearTimeout(pollTimer);
  pollDelay = delay;
  pollTimer = setTimeout(() => pollForeground(immediate), delay);
}

async function pollForeground(immediate) {
  pollTimer = undefined;
  if (document.hidden) return;
  polling = true;
  try {
    const drawer = byId("workspace-drawer").open;
    if (isSetting("connections")) {
      if (!chatWorkspace.busy) await refreshPineconeHealth();
    } else if (view === "chat" && !chatWorkspace.threadBusy) {
      const previous = chatWorkspace.snapshot;
      if (await refreshState(undefined, { background: true }) && view === "chat") {
        if (previous !== chatWorkspace.snapshot) renderChat();
        await refreshVisibleHistory();
      }
    } else if (!chatWorkspace.threadBusy && (view === "home" || (!chatWorkspace.busy && (["reminders", "inbox"].includes(view) ||
        isSetting("automations") || (immediate && view === "timeline"))))) {
      await refreshView({ background: true });
    }
    if (drawer && view !== "chat" && !chatWorkspace.threadBusy) await refreshState();
  } catch {
    // Refresh status is reported next to the affected view title.
  } finally {
    polling = false;
    const again = resumePoll;
    resumePoll = false;
    schedulePoll(again);
  }
}

window.addEventListener("focus", () => schedulePoll(true));
function updateConnectivity() {
  renderWorkspaceStatus();
  renderRefreshStatus();
  if (navigator.onLine) schedulePoll(true);
}
window.addEventListener("offline", updateConnectivity);
window.addEventListener("online", updateConnectivity);
setInterval(() => { if (!document.hidden) delivery.poll(); }, 60_000);
chatWorkspace.applyAppearance();
renderWorkspaceStatus();
syncWorkspaceRoute();
schedulePoll();
if (!document.hidden) delivery.poll();
if (!isSetting("connections")) updateConnections("rescan");
