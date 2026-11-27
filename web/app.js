import { artifactFilterFromHash } from "./artifacts/format.js";
import { createApprovalCards } from "./approval-cards.js";
import { memoryLabel } from "./chat/chips.js";
import { createChatSearch } from "./chat/search.js";
import { mainThread, mountThreadList } from "./chat/threads.js";
import { slashSearchShortcut, updateText } from "./dom.js";
import { confirmControl, moveNavHighlight, showLoading, transitionView } from "./motion.js";
import { setupMobile } from "./mobile.js";
import { setupSearchableSelects } from "./combobox.js";
import { createListSearch, listSearchHash, listSearchRoute } from "./list-search.js";
import { mountIcons } from "./icons.js";
import { setTimeZone, timeFormatter } from "./time.js";
import { createFeed } from "./home/feed.js";
import { createHome } from "./home/workspace.js";
import { mountHome } from "./home/view.js";
import { createWorkspaceStatus, showConnectionGuidance, connectorHasError } from "./settings/status.js";
import { settingsHash, settingsRoute } from "./settings/routes.js";
import { createSSEParser } from "./sse.js";
import { createStore } from "./store.js";
import { createWorkersCard } from "./workers.js";

const byId = (id) => document.getElementById(id);
mountHome(byId);
mountIcons();
setupSearchableSelects();

const notice = byId("notice");
const loadingStatus = byId("view-loading");
const nav = [...document.querySelectorAll("[data-view]")];
const dateFormat = timeFormatter({ dateStyle: "medium", timeStyle: "short" });
const gatewayResults = new Map();
const requestedThread = new URLSearchParams(location.search).get("thread");
let homeCache, homeSequence = 0, homeActive = false;
let view = "home", viewRequest = 0, loadingView = false;
let chatWorkspace, settings, timeline, artifactLibrary, skills, inbox, memoryPage, automation;
let connections, brain, preferences, connectionState, connectionRequest;
let voiceSettings;
let busy = false;
const store = createStore({
  currentThread: requestedThread || sessionStorage.getItem("hearth-thread") || mainThread.id,
  threads: [mainThread], threadEntries: [mainThread], busy: false,
});
const listSearchViews = new Set(["reminders", "inbox", "skills"]);
const listSearches = {};
function mountListSearch(name) {
  listSearches[name] = createListSearch(name, (query) => {
    const hash = listSearchHash(name, query, listSearchRoute(location.hash)?.target);
    if (hash !== location.hash) history.pushState(history.state, "", hash);
    void refreshView();
  });
  return listSearches[name];
}
const refreshStatus = new Map();
const viewRefreshPaths = { chat: "/api/state", home: "/api/home", inbox: "/api/inbox",
  reminders: "/api/reminders", timeline: "/api/timeline" };
const workspaceStatus = createWorkspaceStatus({ byId, isHome: () => view === "home", openConnections });

const mobile = setupMobile({
  nearBottom: () => chatWorkspace?.nearBottom(), scrollDown: () => chatWorkspace?.scrollDown(),
  refreshThreads: refreshDrawerThreads, closeThreadMenu: (options) => chatWorkspace?.closeThreadMenu(options),
});
const chatSearch = createChatSearch({
  api, thread: () => store.state.currentThread,
  jump: (...args) => chatWorkspace.openChatSearchResult(...args),
  reveal: (...args) => chatWorkspace.revealChatSearchResult(...args),
  prepareFind: () => chatWorkspace?.prepareFind(),
});
mountThreadList({
  store, list: byId("threads"), menuId: "thread-menu",
  onSelect: (id) => withChat((chat) => chat.openThreadFromList(id)),
  openMenu: (thread, trigger, options) => withChat((chat) => chat.openThreadMenu(thread, trigger, options)),
});
byId("new-thread").addEventListener("click", () => withChat((chat) => chat.newThread()));

function withChat(action) {
  if (chatWorkspace) return action(chatWorkspace);
  return loadChat().then(action, (error) => showNotice(error.message));
}

const openPanelChat = (...args) => withChat((chat) => chat.openPanelChat(...args));
const openSkillChat = (...args) => withChat((chat) => chat.openSkillChat(...args));
const openArtifactThread = (...args) => withChat((chat) => chat.openArtifactThread(...args));
const openDemo = (...args) => withChat((chat) => chat.openDemo(...args));
const openMainChat = () => withChat((chat) => chat.openMainChat());
const sendPanelPrompt = async (prompt) => (await loadChat()).sendPanelPrompt(prompt);

function openThread(thread) {
  return openView("chat", true, undefined, false, () => chatWorkspace.activateThread(thread));
}

const timelineErrorRoute = "#timeline/errors";
const approvalCards = createApprovalCards({
  api, refresh: refreshView, openThread, undo,
  onDecision: (id, result) => automation?.onDecision(id, result),
  eventData: () => automation?.eventData,
});

const pending = new Map();
const loaded = new Map();
function once(name, initialize) {
  if (loaded.has(name)) return Promise.resolve(loaded.get(name));
  if (!pending.has(name)) {
    pending.set(name, initialize().then((instance) => {
      loaded.set(name, instance);
      return instance;
    }).finally(() => pending.delete(name)));
  }
  return pending.get(name);
}

let chatModule, chatPrefetchScheduled = false;
function importChat() {
  chatModule ??= import("./chat/workspace.js").catch((error) => {
    chatModule = undefined;
    throw error;
  });
  return chatModule;
}

function prefetchChat() {
  if (chatModule || chatPrefetchScheduled) return;
  chatPrefetchScheduled = true;
  requestAnimationFrame(() => {
    const prefetch = () => {
      chatPrefetchScheduled = false;
      if (view === "home") void importChat().catch(() => {});
    };
    if (typeof window.requestIdleCallback === "function") window.requestIdleCallback(prefetch);
    else window.setTimeout(prefetch, 0);
  });
}

function loadChat() {
  return once("chat", async () => {
    const [{ createChatWorkspace }, persona, { createVoiceInput }, { createVoiceCall }] = await Promise.all([
      importChat(), import("./settings/persona.js"), import("./voice.js"), import("./voice-call.js"),
    ]);
    chatWorkspace = createChatWorkspace({
      store, byId, api, trackRefresh, readResponse, showNotice, showConnectionGuidance, date,
      mobile, chatSearch, persona, createVoiceInput, createVoiceCall, createSSEParser,
      currentView: () => view,
      getConnectionRequest: () => connections?.request || connectionRequest,
      whisperConnected, updateVoiceSettings,
      openView, refreshView, artifacts: {
        chatActions: (...args) => artifactContent("chatActions", args),
        attachmentCards: (...args) => artifactContent("attachmentCards", args),
        openAttachment: async (...args) => (await loadView("artifacts")).openAttachment(...args),
        openBrowse: async (...args) => (await loadView("artifacts")).openBrowse(...args),
        endBrowse: (...args) => artifactLibrary?.endBrowse(...args),
      },
      onThreadsChanged: () => { if (isSetting("memory")) preferences?.updateThreads(); },
      renderBrain: workspaceStatus.updateModel, schedulePoll, approvalCard: approvalCards.approvalCard,
      approve, undo, gatewayResults, memoryLabel, openMemorySource, stopWorkers, openVoiceAction,
    });
    chatWorkspace.applyAppearance();
    return chatWorkspace;
  });
}

function artifactContent(method, args) {
  if (artifactLibrary) return artifactLibrary[method](...args);
  const placeholder = document.createElement("span");
  placeholder.hidden = true;
  loadView("artifacts").then((library) => {
    placeholder.replaceWith(library[method](...args));
  }).catch((error) => showNotice(error.message));
  return placeholder;
}

function loadDelivery() {
  return once("delivery", async () => {
    const { createReminders } = await import("./reminders/workspace.js");
    return createReminders({
      api, refreshAPI, openView, openSettings: openSettingsSection,
      currentView: () => view, currentSettings: () => settings?.section,
      startSending: () => chatWorkspace?.reminderSending(true),
      stopSending: () => chatWorkspace?.reminderSending(false),
    });
  });
}

function loadAutomation() {
  return once("automation", async () => {
    const { createAutomation } = await import("./automation/workspace.js");
    automation = createAutomation({
      api, refreshAPI, refresh: refreshView, undo, openInbox: () => openView("inbox"), approvals: approvalCards,
    });
    return automation;
  });
}

function loadTasks() {
  return once("tasks", async () => {
    const [{ mountTasks }, controller] = await Promise.all([import("./automation/view.js"), loadAutomation()]);
    mountTasks(byId);
    controller.mountTasks();
    return controller;
  });
}

async function openTask(id) {
  const tasks = await loadTasks();
  if (view === "reminders") return tasks.openTask(id);
}

function mountReminderTabs() {
  let choice = 0;
  for (const name of ["reminders", "tasks"]) {
    const tab = byId(`${name}-tab`);
    async function choose(target, focus = false) {
      const request = ++choice;
      if (target === "reminders" && !loaded.has("tasks")) {
        if (focus) byId("reminders-tab").focus();
        return;
      }
      try {
        const tasks = await loadTasks();
        if (view === "reminders" && request === choice) await tasks.chooseTab(target, focus);
      } catch (error) {
        showNotice(error.message);
      }
    }
    tab.addEventListener("click", () => choose(name));
    tab.addEventListener("keydown", (event) => {
      const target = { ArrowLeft: name === "tasks" ? "reminders" : "tasks",
        ArrowRight: name === "tasks" ? "reminders" : "tasks", Home: "reminders", End: "tasks" }[event.key];
      if (!target) return;
      event.preventDefault();
      choose(target, true);
    });
  }
}

const loadWorkspace = {
  async timeline() {
    const [{ createTimeline }, { mountTimeline }] = await Promise.all([
      import("./timeline/workspace.js"), import("./timeline/view.js"),
    ]);
    mountTimeline(byId);
    timeline = createTimeline({
      refreshAPI, approve, undo, gatewayResults, isBusy: () => busy || chatWorkspace?.busy,
      onFilter() {
        if (location.hash === timelineErrorRoute) {
          history.replaceState({ hearthView: "timeline" }, "", location.pathname + location.search);
        }
      },
    });
    mountIcons(byId("timeline-view"));
    return timeline;
  },
  async artifacts() {
    const [{ createArtifacts }, { mountArtifacts }] = await Promise.all([
      import("./artifacts/library.js"), import("./artifacts/view.js"),
    ]);
    mountArtifacts(byId);
    artifactLibrary = createArtifacts({
      api, showNotice, openThread: openArtifactThread,
      refreshChat: async () => { if (view === "chat") await refreshView(); },
      onFilter: selectArtifactFilter,
    });
    mountIcons();
    return artifactLibrary;
  },
  async reminders() {
    const [{ mountReminders }, delivery] = await Promise.all([import("./reminders/view.js"), loadDelivery()]);
    mountReminders(byId);
    mountListSearch("reminders");
    delivery.mountList(listSearches.reminders);
    mountReminderTabs();
    mountIcons(byId("reminders-view"));
    return delivery;
  },
  async inbox() {
    const { createInbox, mountInbox } = await import("./inbox/workspace.js");
    mountInbox();
    inbox = createInbox({
      api, refreshAPI, search: mountListSearch("inbox"), currentView: () => view, checkMail,
      pendingPoll: () => mailPoll,
      onInbox: approvalCards.inbox,
    });
    mountIcons(byId("inbox-view"));
    return inbox;
  },
  async memory() {
    const { createMemory } = await import("./memory/workspace.js");
    memoryPage = createMemory({
      api, openSource: openMemorySource, approvals: () => openSettingsSection("approvals"),
      isBusy: () => busy || chatWorkspace?.busy, setBusy, showNotice,
    });
    return memoryPage;
  },
  async skills() {
    const { createSkills, mountSkills } = await import("./skills/workspace.js");
    mountSkills(byId);
    skills = createSkills({
      api, openChat: openSkillChat, search: mountListSearch("skills"),
      onLinkedClose(id) {
        const route = listSearchRoute(location.hash);
        if (route?.view === "skills" && route.target === id) {
          history.replaceState(history.state, "", listSearchHash("skills", route.query));
        }
      },
    });
    mountIcons();
    return skills;
  },
  async settings() {
    const [{ createSettings }, { mountSupportingSections }] = await Promise.all([
      import("./settings/workspace.js"), import("./settings/sections.js"),
    ]);
    settings = createSettings(openSettingsSection, { api, renderRefreshStatus });
    mountSupportingSections(byId);
    mountIcons(byId("settings-view"));
    return settings;
  },
};

function loadView(name) {
  return name === "chat" ? loadChat() : once(name, loadWorkspace[name]);
}

function updateConnectionState(data) {
  connectionState = data;
  workspaceStatus.updateConnections(data);
}

function updateConnections(operation, data) {
  if (connections) return connections.update(operation, data);
  if (connectionRequest) return connectionRequest;
  connectionRequest = trackRefresh("/api/connections", false, () => api("/api/connections/rescan", {}))
    .catch(() => connectionState || refreshAPI("/api/connections").catch(() => undefined))
    .then((result) => {
      if (result) updateConnectionState(result);
      return result;
    }).finally(() => { connectionRequest = undefined; });
  return connectionRequest;
}

function loadConnections() {
  return once("connections", async () => {
    const { createConnections } = await import("./settings/connections.js");
    connections = createConnections({
      byId, api, date, trackRefresh, refreshAPI, isActive: () => isSetting("connections"),
      onData: updateConnectionState,
      onUpdate() { updateVoiceSettings({ refreshCall: true }); },
      loadMail: loadEmailConnection, pollMail,
      initialState: connectionState, initialRequest: connectionRequest,
    });
    return connections;
  });
}

function loadPreferences() {
  return once("preferences", async () => {
    const { createPreferences } = await import("./settings/preferences.js");
    preferences = createPreferences({
      byId, api, date, isActive: isSetting, openConnections,
      renderRecall: async (...args) => (await loadView("memory")).renderRecall(...args),
      getThreads: () => store.state.threads,
      hasPineconeError: () => connectorHasError(connectionState?.providers.pinecone),
      loadReview: async () => {
        const review = await once("review-settings", async () => {
          const { createReviewSettings } = await import("./memory/review.js");
          return createReviewSettings({ api });
        });
        return review();
      },
      refreshState: (...args) => chatWorkspace ? chatWorkspace.refreshState(...args) : refreshDrawerThreads(),
      isBusy: () => busy || chatWorkspace?.busy, isThreadBusy: () => chatWorkspace?.threadBusy,
    });
    return preferences;
  });
}

const loadSettings = {
  async connections() {
    const controller = await loadConnections();
    if (isSetting("connections")) {
      controller.syncTab(settingsRoute(location.hash)?.target);
      return controller.open();
    }
  },
  async brain() {
    brain = await once("brain", async () => {
      const { createBrain } = await import("./settings/brain.js");
      return createBrain({
        byId, api, date, updateConnections, renderBrain: workspaceStatus.updateModel,
        isBusy: () => busy || chatWorkspace?.busy, isActive: () => isSetting("brain"),
      });
    });
    workspaceStatus.paintModel();
    if (isSetting("brain")) return brain.open();
  },
  memory: async () => (await loadPreferences()).open("memory"),
  search: async () => (await loadPreferences()).open("search"),
  appearance: async () => (await loadChat()).showAppearance(),
  async voice() {
    const { createVoiceSettings, readVoiceSettings } = await import("./settings/persona.js");
    if (!isSetting("voice")) return;
    if (!voiceSettings) {
      store.update(readVoiceSettings());
      voiceSettings = createVoiceSettings({ store, byId, api, date, openConnections, whisperConnected });
    }
    return voiceSettings.open();
  },
  artifacts: async () => (await loadView("artifacts")).settings(),
  home: () => homePage.settings(),
  feed: () => feed.settings(),
  async proactivity() {
    const controller = await once("proactivity", async () => {
      const { createProactivity } = await import("./proactivity.js");
      return createProactivity({ api });
    });
    return controller.settings();
  },
  approvals: async () => (await loadAutomation()).settings(),
  automations: async () => (await loadAutomation()).eventSettings(),
  reminders: async () => (await loadDelivery()).settings(),
};

function whisperConnected() {
  const connection = connectionState?.providers?.huggingface?.status;
  return connection === "connected" || (connection == null && chatWorkspace?.snapshot?.whisper_available === true);
}

function updateVoiceSettings({ refreshCall = false } = {}) {
  if (!voiceSettings || !isSetting("voice")) return;
  voiceSettings.showEngine();
  if (refreshCall) voiceSettings.refreshCall();
}

async function loadEmailConnection() {
  const { loadEmailConnection: load } = await import("./reminders/delivery.js");
  if (isSetting("connections")) return load(api);
}

let mailPoll;
async function checkMail(manual) {
  const result = await api("/api/inbox/poll", manual ? { force: true } : {});
  if (view === "inbox") await inbox?.load({ background: !manual });
  if (isSetting("connections")) await loadEmailConnection();
  if (isSetting("reminders")) await (await loadDelivery()).refreshEmailStatus();
  return result;
}

function pollMail() {
  if (mailPoll || inbox?.manualPending) return;
  mailPoll = checkMail(false).catch(() => {}).finally(() => { mailPoll = undefined; });
}

let drawerRequest;
function refreshDrawerThreads() {
  if (chatWorkspace) return chatWorkspace.refreshDrawerThreads();
  if (drawerRequest) return drawerRequest;
  drawerRequest = loadDrawerThreads().catch((error) => {
    if (byId("workspace-drawer").open) showNotice(error.message);
  }).finally(() => { drawerRequest = undefined; });
  return drawerRequest;
}

async function loadDrawerThreads() {
  const thread = store.state.currentThread;
  const state = await api(`/api/state?thread=${encodeURIComponent(thread)}`, undefined, AbortSignal.timeout(6000));
  const entries = new Map(state.threads.map((item) => [item.id, item]));
  let offset = state.next_thread_offset;
  while (!chatWorkspace && offset != null) {
    const page = await api(`/api/threads?offset=${offset}`, undefined, AbortSignal.timeout(6000));
    if (page.thread_revision !== state.thread_revision) return;
    for (const item of page.threads) if (!entries.has(item.id)) entries.set(item.id, item);
    offset = page.next_thread_offset;
  }
  if (chatWorkspace || thread !== store.state.currentThread) return;
  const threads = [...entries.values()].map((item) => {
    const activity = state.thread_activity[item.id];
    return { ...item, busy: !!activity, activity };
  });
  let seen;
  try {
    seen = new Map(JSON.parse(localStorage.getItem("hearth-seen-replies") || "[]"));
  } catch {
    seen = new Map();
  }
  const threadEntries = threads.map((item) => {
    if (!seen.has(item.id)) seen.set(item.id, item.last_reply);
    const status = state.reminder_sending?.includes(item.id) ? "Sending reminder"
      : item.busy ? "Working" : item.last_reply && seen.get(item.id) !== item.last_reply ? "Unread reply" : "";
    return { ...item, status };
  });
  localStorage.setItem("hearth-seen-replies", JSON.stringify([...seen]));
  updateText(byId("thread-list-status"), threadEntries.filter((item) => item.status)
    .map((item) => `${item.title}: ${item.status}`).join(". "));
  store.update({ threads, threadEntries });
  setTimeZone(state.timezone);
  workspaceStatus.updateModel(state);
  if (isSetting("memory")) preferences?.updateThreads();
}

const homeWorkers = createWorkersCard({
  heading: "Running now", stop: stopWorkers,
  openThread: async (thread) => {
    await openThread(thread);
  },
});
const feed = createFeed({
  api, approvalCard: approvalCards.approvalCard, refreshHome: loadHome,
  runSuggestion: async (id) => (await loadChat()).send("", { keepDraft: true, suggestion: id }),
  openReview: async (id) => {
    await openView("memory", true, undefined, false, () => memoryPage.selectReview(id));
  },
  openSettings: () => openSettingsSection("feed"),
  async openChat(thread, draft) {
    await withChat(async (chat) => {
      await chat.openSkillChat(thread);
      chat.fillDraft(draft);
    });
  },
  async openSource(source) {
    const id = source.ref;
    if (source.kind === "memory") return openMemorySource({ path: id, line: 1 });
    if (source.kind === "chat") return openArtifactThread(...id.split("/"));
    if (["page", "artifact"].includes(source.kind)) {
      if (await openView("artifacts") === false) return;
      return artifactLibrary.open(id);
    }
    const next = source.kind === "inbox" ? "inbox" : "reminders";
    await openView(next);
    if (source.kind === "task") return openTask(id);
    if (source.kind === "reminder" && automation?.tasksActive()) await automation.openReminders();
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
  feed, approvalCard: approvalCards.approvalCard,
  openFile: async (file, trigger) => (await loadView("artifacts")).open(file.id, trigger, file),
  onData(data) {
    setTimeZone(data.timezone);
    if (feed.root.isConnected) feed.show();
    approvalCards.home(data.approvals || []);
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
function showNotice(message = "") {
  chatWorkspace?.clearNoticeTurn();
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
  if (view === "reminders" && automation?.tasksActive()) path = "/api/tasks";
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
  busy = value;
  if (chatWorkspace) chatWorkspace.setBusy(value);
  else store.update({ busy: value });
  for (const item of document.querySelectorAll(".cards button, [data-prompt]")) {
    item.disabled = value;
  }
  timeline?.setBusy();
  brain?.updateControls();
  schedulePoll();
}

async function stopWorkers(turnId, id) {
  await api("/api/workers/stop", { turn_id: turnId, ...(id ? { id } : {}) });
  await refreshView();
}

async function openMemorySource(hit) {
  showNotice();
  if (hit.artifact_id) {
    if (await openView("artifacts") === false) return;
    return artifactLibrary.open(hit.artifact_id);
  }
  await openView("memory", true, undefined, false, () => memoryPage.selectSource(hit));
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
  return view === "settings" && settings?.section === section;
}

function workspaceRoute() {
  const hash = location.hash;
  const route = settingsRoute(hash) || listSearchRoute(hash);
  if (route) return route;
  const filter = artifactFilterFromHash(hash);
  if (filter) return { view: "artifacts", hash: artifactHash(filter) };
  if (hash === timelineErrorRoute) return { view: "timeline", hash };
  if (!history.state?.hearthView) {
    if (location.pathname === "/automations") return settingsRoute("#settings/automations");
    if (location.pathname === "/voice") return settingsRoute("#settings/voice");
  }
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
    const previous = history.state?.hearthView || location.pathname.slice(1);
    openView(nav.some((item) => item.dataset.view === previous) ? previous : requestedThread ? "chat" : "home", false);
    return;
  }
  if (location.hash !== route.hash) history.replaceState(history.state, "", route.hash);
  if (route.view === "artifacts" && view === "artifacts" && artifactLibrary) {
    artifactLibrary.selectFormat(artifactFilterFromHash(route.hash));
    return;
  }
  if (route.section === "connections" && connections?.syncTab(route.target)) return;
  const focusSection = route.section && !isSetting(route.section);
  openView(route.view, false, route.section, focusSection);
}

async function loadHome(options) {
  await homePage.load(options);
  if (view === "home" && byId("home-loading").hidden) prefetchChat();
}

async function refreshView(options) {
  if (loadingView) return;
  renderRefreshStatus();
  if (view === "home") return loadHome(options);
  if (view === "timeline") return timeline.show(options);
  if (view === "artifacts") return artifactLibrary.show();
  if (view === "skills") return skills.load();
  if (view === "reminders") return automation?.tasksActive() ? automation.loadTasks(options) : loaded.get("delivery").reminders(options);
  if (view === "inbox") return inbox.load(options);
  if (isSetting("automations")) return automation?.eventSettings(options);
  if (view === "memory") {
    if (chatWorkspace) await chatWorkspace.refreshState();
    return memoryPage.load();
  }
  if (view === "chat" && await chatWorkspace.refreshState()) {
    chatWorkspace.renderChat();
    await chatWorkspace.refreshVisibleHistory();
  }
}

async function openView(nextView, updateHistory = true, section, focusSection = false, prepare) {
  const request = ++viewRequest;
  const previousView = view;
  const loading = nextView !== "home" && !loaded.has(nextView)
    ? Promise.resolve(loadView(nextView)).then(() => null, (error) => error) : null;
  const fromDrawer = mobile.closeDrawer({ restoreFocus: false });
  if (nextView !== previousView) chatWorkspace?.closeThreadMenu({ restoreFocus: false });
  if (nextView !== previousView) listSearches[previousView]?.cancel();
  if (previousView === "home" && nextView !== "home") homePage.closeAdd({ restoreFocus: false });
  if (nextView !== previousView) showNotice();
  if (nextView !== "chat") {
    chatSearch.close({ restoreFocus: false });
    chatWorkspace?.cancelVoice();
  }
  if (updateHistory) {
    const route = listSearchRoute(location.hash);
    const hash = nextView === "settings" ? settingsHash(section) : nextView === "artifacts" ? artifactHash()
      : listSearchViews.has(nextView) ? listSearchHash(nextView, route?.view === nextView ? route.query : "") : "";
    const sameArtifactsView = nextView === "artifacts" && workspaceRoute()?.view === "artifacts";
    if (hash !== location.hash && !sameArtifactsView) {
      history.pushState({ hearthView: nextView }, "", hash || location.pathname + location.search);
    }
  }
  history.replaceState({ ...history.state, hearthView: nextView }, "");
  if (view === "timeline" && nextView !== view) timeline?.hide();
  if (nextView !== "skills") skills?.clearLink();
  const searchRoute = listSearchRoute(location.hash);
  const update = () => {
    if (request !== viewRequest) return;
    if (previousView !== nextView) moveNavHighlight(nav, nextView);
    view = nextView;
    loadingView = !!loading;
    loadingStatus.hidden = !loading;
    const title = view[0].toUpperCase() + view.slice(1);
    if (loading) showLoading(loadingStatus, `Loading ${title}…`);
    schedulePoll();
    byId("start-call").hidden = view !== "chat" || loadingView;
    byId("view-title").textContent = title;
    preferences?.stopPolling();
    for (const item of nav) {
      const active = item.dataset.view === view;
      if (active) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
      byId(`${item.dataset.view}-view`).hidden = !active || loadingView;
    }
    if (fromDrawer) byId("view-title").focus({ preventScroll: true });
    if (previousView !== nextView && ["home", "settings", "skills"].includes(view)) byId(`${view}-view`).scrollTop = 0;
    chatWorkspace?.paintAvatars();
    workspaceStatus.paint();
    if (view !== "settings") renderRefreshStatus();
  };
  const switching = transitionView(update, request > 1 && previousView !== nextView);
  if (switching) await switching;
  if (request !== viewRequest) return false;
  if (loading) {
    const error = await loading;
    if (request !== viewRequest) return false;
    loadingView = false;
    loadingStatus.hidden = true;
    if (error) {
      showNotice(error.message);
      return false;
    }
    byId(`${view}-view`).hidden = false;
    byId("start-call").hidden = view !== "chat";
  }
  prepare?.();
  listSearches[view]?.sync(searchRoute?.view === view ? searchRoute.query : "");
  if (view === "timeline") timeline.setTodayErrors(location.hash === timelineErrorRoute);
  if (view === "settings") {
    try {
      await settings.open(section, focusSection, loadSettings[section]);
    } catch (error) {
      if (request === viewRequest) showNotice(error.message);
    }
  } else if (view === "home") {
    await loadHome();
    if (previousView !== "home" && feed.root.isConnected) feed.show(true);
  } else if (view === "skills") {
    await skills.loadLinked(searchRoute?.target);
  } else if (view === "artifacts") {
    artifactLibrary.selectFormat(artifactFilterFromHash(location.hash) || "all");
    await artifactLibrary.show();
  } else if (view === "reminders" || view === "inbox") {
    if (view === "reminders" && !updateHistory && searchRoute?.query && automation?.tasksActive()) {
      await automation.openReminders();
    } else await refreshView();
    if (view === "inbox") pollMail();
  } else if (!busy && !chatWorkspace?.busy) {
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
  if (busy || chatWorkspace?.busy) return;
  setBusy(true);
  showNotice();
  const threadId = action.thread_id || mainThread.id;
  chatWorkspace?.signalAvatar(threadId, { type: "approval_started", title: action.title });
  try {
    const result = await api("/api/approve", { id: action.id });
    if (result.response) gatewayResults.set(action.id, result.response);
    chatWorkspace?.signalAvatar(threadId, { type: "approval_done", success: ["complete", "sent", "simulated"].includes(result.status) });
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
    chatWorkspace?.signalAvatar(threadId, { type: "approval_done", success: false });
    showNotice(error.message);
  } finally {
    setBusy(false);
  }
}

async function undo(action, { confirmed = false, timelineTitle, redo = false } = {}) {
  if (action.job || action.inbox_id || action.undo_task || action.undo_automation || action.automation_id) {
    if (busy || chatWorkspace?.busy) return;
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
    if (busy || chatWorkspace?.busy || (!confirmed && !window.confirm("Undo this memory change?"))) return;
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
    if (busy || chatWorkspace?.busy || (["skill", "goal"].includes(action.kind) && !confirmed && !window.confirm(`Undo this ${action.kind} change?`))) return;
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
    if (busy || chatWorkspace?.busy) return;
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
  if (busy || chatWorkspace?.busy || (!confirmed && !window.confirm(`Restore checkpoint ${action.checkpoint.id}? This rolls back the workspace, including newer chat, memory, and reminders. Delivered email stays delivered.`))) return;
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
        if (!await (await loadChat()).refreshState(action.id)) continue;
      } catch {
        continue;
      }
      if (chatWorkspace.snapshot.restore?.action_id === action.id && chatWorkspace.snapshot.restore.status === "failed") {
        throw new Error("The checkpoint could not be restored.");
      }
      if (!chatWorkspace.snapshot.actions.some((item) => item.id === action.id && item.checkpoint?.id === action.checkpoint.id)) {
        timeline?.restored(action, timelineTitle);
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
  const canSearch = view === "chat" && !!chatWorkspace && !document.querySelector("dialog[open]:not(#chat-search-dialog)");
  if (chatWorkspace?.voiceCall.open || chatSearch.shortcut(event, canSearch)) return;
  if (listSearches[view] && slashSearchShortcut(event) && !document.querySelector("dialog[open]")
      && listSearches[view].focus()) {
    event.preventDefault();
    return;
  }
  chatWorkspace?.composerShortcut(event);
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
    chatWorkspace?.cancelVoice({ releaseKey: true });
    if (view === "timeline") timeline?.hide();
  }
  if (!document.hidden) pollMail();
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
  const active = busy || chatWorkspace?.busy || chatWorkspace?.threadBusy || chatWorkspace?.hasPendingTurns ||
    (view === "home" ? homeActive : view === "chat" ? chatWorkspace?.snapshot?.active_work : true);
  const delay = immediate && !loadingView ? 0 : active ? 3000 : 12000;
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
      if (!busy && !chatWorkspace?.busy) await connections?.refreshHealth();
    } else if (!loadingView && view === "chat" && !chatWorkspace.threadBusy) {
      const previous = chatWorkspace.snapshot;
      if (await chatWorkspace.refreshState(undefined, { background: true }) && view === "chat") {
        if (previous !== chatWorkspace.snapshot) chatWorkspace.renderChat();
        await chatWorkspace.refreshVisibleHistory();
      }
    } else if (!chatWorkspace?.threadBusy && (view === "home" || (!busy && !chatWorkspace?.busy && (["reminders", "inbox"].includes(view) ||
        isSetting("automations") || (immediate && view === "timeline"))))) {
      await refreshView({ background: true });
    }
    if (drawer && view !== "chat" && !chatWorkspace?.threadBusy) await refreshDrawerThreads();
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
setInterval(() => { if (!document.hidden) pollMail(); }, 60_000);
workspaceStatus.paint();
syncWorkspaceRoute();
schedulePoll();
if (!document.hidden) pollMail();
if (settingsRoute(location.hash)?.section !== "connections") updateConnections("rescan");
