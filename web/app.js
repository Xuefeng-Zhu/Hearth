import { createTimeline } from "./timeline/workspace.js";
import { mountTimeline } from "./timeline/view.js";
import { createArtifacts } from "./artifacts/library.js";
import { artifactFilterFromHash } from "./artifacts/format.js";
import { mountArtifacts } from "./artifacts/view.js";
import { createReminders } from "./reminders/workspace.js";
import { mountReminders } from "./reminders/view.js";
import { slashSearchShortcut, updateText } from "./dom.js";
import { confirmControl, moveNavHighlight, transitionView } from "./motion.js";
import { setupSearchableSelects } from "./combobox.js";
import { createListSearch, listSearchHash, listSearchRoute } from "./list-search.js";
import { mountIcons } from "./icons.js";
import { setTimeZone, timeFormatter } from "./time.js";
import { createFeed } from "./home/feed.js";
import { createHome } from "./home/workspace.js";
import { mountHome } from "./home/view.js";
import { createProactivity } from "./proactivity.js";
import { createAutomation } from "./automation/workspace.js";
import { mountTasks } from "./automation/view.js";
import { createSkills, mountSkills } from "./skills/workspace.js";
import { createWorkersCard } from "./workers.js";
import { createMemory } from "./memory/workspace.js";
import { memoryLabel } from "./memory/view.js";
import { createReviewSettings } from "./memory/review.js";

import { createSettings, settingsHash, settingsRoute } from "./settings/workspace.js";
import { connectorHasError, createConnections } from "./settings/connections.js";
import { createPreferences } from "./settings/preferences.js";
import { createWorkspaceStatus, showConnectionGuidance } from "./settings/status.js";
import { mountSupportingSections } from "./settings/sections.js";
import { createBrain } from "./settings/brain.js";
import { createChatWorkspace, mainThread } from "./chat/workspace.js";

const byId = (id) => document.getElementById(id);
const settings = createSettings(openSettingsSection, { api, renderRefreshStatus });
mountSupportingSections(byId);
mountArtifacts(byId);
mountTasks(byId);
mountReminders(byId);
mountHome(byId);
mountTimeline(byId);
mountSkills(byId);
mountIcons();
setupSearchableSelects();

const notice = byId("notice");
const nav = [...document.querySelectorAll("[data-view]")];
const dateFormat = timeFormatter({ dateStyle: "medium", timeStyle: "short" });
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
const refreshStatus = new Map();
const viewRefreshPaths = { chat: "/api/state", home: "/api/home", inbox: "/api/inbox",
  reminders: "/api/reminders", timeline: "/api/timeline" };
const workspaceStatus = createWorkspaceStatus({ byId, isHome: () => view === "home", openConnections });
const connections = createConnections({
  byId, api, date, trackRefresh, refreshAPI, isActive: () => isSetting("connections"),
  onData: workspaceStatus.updateConnections,
  onUpdate() {
    if (!isSetting("voice")) return;
    voiceSettings.showEngine();
    voiceSettings.refreshCall();
  },
  loadMail: () => delivery.connections(), pollMail: () => delivery.poll(),
});
const brain = createBrain({
  byId, api, date, updateConnections: connections.update, renderBrain: workspaceStatus.updateModel,
  isBusy: () => chatWorkspace.busy, isActive: () => isSetting("brain"),
});
const preferences = createPreferences({
  byId, api, date, isActive: isSetting, openConnections, renderRecall: (...args) => memoryPage.renderRecall(...args), getThreads: () => chatWorkspace.threads,
  hasPineconeError: () => connectorHasError(connections.state?.providers.pinecone),
  loadReview: () => reviewSettings(), refreshState: (...args) => chatWorkspace.refreshState(...args),
  isBusy: () => chatWorkspace.busy, isThreadBusy: () => chatWorkspace.threadBusy,
});
const requestedThread = new URLSearchParams(location.search).get("thread");
const chatWorkspace = createChatWorkspace({
  requestedThread, byId, api, trackRefresh, readResponse, showNotice, showConnectionGuidance, date,
  currentView: () => view, currentSettings: () => settings.section,
  getConnections: () => connections.state, getConnectionRequest: () => connections.request,
  openView, refreshView, getArtifacts: () => artifactLibrary,
  onThreadsChanged: () => { if (isSetting("memory")) preferences.updateThreads(); },
  renderBrain: workspaceStatus.updateModel, schedulePoll, approvalCard: (action) => automation.approvalCard(action),
  approve, undo, gatewayResults, memoryLabel, openMemorySource, stopWorkers, openVoiceAction, openConnections,
});
const { activateThread, openArtifactThread, openDemo, openMainChat, openPanelChat, openSkillChat,
  sendPanelPrompt, mobile, voiceCall, refreshState, refreshVisibleHistory, renderChat, paintAvatars,
  voiceSettings } = chatWorkspace;
const timelineErrorRoute = "#timeline/errors";
const timeline = createTimeline({
  refreshAPI, approve, undo, gatewayResults, isBusy: () => chatWorkspace.busy,
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
    workspaceStatus.updateHome(data);
  },
});
const delivery = createReminders({
  api, refreshAPI, openView, openSettings: openSettingsSection, onInbox: automation.inbox, currentView: () => view, currentSettings: () => settings.section,
  reminderSearch: listSearches.reminders, inboxSearch: listSearches.inbox,
  startSending: () => chatWorkspace.reminderSending(true),
  stopSending: () => chatWorkspace.reminderSending(false),
});
function showNotice(message = "") {
  chatWorkspace.clearNoticeTurn();
  const target = byId("workspace-drawer").open ? byId("drawer-notice") : notice;
  target.hidden = !message;
  showConnectionGuidance(target, String(message ?? ""));
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

const reviewSettings = createReviewSettings({ api });
const memoryPage = createMemory({
  api, openSource: openMemorySource, approvals: () => openSettingsSection("approvals"),
  isBusy: () => chatWorkspace.busy, setBusy, showNotice,
});

async function openMemorySource(hit) {
  showNotice();
  if (hit.artifact_id) {
    await openView("artifacts");
    return artifactLibrary.open(hit.artifact_id);
  }
  memoryPage.selectSource(hit);
  await openView("memory");
}

async function openVoiceAction(action, payload) {
  await openView("timeline");
  if (view !== "timeline") return;
  if (action === "show_reminder" && timeline.focusReminder(payload)) return;
  const heading = byId("timeline-view").querySelector("h2");
  heading.tabIndex = -1;
  heading.focus();
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
  if (route.section === "connections" && connections.syncTab(route.target)) return;
  const focusSection = route.section && !isSetting(route.section);
  openView(route.view, false, route.section, focusSection);
}

const loadSettings = {
  connections: connections.open,
  brain: brain.open,
  memory: () => preferences.open("memory"),
  search: () => preferences.open("search"),
  voice: voiceSettings.open,
  artifacts: artifactLibrary.settings,
  home: homePage.settings,
  feed: feed.settings,
  proactivity: proactivity.settings,
  approvals: automation.settings,
  automations: automation.eventSettings,
  reminders: delivery.settings,
};

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
  else if (view === "memory") await memoryPage.load();
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
    preferences.stopPolling();
    for (const item of nav) {
      const active = item.dataset.view === view;
      if (active) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
      byId(`${item.dataset.view}-view`).hidden = !active;
    }
    if (fromDrawer) byId("view-title").focus({ preventScroll: true });
    if (previousView !== nextView && ["home", "settings", "skills"].includes(view)) byId(`${view}-view`).scrollTop = 0;
    paintAvatars();
    workspaceStatus.paint();
    if (view !== "settings") renderRefreshStatus();
  };
  const switching = transitionView(update, request > 1 && previousView !== nextView);
  if (switching) await switching;
  if (request !== viewRequest) return;
  if (view === "timeline") timeline.setTodayErrors(location.hash === timelineErrorRoute);
  if (view === "settings") {
    await settings.open(section, focusSection, loadSettings[section]);
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
window.addEventListener("hashchange", syncWorkspaceRoute);
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
      if (!chatWorkspace.busy) await connections.refreshHealth();
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
  workspaceStatus.paint();
  renderRefreshStatus();
  if (navigator.onLine) schedulePoll(true);
}
window.addEventListener("offline", updateConnectivity);
window.addEventListener("online", updateConnectivity);
setInterval(() => { if (!document.hidden) delivery.poll(); }, 60_000);
chatWorkspace.applyAppearance();
workspaceStatus.paint();
syncWorkspaceRoute();
schedulePoll();
if (!document.hidden) delivery.poll();
if (!isSetting("connections")) connections.update("rescan");
