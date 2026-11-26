import { avatarEvent, avatarPose, newAvatar } from "./avatar-state.js";
import { announcePose, looks, mascot, poseLabel, setLook, setPose } from "./avatar.js";
import { createVoiceInput } from "./voice.js";
import { callDuration, captionLine, createVoiceCall } from "./voice-call.js";
import { createTimeline } from "./timeline.js";
import { artifactFilterFromHash, createArtifacts, markdown } from "./artifacts.js";
import { fileAnswerSources } from "./file-questions.js";
import { channelChip, createReminders } from "./reminders.js";
import { reconcileChildren } from "./dom.js";
import { setupMobile } from "./mobile.js";
import { createThreadMenu } from "./thread-menu.js";
import { setupSearchableSelects } from "./combobox.js";
import { createAttachments } from "./attachments.js";
import { icon, iconButton, mountIcons } from "./icons.js";
import { setTimeZone, timeFormatter } from "./time.js";
import { createFeed } from "./feed.js";
import { createHome } from "./home.js";
import { createProactivity } from "./proactivity.js";
import { createAutomation } from "./automation.js";
import { createSkills, skillChip } from "./skills.js";
import { createWorkersCard } from "./workers.js";
import { createMemory } from "./memory.js";
import { createMemoryReview } from "./memory-review.js";
import { conversationView, newConversation, reconcile } from "./chat-state.js";
import { createSSEParser } from "./sse.js";
import { githubSettings, updateCard } from "./self-update.js";

mountIcons();
setupSearchableSelects();

const byId = (id) => document.getElementById(id);
const nav = [...document.querySelectorAll("[data-view]")];
const transcript = byId("transcript");
const input = byId("message");
const send = byId("send");
const stopReply = byId("stop-reply");
const replyStatus = byId("reply-status");
const notice = byId("notice");
const chatScroll = byId("chat-scroll");
const threadMenu = byId("thread-menu");
const threadActions = createThreadMenu(threadMenu);
const mobile = setupMobile({
  nearBottom, scrollDown, refreshThreads: refreshDrawerThreads, closeThreadMenu: threadActions.close,
});
const settingsGroups = [
  ["Assistant", [
    ["brain", "Brain", "Models and routing", "route"],
    ["memory", "Memory", "Recall and saved facts", "book"],
    ["search", "Search", "Web search providers", "search"],
    ["voice", "Voice", "Calls and dictation", "mic"],
  ]],
  ["Connected", [
    ["connections", "Connections", "Fly connectors and health", "plug"],
    ["artifacts", "Artifacts", "File sync and Box storage", "files"],
  ]],
  ["Notifications", [
    ["reminders", "Reminders", "Delivery and forwarded mail", "bell"],
    ["feed", "Feed", "Topics and steering", "sparkle"],
    ["proactivity", "Action suggestions", "Quiet hours and email digests", "bell"],
    ["automations", "Automations", "When events trigger actions", "clock"],
    ["watchers", "Watchers", "Public pages and Apify status", "monitor"],
    ["approvals", "Approvals", "When Hearth asks first", "shield"],
  ]],
  ["App", [
    ["home", "Home", "Weather location", "home"],
    ["appearance", "Appearance", "Ember view and style", "image"],
    ["about", "About", "Deployed Hearth version", "history"],
  ]],
];
const settingsDisclosures = new Map();
const connectionsLabel = "Settings → Connections";
const dateFormat = timeFormatter({ dateStyle: "medium", timeStyle: "short" });
const messageTime = timeFormatter({ hour: "numeric", minute: "2-digit" });
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
const mainThread = { id: "main", title: "Main", busy: false };
let threadList = [mainThread];
const requestedThread = new URLSearchParams(location.search).get("thread");
let currentThread = requestedThread || sessionStorage.getItem("hearth-thread") || mainThread.id;
let conversation = newConversation(currentThread);
const localTurns = () => [...conversation.turns.values()];
const turnBubbles = new Map();
const stopping = new Set();
let chatNoticeTurn;
let selectionVersion = 0;
let stateRequest = 0;
let threadSignature;
let seenReplies;
try {
  seenReplies = new Map(JSON.parse(localStorage.getItem("hearth-seen-replies") || "[]"));
} catch {
  seenReplies = new Map();
}
let sendingTestReminder = false;
let chatSignature;
let chatRows = new Map();
const workerCards = new Map();
let threadBusy = false;
let state;
let stateTag;
let stateVariant;
let olderRequest;
let historyRefresh;
let sidebarRequest;
let sidebarTail = [];
let homeCache;
let homeSequence = 0;
let homeActive = false;
let view = "home";
let memoryFindRequest = 0;
let busy = false;
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
let brainSettings;
let brainBusy = false;
let modelRequest;
let routingRequest;
let poolRequest;
let poolModels = {};
let poolDraft = [];
let poolDirty = false;
let settingsSection;
let reindexPoll;
const preferences = { memory: {}, search: {} };
let uploading = false;
const attachmentDraft = createAttachments({
  thread: () => currentThread, isChat: () => view === "chat", isBusy: () => busy,
  onChange(pending) {
    const follow = nearBottom();
    uploading = pending;
    send.disabled = busy || pending;
    if (follow) scrollDown();
  },
});
const timelineErrorRoute = "#timeline/errors";
const timeline = createTimeline({
  api, refreshAPI, approve, undo, gatewayResults, isBusy: () => busy,
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
  api, openChat: openSkillChat,
  onLinkedClose(id) {
    if (location.hash === skillHash(id)) {
      history.replaceState(history.state, "", skillHash());
    }
  },
});
const faceWorkers = createWorkersCard({ stop: stopWorkers });
const homeWorkers = createWorkersCard({
  heading: "Running now", stop: stopWorkers,
  openThread: async (thread) => {
    activateThread(thread);
    await openView("chat");
  },
});
const proactivity = createProactivity({ api });
const feed = createFeed({
  api, approvalCard: automation.approvalCard, refreshHome: () => homePage.load(), runSuggestion: (id) => chat("", { keepDraft: true, suggestion: id }),
  openReview: async (id) => {
    memoryPage.selectReview(id);
    await openView("memory");
  },
  openSettings: () => openSettingsSection("feed"),
  async openChat(thread, draft) {
    await openSkillChat(thread);
    input.value = draft;
    resizeInput();
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
  api, refreshAPI, openView, openSettings: openSettingsSection, onInbox: automation.inbox, currentView: () => view, currentSettings: () => settingsSection,
  startSending: () => {
    sendingTestReminder = true;
    renderThreads();
    avatarSignal(mainThread.id, { type: "tool_started", title: "Sending reminder" });
  },
  stopSending: () => {
    sendingTestReminder = false;
    renderThreads();
    avatarSignal(mainThread.id, { type: "tool_finished" });
  },
});
const memoryNames = { auto: "Auto", pinecone: "Pinecone", local: "Local", keyword: "Local", huggingface: "Local · Hugging Face embeddings" };
const folderNames = { root: "Profile and approvals", people: "people/", locations: "locations/",
  topics: "Topic notes", projects: "projects/", daily: "daily/" };
const brainProvider = byId("brain-provider");
const brainModel = byId("brain-model");
const customModel = byId("brain-custom");
const poolProvider = byId("pool-provider");
const poolModel = byId("pool-model");
const avatarModes = ["off", "beside", "face"];
const savedMode = localStorage.getItem("hearth-avatar-view");
let avatarMode = avatarModes.includes(savedMode) ? savedMode : "beside";
const savedLook = localStorage.getItem("hearth-avatar-look");
let avatarLook = Object.hasOwn(looks, savedLook) ? savedLook : "ember";
let avatarColor = localStorage.getItem("hearth-avatar-color") || "";
if (!/^#[0-9a-f]{6}$/i.test(avatarColor)) avatarColor = "";
const avatarStates = new Map();
const headerMascot = mascot(avatarLook, avatarColor);
const portraitMascot = mascot(avatarLook, avatarColor);
byId("avatar-header").append(headerMascot);
byId("avatar-portrait").append(portraitMascot);
const voiceLanguages = [...byId("voice-language").options].map((option) => option.value);
let voicePreferences = { engine: "auto", language: "auto", autoSend: false, seconds: 60 };
try {
  const saved = JSON.parse(localStorage.getItem("hearth-voice"));
  if (["auto", "browser", "whisper"].includes(saved?.engine)) voicePreferences.engine = saved.engine;
  if (voiceLanguages.includes(saved?.language)) voicePreferences.language = saved.language;
  if (Number.isInteger(saved?.seconds) && saved.seconds >= 5 && saved.seconds <= 120) voicePreferences.seconds = saved.seconds;
  voicePreferences.autoSend = saved?.autoSend === true;
} catch {
  // Start from the default settings if the saved value is unreadable.
}
const voiceLevel = byId("voice-level");
const mic = byId("mic");
let voicePhase = "idle";
let spaceHeld = false;
const voice = createVoiceInput({
  update: updateVoice,
  meter: (level) => { voiceLevel.value = level; },
  deliver: fillFromVoice,
});
const voiceCall = createVoiceCall({
  api,
  getThread: () => ({ id: currentThread, title: threadSource({ thread_id: currentThread }) }),
  isConfigured: () => state?.voice_call_available,
  prepare: () => {
    if (busy) return false;
    voice.cancel();
    spaceHeld = false;
    return true;
  },
  makeMascot: () => avatarMode === "off" ? null : mascot(avatarLook, avatarColor),
  update: (_, refresh) => {
    mic.disabled = voiceCall.inProgress;
    paintAvatars();
    if (refresh) refreshView().catch((error) => showNotice(error.message));
    if (view === "settings" && settingsSection === "voice" && !voiceCall.inProgress) voiceCall.refreshSettings();
  },
  onAction: openVoiceAction,
  date,
});

function avatarState(threadId, now) {
  if (!avatarStates.has(threadId)) avatarStates.set(threadId, newAvatar(now));
  return avatarStates.get(threadId);
}

function avatarSignal(threadId, event) {
  if (!threadId) return;
  const now = Date.now();
  avatarStates.set(threadId, avatarEvent(avatarState(threadId, now), event, now));
  paintAvatars();
}

function threadPose(thread, now) {
  const callPose = voiceCall.poseFor(thread.id);
  if (callPose) return callPose;
  if (isSendingReminder(thread.id)) return { pose: "working", detail: "Sending reminder" };
  const pose = avatarPose(avatarState(thread.id, now), now, isWorking(thread));
  const local = localTurns().some((turn) => turn.threadId === thread.id && turn.user && !turn.finished);
  if (pose.pose === "thinking" && !local && thread.activity) return thread.activity;
  return pose;
}

function updateText(element, text) {
  if (element.textContent !== text) element.textContent = text;
}

function paintAvatars() {
  if (view !== "chat" || avatarMode === "off") return;
  const now = Date.now();
  const active = threadList.find((thread) => thread.id === currentThread) || { id: currentThread };
  const current = threadPose(active, now);
  setPose(avatarMode === "face" ? portraitMascot : headerMascot, current);
  updateText(byId("avatar-caption"), current.pose === "idle" ? "" : poseLabel(current));
  byId("avatar-caption").hidden = current.pose === "idle";
  updateText(byId("face-status"), poseLabel(current));
  updateText(byId("avatar-status"), announcePose(current));
  for (const turn of conversation.turns.values()) {
    const bubble = turnBubbles.get(turn.key);
    if (turn.threadId === currentThread && bubble?.avatar && !turn.finished) {
      setPose(bubble.avatar, current);
    }
  }
}

function updateFaceCaption(text) {
  text = text.replace(/[ \t]*\[\[memory:[^\]\n]*\]\]/g, "");
  const tail = text.lastIndexOf("[[");
  if (tail >= 0) {
    const marker = text.slice(tail);
    if ("[[memory:".startsWith(marker) || (marker.startsWith("[[memory:") && !marker.includes("]]"))) {
      text = text.slice(0, tail);
    }
  }
  text = text.trim();
  const captions = byId("face-captions");
  if (captions.textContent === text) return;
  captions.hidden = !text;
  captions.textContent = text;
  captions.scrollTop = captions.scrollHeight;
}

function replyArtifacts(message, linkedArtifacts = state?.message_artifacts?.[message?.id]) {
  const linked = message?.artifacts || linkedArtifacts || [];
  const legacyPages = (message?.pages || []).map((page) => ({
    ...page, kind: "page", format: "html", version_number: page.version,
  }));
  return [...linked, ...legacyPages];
}

function updateFaceWorkers(workers = []) {
  const target = byId("face-workers");
  faceWorkers.update(workers);
  if (!faceWorkers.card.isConnected) target.append(faceWorkers.card);
  target.hidden = !workers.length;
}

function renderFace(local, messages, actions, remoteBrowse, remoteSkill, workers) {
  if (avatarMode !== "face") return;
  const active = local.find((turn) => (turn.user || turn.approval) && !turn.reply && !turn.finished);
  const latest = [...local].reverse().find((turn) => turn.reply || turn.error);
  const saved = messages.findLast((message) => message.role === "assistant");
  const reply = latest?.reply || saved;
  const pendingPrompt = messages.findLast((message) => message.role === "user");
  const pendingWorkers = !messages.some((message) => message.worker_turn_id === pendingPrompt?.id) &&
    workers.get(pendingPrompt?.id);
  updateFaceWorkers(active ? [...(active.workers?.values() || [])] :
    pendingWorkers || workers.get(reply?.worker_turn_id) || [...(latest?.workers?.values() || [])]);
  const skill = active ? active.skill : remoteSkill || reply?.skill;
  byId("face-skill").hidden = !skill;
  byId("face-skill").replaceChildren(...(skill ? [skillChip(skill)] : []));
  updateFaceCaption(active ? active.text : latest?.error || reply?.content || "");
  const items = active ? [...active.actions.values()] : pendingWorkers ?
    [...actions.values()].filter((action) => action.worker_turn_id === pendingPrompt.id) :
    (reply?.action_ids || []).map((id) => actions.get(id) || latest?.actions.get(id)).filter(Boolean);
  const details = byId("face-actions");
  const linked = active ? [] : replyArtifacts(reply);
  const screenshots = !active && (reply?.browse_images || []);
  const browse = active?.browse || remoteBrowse;
  byId("face-browse").replaceChildren(...(browse ? [browseCard(browse)] : []));
  details.hidden = !items.length && !linked.length && !screenshots?.length;
  if (details.hidden) details.open = false;
  details.querySelector(".cards").replaceChildren(...items.map((action) => actionCard(actions.get(action.id) || action)));
  if (linked.length) details.querySelector(".cards").append(artifactLibrary.chatActions(linked));
  if (screenshots?.length) details.querySelector(".cards").append(...screenshots.map(browseScreenshot));
}

function applyAppearance() {
  const hidden = avatarMode === "off";
  const full = avatarMode === "face";
  byId("avatar-view").value = avatarMode;
  byId("ember-view").value = avatarMode;
  byId("avatar-enabled").checked = !hidden;
  byId("avatar-header").hidden = hidden;
  byId("face-stage").hidden = !full;
  byId("chat-view").classList.toggle("avatar-off", hidden);
  byId("chat-view").classList.toggle("face-view", full);
  mobile.placeCallControls();
  if (hidden) {
    byId("avatar-caption").hidden = true;
    updateText(byId("avatar-status"), "");
  }
  setLook(headerMascot, avatarLook, avatarColor);
  setLook(portraitMascot, avatarLook, avatarColor);
  updateText(byId("avatar-name"), looks[avatarLook].name);
  for (const [preset, look] of Object.entries(looks)) {
    const choice = byId(`look-${preset}`);
    choice.setAttribute("aria-pressed", String(preset === avatarLook));
    setLook(choice.firstChild, preset, preset === avatarLook ? avatarColor : look.color);
  }
  byId("avatar-color").value = avatarColor || looks[avatarLook].color;
  byId("avatar-color-reset").disabled = !avatarColor;
  renderChat(true);
}

function chooseAvatarMode(mode) {
  const leavingFace = avatarMode === "face" && mode !== "face";
  if (mode === "face") mobile.closeDrawer();
  avatarMode = mode;
  localStorage.setItem("hearth-avatar-view", mode);
  applyAppearance();
  if (leavingFace && mobile.isMobile() && view === "chat") byId("open-menu").focus();
}

function whisperConnected() {
  const connection = connectionState?.providers?.huggingface?.status;
  return connection === "connected" || (connection == null && state?.whisper_available === true);
}

function syncVoiceSettings() {
  byId("voice-engine").value = voicePreferences.engine;
  byId("voice-language").value = voicePreferences.language;
  byId("voice-length").value = voicePreferences.seconds;
  byId("voice-auto-send").checked = voicePreferences.autoSend;
  showVoiceEngine();
}

function showVoiceEngine() {
  const engine = byId("voice-engine").value;
  const connected = whisperConnected();
  const browser = window.SpeechRecognition || window.webkitSpeechRecognition;
  const status = engine === "whisper"
    ? (connected ? "Hugging Face is connected." : "Connect Hugging Face in Settings → Connections to use Whisper.")
    : engine === "auto" && connected ? "Auto will use Hugging Face Whisper."
      : browser ? "Browser uses its default speech language when Language is set to Auto."
        : "This browser does not support speech recognition. Connect Hugging Face to use Whisper.";
  updateText(byId("voice-engine-status"), status);
}

function updateVoice({ thread, phase, interim = "", engine, message }) {
  const recording = phase === "recording";
  const processing = phase === "processing";
  const active = phase !== "idle";
  const follow = voicePhase !== phase && nearBottom();
  if (voicePhase !== phase) {
    if (recording || voicePhase === "recording") avatarSignal(thread, { type: "recording", active: recording });
    if (processing || voicePhase === "processing") avatarSignal(thread, { type: "voice_processing", active: processing });
    voicePhase = phase;
  }
  const bar = byId("voice-bar");
  bar.hidden = !active;
  bar.dataset.phase = phase;
  mic.setAttribute("aria-pressed", String(active));
  mic.setAttribute("aria-label", recording ? "Stop voice recording" : active ? "Cancel voice input" : "Start voice input");
  mic.title = active ? mic.getAttribute("aria-label") : "Start voice input. Hold Space in an empty composer to talk.";
  voiceLevel.hidden = !recording;
  if (!recording) voiceLevel.value = 0;
  updateText(byId("voice-phase"), recording ? `Recording · ${engine === "whisper" ? "Whisper" : "Browser"}`
    : processing ? "Transcribing…" : active ? "Waiting for microphone…" : "");
  updateText(byId("voice-key"), recording && spaceHeld ? "Release Space to finish · Esc to cancel" : "Esc to cancel");
  const preview = byId("voice-interim");
  preview.hidden = !interim;
  updateText(preview, interim);
  if (follow) scrollDown();
  if (message) showNotice(message);
}

function fillFromVoice({ thread, text, autoSend }) {
  if (thread !== currentThread || view !== "chat") return;
  if (autoSend && !busy) {
    chat(text, { keepDraft: true });
    return;
  }
  const draft = input.value;
  const start = input.selectionStart;
  const end = input.selectionEnd;
  const left = draft.slice(0, start);
  const right = draft.slice(end);
  const insertion = `${left && !/\s$/.test(left) ? " " : ""}${text}${right && !/^\s/.test(right) ? " " : ""}`;
  input.setRangeText(insertion.slice(0, Math.max(0, input.maxLength - left.length - right.length)), start, end, "end");
  resizeInput();
  input.focus();
  followComposer();
}

function startVoice() {
  if (view !== "chat" || busy || voiceCall.inProgress) return;
  showNotice();
  voice.start(currentThread, voicePreferences, whisperConnected());
}

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
  chatNoticeTurn = undefined;
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
  return trackRefresh(path, background, () => api(path, undefined, signal));
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
  busy = value;
  send.disabled = value || uploading;
  byId("attach").disabled = value;
  for (const item of document.querySelectorAll(".cards button, [data-prompt]")) {
    item.disabled = value;
  }
  timeline.setBusy();
  renderThreads();
  setBrainControls();
  schedulePoll();
}

function scrollDown() {
  chatScroll.scrollTop = chatScroll.scrollHeight;
}

function nearBottom() {
  return chatScroll.scrollHeight - chatScroll.scrollTop - chatScroll.clientHeight < 65;
}

function shortModel({ name, model, provider }) {
  return provider === "mock" ? "Mock" : model?.split("/").at(-1).split(":")[0] || name;
}

const messageVotes = new Map();

const menu = byId("message-menu");
const toast = byId("chat-toast");
let toastTimer;
let menuTrigger;
function showToast(message) {
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.hidden = false;
  toastTimer = setTimeout(() => { toast.hidden = true; }, 1700);
}

async function copyMessage(content) {
  if (menu.open) menu.close();
  try {
    await navigator.clipboard.writeText(content);
    showToast("Copied");
  } catch {
    showNotice("Couldn’t copy this message.");
  }
}

function restorePrompt(prompt) {
  if (input.value || attachmentDraft.hasDraft()) {
    showNotice("Clear the composer to restore this prompt.");
    return;
  }
  input.value = prompt.text;
  attachmentDraft.restore(currentThread, prompt.attachments);
  resizeInput();
  input.focus();
}

function messageToolbar(message, content, prompt) {
  const toolbar = node("div", "message-toolbar");
  const actions = node("div", "message-inline-actions");
  if (content) actions.append(iconButton("copy", "Copy", () => copyMessage(content)));
  if (prompt?.text || prompt?.attachments.length) {
    actions.append(iconButton("retry", "Retry", () => restorePrompt(prompt)));
  }
  for (const [key, label] of [["up", "Helpful"], ["down", "Unhelpful"]]) {
    const vote = iconButton(`thumbs-${key}`, label, () => {
      if (messageVotes.get(message.id) === key) messageVotes.delete(message.id);
      else messageVotes.set(message.id, key);
      for (const choice of actions.querySelectorAll("[data-vote]")) {
        choice.setAttribute("aria-pressed", String(messageVotes.get(message.id) === choice.dataset.vote));
      }
    });
    vote.dataset.vote = key;
    vote.setAttribute("aria-pressed", String(messageVotes.get(message.id) === key));
    actions.append(vote);
  }
  const footer = node("div", "message-route");
  if (message.at) {
    const stamp = node("time", "", messageTime.format(new Date(message.at)));
    stamp.dateTime = message.at;
    stamp.title = date(message.at);
    footer.append(stamp);
  }
  toolbar.append(actions, footer);
  return toolbar;
}

byId("close-message-menu").addEventListener("click", () => menu.close());
let pressedBackdrop = false;
menu.addEventListener("pointerdown", (event) => {
  const { left, right, top, bottom } = menu.getBoundingClientRect();
  pressedBackdrop = event.target === menu && (event.clientX < left || event.clientX > right ||
    event.clientY < top || event.clientY > bottom);
});
menu.addEventListener("click", (event) => {
  if (pressedBackdrop && event.target === menu) menu.close();
  pressedBackdrop = false;
});
menu.addEventListener("close", () => {
  pressedBackdrop = false;
  if (menuTrigger?.isConnected) menuTrigger.focus({ preventScroll: true });
  menuTrigger = undefined;
});

function bindMessageMenu(item, message, content) {
  const threadId = currentThread;
  item.tabIndex = 0;
  item.setAttribute("aria-haspopup", "dialog");
  item.setAttribute("aria-keyshortcuts", "Enter Space Shift+F10");
  function open() {
    if (menu.open || !item.isConnected) return;
    const actions = byId("message-menu-actions");
    actions.replaceChildren();
    const action = (glyph, label, handler) => {
      const choice = button("", handler);
      choice.append(icon(glyph, 18), label);
      actions.append(choice);
    };
    if (content) action("copy", "Copy", () => copyMessage(content));
    if (threadId !== mainThread.id) action("share", "Share to Main", () => {
      menu.close();
      changeThread("share", { thread_id: threadId, message_id: message.id });
    });
    if (message.at) {
      const stamp = node("time", "", date(message.at));
      stamp.dateTime = message.at;
      actions.append(stamp);
    }
    menuTrigger = item;
    menu.showModal();
    (actions.querySelector("button") || byId("close-message-menu")).focus();
  }

  let timer, origin, held;
  const cancel = () => clearTimeout(timer);
  const interactive = (event) => event.target.closest("a, button, details, input, pre, .message-toolbar");
  item.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" || interactive(event)) return;
    origin = { x: event.clientX, y: event.clientY };
    held = false;
    timer = setTimeout(() => { held = true; open(); }, 480);
  });
  item.addEventListener("pointermove", (event) => {
    if (origin && Math.hypot(event.clientX - origin.x, event.clientY - origin.y) > 10) cancel();
  });
  item.addEventListener("pointerup", cancel);
  item.addEventListener("pointercancel", cancel);
  item.addEventListener("contextmenu", (event) => {
    if (interactive(event) || !getSelection()?.isCollapsed) return;
    event.preventDefault();
    cancel();
    open();
  });
  item.addEventListener("click", (event) => {
    if (!held && event.pointerType === "touch" && !interactive(event) && getSelection()?.isCollapsed) open();
    held = false;
  });
  item.addEventListener("keydown", (event) => {
    if (event.target !== item || !["Enter", " ", "ContextMenu"].includes(event.key) &&
        !(event.key === "F10" && event.shiftKey)) return;
    event.preventDefault();
    open();
  });
}

function checkCollapsedReplies() {
  for (const toggle of transcript.querySelectorAll(".message-expand")) {
    const text = toggle.previousElementSibling;
    if (toggle.getAttribute("aria-expanded") === "true") continue;
    toggle.hidden = text.scrollHeight <= text.clientHeight + 1;
    for (const link of text.querySelectorAll("a")) {
      link.tabIndex = link.getBoundingClientRect().bottom > text.getBoundingClientRect().bottom ? -1 : 0;
    }
  }
}
window.addEventListener("resize", checkCollapsedReplies);

function messageBubble(role, content, { message, status, prompt, working, attachments = [], skill = message?.skill,
  linkedArtifacts, uploadMetadata = state?.message_uploads } = {}) {
  const item = node("article", `message ${role}`);
  let avatar;
  if (role === "assistant") {
    avatar = mascot(avatarLook, avatarColor);
    if (!working) avatar.dataset.still = "";
    item.append(avatar);
  }
  const body = node("div", "message-body");
  if (skill) body.append(skillChip(skill));
  const text = message?.file_answer ? node("p", "file-answer-text", content)
    : role === "assistant" && message?.id ? markdown(content, "chat-markdown") : node("p", "", content);
  const cards = node("div", "cards");
  const notices = node("div");
  notices.setAttribute("role", "status");
  if (status) notices.append(node("p", "queued-label", status));
  if (working) {
    body.classList.add("message-working");
    const dots = node("span", "typing-dots");
    dots.setAttribute("aria-hidden", "true");
    dots.append(node("i"), node("i"), node("i"));
    body.append(dots);
    text.setAttribute("role", "status");
  }
  text.hidden = !content;
  body.append(notices, text);
  if (role === "assistant" && message?.id && content) {
    const toggle = button("Show more", () => {
      const expanded = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", String(!expanded));
      toggle.textContent = expanded ? "Show more" : "Show less";
      text.classList.toggle("message-clamped", expanded);
      if (expanded) {
        toggle.scrollIntoView({ block: "nearest" });
        checkCollapsedReplies();
      } else {
        for (const link of text.querySelectorAll("a")) link.removeAttribute("tabindex");
      }
    });
    toggle.className = "message-expand";
    toggle.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
    text.classList.add("message-clamped");
    body.append(toggle);
  }
  body.append(cards);
  if (message?.file_answer) body.append(fileAnswerSources(message.file_answer));
  if (message?.source === "voice-call" && role === "assistant") body.append(node("p", "meta", "Voice call"));
  if (message?.remembered?.length) {
    const sources = node("details", "remembered");
    const count = message.remembered.length;
    const summary = node("summary", "", `${count} memory ${count === 1 ? "source" : "sources"}`);
    const sourceThread = currentThread;
    summary.addEventListener("click", () => avatarSignal(sourceThread, { type: "remembered" }));
    sources.append(summary);
    sources.append(...message.remembered.map((hit) =>
      button(memoryLabel(hit), () => openMemorySource(hit))));
    body.append(sources);
  }
  if (attachments.length) body.append(artifactLibrary.attachmentCards(attachments));
  if (message?.attachment_citations?.length) {
    const sources = node("div", "attachment-sources");
    sources.setAttribute("aria-label", "Attachment sources");
    sources.append(node("span", "", "Sources"));
    for (const id of message.attachment_citations) {
      const file = uploadMetadata?.[id] || localTurns().flatMap((turn) => turn.attachments || [])
        .find((item) => item.id === id);
      if (!file) continue;
      const source = button("", (event) => artifactLibrary.openAttachment(file, event.currentTarget));
      source.setAttribute("aria-haspopup", "dialog");
      source.title = file.filename;
      source.append(icon("paperclip", 14), node("span", "", file.filename));
      sources.append(source);
    }
    if (sources.childElementCount > 1) body.append(sources);
  }
  if (message?.id) item.dataset.messageId = message.id;
  if (role === "assistant" && message?.id) {
    const linked = replyArtifacts(message, linkedArtifacts);
    if (linked.length) body.append(artifactLibrary.chatActions(linked));
    if (message.browse_images?.length) body.append(...message.browse_images.map(browseScreenshot));
  }
  item.append(body);
  if (message?.id) {
    bindMessageMenu(item, message, content);
    if (role === "assistant") item.append(messageToolbar(message, content, prompt));
  }
  return { item, avatar, cards, notices, text };
}

function threadSource(item, fallback = "Main") {
  return threadList.find((thread) => thread.id === item.thread_id)?.title || item.thread_title || fallback;
}

function timelineSource(item) {
  const name = threadSource(item);
  return item.source === "voice-call" ? `${name} · Voice call` : name;
}

function browseScreenshot(image) {
  const open = button("", (event) => artifactLibrary.openBrowse(image, event.currentTarget));
  open.className = "browse-screenshot";
  open.setAttribute("aria-haspopup", "dialog");
  const thumbnail = node("img");
  thumbnail.src = `/api/browse/screenshots/${image.name}`;
  thumbnail.alt = "";
  thumbnail.loading = "lazy";
  open.append(thumbnail, node("span", "", `${image.mock ? "Mock screenshot" : "Browser screenshot"} · ${image.domain}`));
  return open;
}

function browseCard(browse) {
  const card = node("section", "card browse-card");
  const status = node("div", "browse-progress");
  status.setAttribute("role", "status");
  status.append(node("span", "browse-indicator"), node("strong", "", `Browsing ${browse.domain}…`));
  card.append(status);
  if (browse.live_url || browse.mock) {
    const watch = button("Watch live", (event) => artifactLibrary.openBrowse(browse, event.currentTarget));
    watch.setAttribute("aria-haspopup", "dialog");
    card.append(watch);
  }
  return card;
}

function actionCard(action) {
  if (action.tool) return automation.approvalCard(action);
  const card = node("article", "card");
  const header = node("div", "card-header");
  const statuses = {
    pending: "Awaiting approval", changing: "Interrupted", partial: "Partially applied", cancelled: "Stopped",
    simulated: "Simulated send", unknown: "Delivery unknown", sending: "Delivery unknown",
    sent: "Sent", complete: action.kind === "gateway" ? "Completed" : "", request_unknown: "Request unconfirmed",
  };
  header.append(node("h4", "", action.title), node("span", "meta", statuses[action.status] || ""));
  card.append(header, node("p", "thread-source", `From ${timelineSource(action)}`));
  if (action.worker_title) card.append(node("p", "thread-source", `Worker · ${action.worker_title}`));
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
  if (action.kind === "panel") {
    const titles = action.panel_titles || action.panel_definitions?.map((panel) => panel.title) || [];
    if (titles.length) card.append(node("p", "", titles.join(" · ")));
    if (action.status === "pending") card.append(button("Approve and create panels", () => approve(action)));
    else if (action.status === "complete") card.append(button("Open Home", () => openView("home")));
  }
  if (action.kind === "remember") {
    card.append(node("p", "", action.fact));
    if (action.status === "pending") card.append(button("Approve", () => approve(action)));
  }
  if (action.kind === "browse") {
    card.append(node("p", "", action.url));
    const steps = node("ol", "browse-steps");
    for (const step of action.steps) {
      const label = { navigate: "Open", scroll: "Scroll", wait_for: "Wait for", click: "Click", fill: "Enter text in" };
      const value = step.action === "fill" ? ` · “${step.text}”` : "";
      steps.append(node("li", "", `${label[step.action]} ${step.target}${value}`));
    }
    card.append(steps);
    if (action.mock) card.append(node("p", "meta", "Mock browser action"));
    if (action.status === "pending") {
      const approveBrowse = button("Approve browser action", () => chat("", { approval: action, keepDraft: true }));
      approveBrowse.disabled = localTurns().some((turn) => turn.approval?.id === action.id && !turn.finished);
      card.append(approveBrowse);
    } else if (action.status === "complete") {
      card.append(node("p", "meta", "Completed"));
    } else if (action.status === "failed") {
      card.append(node("p", "meta", "Steps did not run"));
    }
  }
  if (action.paths) card.append(node("p", "", action.paths.join(", ")));
  if (action.job) {
    const controls = node("div", "delivery-actions");
    const chip = button("", () => openView("reminders"));
    chip.setAttribute("aria-label", "Open Reminders");
    chip.append(channelChip(action.job.channel));
    controls.append(chip);
    if (action.job.cancelable ?? (action.job.status === "scheduled" && !action.undone)) {
      controls.append(button("Undo", () => undo(action)));
    }
    card.append(node("p", "", action.job.message), node("p", "meta", date(action.job.next_at)), controls);
    if (action.undone) card.append(node("p", "meta", "Canceled"));
  }
  if (action.detail) card.append(node("p", "", action.detail));
  if (action.kind === "skill" && (action.undoable ?? !action.undone)) card.append(button("Undo", () => undo(action)));
  if (action.checkpoint) {
    if (action.kind !== "gateway" && (action.kind !== "email" || action.mocked)) card.append(button("Undo", () => undo(action)));
  }
  for (const item of card.querySelectorAll("button")) item.disabled = busy;
  return card;
}

function isWorking(thread) {
  return thread?.busy || localTurns().some((turn) => turn.threadId === thread?.id && !turn.finished);
}

const summarySheet = byId("thread-summary");
let threadMenuId;
let summaryThread;

function syncThreadMenu(thread) {
  const pinned = thread?.id === mainThread.id;
  byId("thread-menu-title").textContent = thread?.title || "";
  const rename = threadMenu.querySelector('[value="rename"]');
  const remove = threadMenu.querySelector('[value="delete"]');
  rename.hidden = remove.hidden = pinned;
  rename.disabled = busy || threadBusy || !thread;
  remove.disabled = busy || threadBusy || !thread || !!thread.busy;
  threadMenu.querySelector('[value="summary"]').disabled = !thread;
}

function openThreadMenu(thread, trigger, options) {
  threadMenuId = thread.id;
  syncThreadMenu(thread);
  threadActions.open(trigger, options);
}

function isSendingReminder(threadId) {
  return state?.reminder_sending?.includes(threadId) || (threadId === mainThread.id && sendingTestReminder);
}

function markSeenReplies() {
  if (!state) return;
  let changed = false;
  for (const thread of threadList) {
    const canRead = view === "chat" && !document.hidden && !byId("workspace-drawer").open
      && state.thread_id === thread.id && currentThread === thread.id;
    if ((!seenReplies.has(thread.id) || canRead) && seenReplies.get(thread.id) !== thread.last_reply) {
      seenReplies.set(thread.id, thread.last_reply);
      changed = true;
    }
  }
  if (changed) localStorage.setItem("hearth-seen-replies", JSON.stringify([...seenReplies]));
}

function renderThreads() {
  const entries = threadList.map((thread) => {
    const busy = isWorking(thread);
    const unread = thread.last_reply && seenReplies.get(thread.id) !== thread.last_reply;
    const status = isSendingReminder(thread.id) ? "Sending reminder"
      : busy ? "Working" : unread ? "Unread reply" : "";
    return { ...thread, busy, status };
  });
  const active = entries.find((item) => item.id === currentThread);
  const signature = JSON.stringify([entries, currentThread, busy, threadBusy, avatarMode]);
  if (signature === threadSignature) return;
  threadSignature = signature;
  const list = byId("threads");
  const focused = list.contains(document.activeElement) ? document.activeElement : null;
  updateText(byId("thread-list-status"), entries.filter((thread) => thread.status)
    .map((thread) => `${thread.title}: ${thread.status}`).join(". "));
  list.replaceChildren(...entries.map((thread) => {
    const item = button("", () => {
      if (view !== "chat") {
        activateThread(thread.id);
        openView("chat");
      } else {
        const fromDrawer = mobile.closeDrawer({ restoreFocus: false });
        selectThread(thread.id);
        if (fromDrawer) byId("thread-title").focus({ preventScroll: true });
      }
    });
    item.className = "thread-link";
    item.dataset.thread = thread.id;
    const label = node("span", "thread-label", thread.title);
    item.append(label);
    if (thread.id !== mainThread.id && thread.title !== "Main") {
      item.addEventListener("pointerenter", () => {
        if (label.scrollWidth > label.clientWidth) item.title = thread.title;
      });
      item.addEventListener("pointerleave", () => item.removeAttribute("title"));
    }
    if (thread.id === currentThread) item.setAttribute("aria-current", "true");
    if (thread.status) {
      const dot = node("span", "thread-dot");
      dot.dataset.status = thread.status === "Unread reply" ? "unread" : "working";
      dot.setAttribute("aria-hidden", "true");
      item.append(dot, node("span", "visually-hidden", ` · ${thread.status}`));
    }
    const row = node("div", "thread-row");
    row.append(item);
    const more = iconButton("more", `Actions for ${thread.title}`,
      (event) => openThreadMenu(thread, event.currentTarget), "thread-overflow");
    more.removeAttribute("title");
    more.dataset.thread = thread.id;
    more.setAttribute("aria-haspopup", "menu");
    more.setAttribute("aria-expanded", "false");
    more.setAttribute("aria-controls", threadMenu.id);
    more.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      event.preventDefault();
      openThreadMenu(thread, more, { last: event.key === "ArrowUp" });
    });
    row.append(more);
    return row;
  }));
  if (focused) {
    const replacement = [...list.querySelectorAll("button")].find((item) =>
      item.dataset.thread === focused.dataset.thread && item.className === focused.className);
    (replacement || list.querySelector('[aria-current="true"]'))?.focus({ preventScroll: true });
  }
  if (!threadMenu.hidden) {
    const thread = entries.find((thread) => thread.id === threadMenuId);
    if (thread) {
      syncThreadMenu(thread);
      threadActions.refresh(threadMenuTrigger(thread.id));
    } else {
      threadActions.close({ restoreFocus: false });
      list.querySelector('[aria-current="true"]')?.focus({ preventScroll: true });
    }
  }
  const select = byId("thread-select");
  select.replaceChildren(...entries.map((thread) => new Option(thread.status ? `${thread.title} · ${thread.status}` : thread.title, thread.id)));
  select.value = currentThread;
  byId("thread-title").textContent = active?.title || (currentThread === mainThread.id ? "Main" : "Side chat");
  const activity = byId("thread-activity");
  activity.hidden = avatarMode !== "off" || !active?.status || active.status === "Unread reply";
  updateText(activity, active?.status || "");
  byId("thread-controls").hidden = !active || active.id === mainThread.id;
  byId("new-thread").disabled = busy || threadBusy;
  byId("rename-thread").disabled = busy || threadBusy;
  const remove = byId("delete-thread");
  remove.disabled = busy || threadBusy || !!active?.busy;
  remove.title = active?.busy ? "Wait for this chat to finish" : "Delete this side chat";
  send.title = active?.busy ? "Queue follow-up" : "Send message";
  send.setAttribute("aria-label", send.title);
  paintAvatars();
}

function rememberThread(thread) {
  const index = threadList.findIndex((item) => item.id === thread.id);
  if (index < 0) threadList.push(thread);
  else threadList[index] = { ...threadList[index], ...thread };
}

function callCard(message) {
  const card = node("article", "card call-card");
  card.dataset.messageId = message.id;
  const header = node("div", "card-header");
  header.append(node("h4", "", message.content), node("time", "call-card-duration", callDuration(message.duration)));
  card.append(header);
  if (message.lines.length) {
    const details = node("details");
    const list = node("ol", "call-captions");
    list.append(...message.lines.map(captionLine));
    details.append(node("summary", "", "Call transcript"), list);
    card.append(details);
  } else {
    card.append(node("p", "meta", "No transcript saved."));
  }
  return card;
}

async function stopWorkers(turnId, id) {
  await api("/api/workers/stop", { turn_id: turnId, ...(id ? { id } : {}) });
  await refreshView();
}

function workersCard(workers) {
  const turnId = workers[0].turn_id;
  if (!workerCards.has(turnId)) workerCards.set(turnId, createWorkersCard({ stop: stopWorkers }));
  const widget = workerCards.get(turnId);
  widget.update(workers);
  return widget.card;
}

const activeReply = () => localTurns().find((turn) =>
  turn.threadId === currentThread && turn.id && !turn.finished && !turn.reply && !turn.stopped);

function updateStopReply() {
  const turn = activeReply();
  if (!turn && document.activeElement === stopReply) input.focus({ preventScroll: true });
  stopReply.hidden = !turn;
  stopReply.setAttribute("aria-disabled", String(stopping.has(turn?.key)));
}

stopReply.addEventListener("click", async () => {
  const turn = activeReply();
  if (!turn || stopping.has(turn.key)) return;
  stopping.add(turn.key);
  updateStopReply();
  try {
    const result = await api("/api/chat/stop", { thread_id: turn.threadId, reply_id: turn.id });
    if (!result.stopped && activeReply()?.key === turn.key) showNotice("This reply has already finished.");
  } catch (error) {
    showNotice(error.message);
  } finally {
    stopping.delete(turn.key);
    updateStopReply();
  }
});

function updateConversation(update) {
  const result = reconcile(conversation, update);
  const changed = conversation !== result.state;
  conversation = result.state;
  const announcements = [];
  for (const { turn, reply } of result.completed) {
    if (update.type !== "stream") {
      artifactLibrary.endBrowse(turn.browse?.id);
      avatarSignal(turn.threadId, { type: "done", remembered: !!reply.remembered?.length });
    }
    if (chatNoticeTurn === turn.key) {
      showNotice();
    }
    if (turn.threadId === currentThread && view === "chat" && !byId("workspace-drawer").open) {
      const excerpt = [...reply.content.replace(/\s+/g, " ").trim()];
      const clipped = excerpt.slice(0, 99).join("");
      const snippet = excerpt.length > 100 ? `${clipped.replace(/\s+\S*$/, "")}…` : excerpt.join("");
      announcements.push(node("span", "", snippet ? `Hearth replied. ${snippet}` : "Hearth replied."));
    }
  }
  if (announcements.length) replyStatus.replaceChildren(...announcements);
  return { changed, turn: result.turn };
}

function renderChat(force = false, preserveScroll = false) {
  renderThreads();
  const { transcript: history, local } = conversationView(conversation);
  const actions = new Map((history.actions || []).map((action) => [action.id, action]));
  const proposals = new Map((history.self_updates || []).map((proposal) => [proposal.id, proposal]));
  const messages = history.messages || [];
  updateStopReply();
  const workers = new Map();
  for (const worker of history.workers || []) {
    if (!workers.has(worker.turn_id)) workers.set(worker.turn_id, []);
    workers.get(worker.turn_id).push(worker);
  }
  const localPrompts = new Set(local.map((turn) => turn.user?.id));
  const savedBatches = new Set(messages.map((message) => message.worker_turn_id).filter(Boolean));
  const thread = threadList.find((item) => item.id === currentThread);
  const remoteBrowse = thread?.activity?.browse;
  const remoteSkill = thread?.activity?.skill;
  const signature = JSON.stringify([currentThread, messages, threadList.map((thread) => thread.title),
    avatarLook, avatarColor, busy,
    history.message_artifacts, history.message_uploads, history.self_updates, state?.timezone, history.workers, remoteBrowse, remoteSkill, thread?.skill,
    local.map(({ user, reply, approval, finished }) => [user?.id, reply?.id, approval?.id, finished]),
    messages.flatMap((message) => (message.action_ids || []).map((id) => actions.get(id)))]);
  if (!force && signature === chatSignature) return;
  chatSignature = signature;
  const follow = !preserveScroll && nearBottom();
  turnBubbles.clear();
  const rows = [];
  const nextRows = new Map();
  byId("welcome").hidden = currentThread !== mainThread.id || !!(messages.length || local.length);
  byId("side-welcome").hidden = currentThread === mainThread.id || !!(messages.length || local.length);
  byId("side-skill").hidden = !thread?.skill;
  byId("side-skill").replaceChildren(...(thread?.skill ? [skillChip(thread.skill, "Skill ready")] : []));
  const context = history.previous_prompt;
  let previousPrompt = context ? { text: context.content,
    attachments: context.attachment_ids.map((id) => history.message_uploads?.[id]).filter(Boolean) } : undefined;
  for (const [index, stored] of messages.entries()) {
    const message = stored.id ? stored : { ...stored, id: `${currentThread}:${index + 1}` };
    const attachments = (message.attachment_ids || []).map((id) => history.message_uploads?.[id]).filter(Boolean);
    const cards = [...new Set(message.action_ids || [])].map((id) => actions.get(id)).filter(Boolean);
    const rowSignature = JSON.stringify([currentThread, message, cards, cards.map((action) => threadSource(action)),
      cards.length ? [busy, local.map(({ approval, finished }) => [approval?.id, finished])] : false,
      history.message_artifacts?.[message.id], attachments, state?.timezone, avatarLook, avatarColor,
      message.attachment_citations?.map((id) => history.message_uploads?.[id]),
      message.role === "assistant" ? previousPrompt : null]);
    let row = chatRows.get(message.id);
    if (row?.signature !== rowSignature) {
      let item, bubble;
      if (message.role === "call") {
        item = callCard(message);
      } else {
        bubble = messageBubble(message.role, message.content, {
          message, prompt: previousPrompt, attachments, linkedArtifacts: history.message_artifacts?.[message.id],
          uploadMetadata: history.message_uploads,
        });
        for (const notice of message.notices || []) bubble.notices.append(node("p", "model-warning", notice));
        for (const action of cards) bubble.cards.append(actionCard(action));
        item = bubble.item;
      }
      row = { item, bubble, signature: rowSignature };
    }
    if (row.bubble && workers.has(message.worker_turn_id)) {
      const card = workersCard(workers.get(message.worker_turn_id));
      if (row.bubble.cards.firstElementChild !== card) row.bubble.cards.prepend(card);
    }
    if (row.bubble && proposals.has(message.self_update_id)) {
      const proposal = proposals.get(message.self_update_id);
      if (row.proposalCard) row.proposalCard.render(proposal);
      else {
        row.proposalCard = updateCard(proposal, { perform: changeSelfUpdate, announce: announceSelfUpdate });
        row.bubble.cards.append(row.proposalCard.card);
      }
    }
    nextRows.set(message.id, row);
    rows.push(row.item);
    if (workers.has(message.id) && !localPrompts.has(message.id) && !savedBatches.has(message.id)) {
      const activity = messageBubble("assistant", "");
      activity.cards.append(workersCard(workers.get(message.id)));
      for (const action of actions.values()) {
        if (action.worker_turn_id === message.id) activity.cards.append(actionCard(action));
      }
      rows.push(activity.item);
    }
    if (message.role === "user") previousPrompt = { text: message.content, attachments };
  }
  for (const turn of local) {
    if (turn.showPrompt) {
      rows.push(messageBubble("user", turn.user?.content || turn.prompt, {
        message: turn.user, status: turn.user ? undefined : "Queued", attachments: turn.attachments,
      }).item);
    }
    if (!turn.showReply) continue;
    const content = turn.reply ? turn.reply.content
      : turn.text || turn.error || (turn.stopped ? "Reply stopped." : turn.browse ? "" : turnProgress(turn));
    const bubble = messageBubble("assistant", content, {
      message: turn.reply, skill: turn.skill, prompt: { text: turn.prompt, attachments: turn.attachments },
      working: !turn.reply && !turn.error && !turn.text && !turn.browse && !turn.stopped,
    });
    turnBubbles.set(turn.key, bubble);
    bubble.text.hidden = !content && !!turn.browse;
    rows.push(bubble.item);
    const workerRows = turn.workers?.size ? [...turn.workers.values()] : workers.get(turn.user?.id);
    if (workerRows?.length) bubble.cards.append(workersCard(workerRows));
    for (const warning of turn.warnings) bubble.notices.append(node("p", "model-warning", warning));
    if (turn.stopped && turn.text) bubble.notices.append(node("p", "model-warning", "Reply stopped."));
    for (const action of turn.actions.values()) {
      const saved = actions.get(action.id);
      const current = action.worker_id && (action.status !== "pending" || saved?.status === "pending") ? action : saved;
      bubble.cards.append(actionCard(current || action));
    }
    if (turn.browse) bubble.cards.append(browseCard(turn.browse));
    if (turn.error) {
      const target = turn.text ? node("p", "model-warning") : bubble.text;
      showConnectionGuidance(target, turn.error);
      if (turn.text) bubble.notices.append(target);
      const retry = iconButton("retry", "Edit and retry", () =>
        restorePrompt({ text: turn.user?.content || turn.prompt, attachments: turn.attachments }));
      bubble.cards.append(retry);
    }
  }
  if ((remoteBrowse || remoteSkill) && !local.length) {
    const activity = messageBubble("assistant", "", { skill: remoteSkill });
    activity.text.hidden = true;
    if (remoteBrowse) activity.cards.append(browseCard(remoteBrowse));
    rows.push(activity.item);
  }
  reconcileChildren(transcript, rows);
  checkCollapsedReplies();
  chatRows = nextRows;
  for (const id of workerCards.keys()) {
    if (!workers.has(id) && !localPrompts.has(id)) workerCards.delete(id);
  }
  renderFace(local, messages, actions, remoteBrowse, remoteSkill, workers);
  paintAvatars();
  if (follow) scrollDown();
}

function announceSelfUpdate(row, { complete, stage }) {
  const key = `hearth-update-${row.id}`;
  if ((row.status === "waiting" || row.status === "updating") && sessionStorage.getItem(key) !== "announced") {
    sessionStorage.setItem(key, "pending");
  }
  if (complete && sessionStorage.getItem(key) === "pending") {
    sessionStorage.setItem(key, "announced");
    byId("self-update-status").replaceChildren(node("span", "", stage));
  }
}

async function changeSelfUpdate(operation, { id, thread_id, head }, feedback) {
  const result = await api(`/api/self-update/${operation}`, { id, thread_id, head,
    ...(operation === "revise" ? { feedback } : {}) });
  schedulePoll(true);
  return result;
}

function installSidebar(complete) {
  const entries = new Map();
  for (const thread of [...state.threads.slice(0, state.next_thread_offset ?? undefined), ...sidebarTail]) {
    entries.set(thread.id, thread);
  }
  for (const thread of state.threads) entries.set(thread.id, thread);
  for (const [id, thread] of entries) {
    const active = state.thread_activity;
    entries.set(id, { ...thread, busy: Object.hasOwn(active, id), activity: Object.hasOwn(active, id) ? active[id] : undefined });
  }
  for (const thread of threadList) {
    const browse = thread.activity?.browse;
    if (browse && (complete || entries.has(thread.id)) && entries.get(thread.id)?.activity?.browse?.id !== browse.id) {
      artifactLibrary.endBrowse(browse.id);
    }
  }
  threadList = [...entries.values()];
  if (isSetting("memory")) renderMemoryThreadOptions();
  markSeenReplies();
  renderThreads();
}

async function extendSidebar() {
  const revision = state.thread_revision;
  if (sidebarRequest?.revision === revision) return;
  const request = { revision };
  sidebarRequest = request;
  let offset = state.next_thread_offset;
  if (offset == null) {
    sidebarTail = [];
    installSidebar(true);
    return;
  }
  const tail = [];
  try {
    while (offset != null) {
      const page = await api(`/api/threads?offset=${offset}`, undefined, AbortSignal.timeout(6000));
      if (sidebarRequest !== request) return;
      if (page.thread_revision !== revision) {
        sidebarRequest = undefined;
        return;
      }
      tail.push(...page.threads);
      offset = page.next_thread_offset;
    }
    sidebarTail = tail;
    installSidebar(true);
    if (view === "chat") renderChat();
  } catch {
    if (sidebarRequest === request) sidebarRequest = undefined;
  }
}

async function loadOlderMessages() {
  if (olderRequest || !conversation.snapshot) return false;
  const before = (conversation.pages[0] || conversation.snapshot).before;
  if (!before) return false;
  const thread = currentThread, version = selectionVersion;
  const request = { before };
  olderRequest = request;
  try {
    const page = await transcriptPage(thread, before);
    if (olderRequest !== request || version !== selectionVersion) return false;
    const anchor = transcript.firstElementChild;
    const messageId = anchor?.dataset.messageId;
    const top = anchor?.getBoundingClientRect().top;
    if (!updateConversation({ type: "page", page, cursor: before }).changed) return false;
    renderChat(true, true);
    const retained = chatRows.get(messageId)?.item;
    if (retained && top !== undefined) chatScroll.scrollTop += retained.getBoundingClientRect().top - top;
    return true;
  } catch (error) {
    if (olderRequest === request) showNotice(error.message);
    return false;
  } finally {
    if (olderRequest === request) olderRequest = undefined;
  }
}

function transcriptPage(thread, before) {
  return api(`/api/transcript?thread=${encodeURIComponent(thread)}&before=${encodeURIComponent(before)}`,
    undefined, AbortSignal.timeout(6000));
}

async function refreshVisibleHistory() {
  if (historyRefresh || view !== "chat" || document.hidden || !conversation.pages.length) return;
  const viewport = chatScroll.getBoundingClientRect();
  const page = conversation.pages.find(({ messages, cursor, record_revision: revision }) => {
    if (!cursor || revision === state.record_revision) return false;
    const first = chatRows.get(messages[0]?.id)?.item;
    const last = chatRows.get(messages.at(-1)?.id)?.item;
    return first && last && first.getBoundingClientRect().top < viewport.bottom &&
      last.getBoundingClientRect().bottom > viewport.top;
  });
  if (!page) return;
  historyRefresh = page;
  try {
    const latest = await transcriptPage(currentThread, page.cursor);
    const { changed } = updateConversation({ type: "page", page: latest, previous: page });
    if (changed && view === "chat") renderChat(true, true);
  } catch {
    // A changed or unavailable page can be retried on the next refresh.
  } finally {
    if (historyRefresh === page) historyRefresh = undefined;
  }
}

async function refreshState(actionId, { background } = {}) {
  const request = ++stateRequest;
  const thread = currentThread;
  const params = new URLSearchParams({ thread });
  if (actionId) params.set("action", actionId);
  const variant = params.toString();
  const headers = conversation.snapshot && stateTag && stateVariant === variant ? { "If-None-Match": stateTag } : {};
  const load = async () => {
    const response = await fetch(`/api/state?${variant}`, {
      headers, signal: AbortSignal.timeout(6000),
    });
    return [response, response.status === 304 ? null : await readResponse(response)];
  };
  const [response, next] = await (view === "chat" ? trackRefresh("/api/state", background, load) : load());
  if (response.status === 304) {
    const current = request === stateRequest && thread === currentThread;
    if (current) {
      markSeenReplies();
      void extendSidebar();
    }
    return current;
  }
  if (request !== stateRequest || thread !== currentThread) return false;
  if (next.thread_id !== currentThread) {
    const deleted = currentThread;
    activateThread(next.thread_id);
    threadDrafts.delete(deleted);
    attachmentDraft.discard(deleted);
    avatarStates.delete(deleted);
    updateConversation({ type: "delete-thread", threadId: deleted });
  }
  if (conversation.snapshot?.history_revision !== next.history_revision) olderRequest = undefined;
  state = next;
  updateConversation({ type: "snapshot", snapshot: next });
  setTimeZone(state.timezone);
  stateTag = response.headers.get("ETag");
  stateVariant = variant;
  byId("start-call").disabled = typeof state.voice_call_available !== "boolean";
  installSidebar(state.next_thread_offset == null || sidebarRequest?.revision === state.thread_revision);
  void extendSidebar();
  renderBrain(state);
  paintAvatars();
  schedulePoll();
  if (view === "settings" && settingsSection === "voice") showVoiceEngine();
  return true;
}

function refreshDrawerThreads() {
  if (busy || threadBusy) return;
  refreshState().catch((error) => {
    if (byId("workspace-drawer").open) showNotice(error.message);
  });
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
  if (busy || !window.confirm(`${question} Hearth will save a checkpoint first.`)) return;
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
  container.replaceChildren(node("p", "meta", "Searching memory…"));
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

function settingsHash(section, target) {
  return "#settings" + (section ? `/${section}` : "") + (target ? `/${encodeURIComponent(target)}` : "");
}

function skillHash(id) {
  return id ? `#skills/${encodeURIComponent(id)}` : "#skills";
}

function connectionHash(tab) {
  return settingsHash("connections", tab);
}

function isSetting(section) {
  return view === "settings" && settingsSection === section;
}

function workspaceRoute() {
  const hash = location.hash;
  if (hash === "#settings") return { view: "settings", hash };
  const [root, ...path] = hash.slice(1).split("/");
  const [section, item, extra] = root === "settings" ? path : [root, ...path];
  if (extra === undefined && section === "skills") {
    let target;
    if (item) {
      try { target = decodeURIComponent(item); } catch { /* Open the library for a malformed skill link. */ }
    }
    return { view: "skills", target, hash: skillHash(target) };
  }
  if (extra === undefined && (root === "settings" || root === "connections") && settingsDisclosures.has(section)) {
    const target = section === "connections" && configTabs.includes(item) ? item : undefined;
    return { view: "settings", section, target, hash: settingsHash(section, target) };
  }
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
  openView(route.view, false, route.section, route.target);
  if (focusSection) focusSetting(route.section);
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
      if (view === "settings" && settingsSection === "voice") {
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
  byId("brain-workers").disabled = locked;
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
  return model.provider === "huggingface" && model.model ? shortModel(model)
    : `${model.name} · ${model.model || "Automatic model"}`;
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
  modelDetail.textContent = choice.available ? "Loading chat models…" : "Refresh Settings → Connections after authorizing this provider.";
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
    byId("brain-workers").value = brainSettings.parallel_workers;
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
  if (operation === "settings") draft.parallel_workers = Number(byId("brain-workers").value);
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

function renderMemoryThreadOptions() {
  const select = byId("memory-test-thread");
  settingOptions(select, [["", "All threads"], ...threadList.map(({ id, title }) => [id, title])], select.value);
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
  if (running && view === "settings" && settingsSection === "memory") {
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

function focusSetting(section) {
  const control = settingsDisclosures.get(section);
  const previous = control.closest(".settings-entry").previousElementSibling;
  const anchor = previous.matches(".settings-group-label") ? previous : control;
  anchor.scrollIntoView({ block: "start" });
  control.focus({ preventScroll: true });
}

async function openSettings(section, target) {
  settingsSection = section;
  renderRefreshStatus();
  clearTimeout(reindexPoll);
  for (const [key, disclosure] of settingsDisclosures) {
    const open = key === section;
    disclosure.setAttribute("aria-expanded", String(open));
    byId(`settings-${key}`).hidden = !open;
  }
  settingsDisclosures.get(section)?.scrollIntoView({ block: "nearest" });
  if (!section) return;
  if (section === "connections") {
    renderConnections();
    const mailCard = delivery.connections();
    await updateConnections("rescan");
    await mailCard;
    if (isSetting("connections")) delivery.poll();
    return;
  }
  if (section === "brain") return openBrainSettings();
  if (section === "appearance") return;
  if (section === "about") {
    const version = byId("hearth-version");
    try {
      version.textContent = (await api("/health")).version || "Local checkout";
    } catch (error) {
      version.textContent = error.message;
    }
    return;
  }
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
    if (!busy && !threadBusy) {
      refreshState(undefined, { background: true }).catch(() => {
        // The recall form can still search across all threads.
      });
    }
  }
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

async function openView(nextView, updateHistory = true, section, target) {
  const previousView = view;
  const fromDrawer = mobile.closeDrawer({ restoreFocus: false });
  if (nextView !== previousView) threadActions.close({ restoreFocus: false });
  if (previousView === "home" && nextView !== "home") homePage.closeAdd({ restoreFocus: false });
  if (nextView !== previousView) showNotice();
  if (nextView !== "chat") voice.cancel();
  if (updateHistory) {
    const hash = nextView === "settings" ? settingsHash(section) : nextView === "artifacts" ? artifactHash()
      : nextView === "skills" ? skillHash() : "";
    const sameArtifactsView = nextView === "artifacts" && workspaceRoute()?.view === "artifacts";
    if (hash !== location.hash && !sameArtifactsView) {
      history.pushState({ hearthView: nextView }, "", hash || location.pathname + location.search);
    }
  }
  history.replaceState({ ...history.state, hearthView: nextView }, "");
  if (view === "timeline" && nextView !== view) timeline.hide();
  if (nextView !== "skills") skills.clearLink();
  view = nextView;
  schedulePoll();
  byId("start-call").hidden = view !== "chat";
  byId("view-title").textContent = view[0].toUpperCase() + view.slice(1);
  clearTimeout(reindexPoll);
  for (const item of nav) {
    const active = item.dataset.view === view;
    if (active) {
      item.setAttribute("aria-current", "page");
    } else {
      item.removeAttribute("aria-current");
    }
    byId(`${item.dataset.view}-view`).hidden = !active;
  }
  if (fromDrawer) byId("view-title").focus({ preventScroll: true });
  paintAvatars();
  renderWorkspaceStatus();
  if (view !== "settings") renderRefreshStatus();
  if (view === "timeline") timeline.setTodayErrors(location.hash === timelineErrorRoute);
  if (view === "settings") {
    if (previousView !== "settings") byId("settings-view").scrollTop = 0;
    await openSettings(section, target);
  } else if (view === "home") {
    if (previousView !== "home") byId("home-view").scrollTop = 0;
    await homePage.load();
    if (previousView !== "home" && feed.root.isConnected) feed.show(true);
  } else if (view === "skills") {
    if (previousView !== "skills") byId("skills-view").scrollTop = 0;
    await skills.loadLinked(target);
  } else if (view === "artifacts") {
    artifactLibrary.selectFormat(artifactFilterFromHash(location.hash) || "all");
    await artifactLibrary.show();
  } else if (view === "reminders" || view === "inbox") {
    await refreshView();
    if (view === "inbox") delivery.poll();
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
  voice.cancel();
  threadDrafts.set(currentThread, input.value);
  currentThread = threadId;
  selectionVersion++;
  stateRequest++;
  updateConversation({ type: "select", threadId });
  replyStatus.replaceChildren();
  olderRequest = undefined;
  historyRefresh = undefined;
  sessionStorage.setItem("hearth-thread", threadId);
  input.value = threadDrafts.get(threadId) || "";
  attachmentDraft.render();
  input.placeholder = threadId === mainThread.id ? "Message Hearth…" : "Message this side chat…";
  resizeInput();
  renderChat(true);
  scrollDown();
}

async function selectThread(threadId, focus = false) {
  activateThread(threadId);
  if (focus && mobile.isMobile()) mobile.closeDrawer();
  showNotice();
  if (focus && view === "chat") {
    if (!mobile.isMobile()) input.focus();
  }
  try {
    await refreshView();
  } catch (error) {
    if (currentThread === threadId) showNotice(error.message);
  }
}

function openSettingsSection(section) {
  return openView("settings", true, section);
}

function openWeatherSettings() {
  return openSettingsSection("home");
}

function openConnections() {
  const opening = openSettingsSection("connections");
  focusSetting("connections");
  return opening;
}

async function openPanelChat(id) {
  const thread = await api("/api/home/chat", { id });
  rememberThread(thread);
  activateThread(thread.id);
  await openView("chat");
  input.value = "What should I know about this panel?";
  resizeInput();
  if (!mobile.isMobile()) input.focus();
}

async function openSkillChat(thread) {
  rememberThread(thread);
  activateThread(thread.id);
  await openView("chat");
  if (!mobile.isMobile()) input.focus();
}

async function openDemo(prompt) {
  activateThread(mainThread.id);
  await openView("chat");
  if (input.value || attachmentDraft.hasDraft()) {
    showNotice("Send or clear your draft to load the Home demo prompt.");
    return;
  }
  input.value = prompt;
  resizeInput();
  if (!mobile.isMobile()) input.focus();
}

function openMainChat() {
  activateThread(mainThread.id);
  return openView("chat");
}

function sendPanelPrompt(prompt) {
  if (busy) throw new Error("Wait for the current Chat action to finish, then try again.");
  return chat(prompt, { keepDraft: true, threadId: mainThread.id });
}

async function openArtifactThread(threadId, messageId) {
  activateThread(threadId);
  await openView("chat");
  const version = selectionVersion;
  let message = chatRows.get(messageId)?.item;
  while (!message && threadId === currentThread && view === "chat" && version === selectionVersion &&
      await loadOlderMessages()) {
    message = chatRows.get(messageId)?.item;
  }
  if (message) {
    message.classList.add("artifact-anchor");
    message.tabIndex = -1;
    message.focus({ preventScroll: true });
    message.scrollIntoView({ block: "center" });
  } else if (threadId !== currentThread) {
    showNotice("The source chat is no longer available.");
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
      if (view !== "chat") await openView("chat");
    } else if (operation === "delete") {
      threadList = threadList.filter((item) => item.id !== body.thread_id);
      if (currentThread === body.thread_id) activateThread(mainThread.id);
      threadDrafts.delete(body.thread_id);
      attachmentDraft.discard(body.thread_id);
      avatarStates.delete(body.thread_id);
      updateConversation({ type: "delete-thread", threadId: body.thread_id });
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

function turnProgress(turn) {
  return turn.activity ? `${turn.activity}…` : "Thinking…";
}

function readChatEvent(key, { event: name, data, id: eventId }) {
  const payload = JSON.parse(data);
  if (name === "error") {
    const turn = conversation.turns.get(key);
    if (turn && !turn.reply && !turn.stopped) throw new Error(payload.message);
    return;
  }
  const { turn } = updateConversation({ type: "stream", key, name, payload, eventId });
  if (!turn) return;
  const visible = turn.threadId === currentThread;
  const bubble = visible && turnBubbles.get(key);

  if (name === "queued") {
    avatarSignal(turn.threadId, { type: "queued" });
    rememberThread(payload.thread);
    if (turn.suggestion && turn.selection === selectionVersion) {
      activateThread(turn.threadId);
      void openView("chat");
    } else if (turn.command && turn.selection === selectionVersion) {
      activateThread(turn.threadId);
      if (view === "chat") input.focus();
    }
  } else if (name === "started") {
    rememberThread(payload.thread);
    if (conversation.turns.has(key)) avatarSignal(turn.threadId, { type: "started" });
  } else if (name === "token" || name === "reset") {
    const follow = visible && nearBottom();
    avatarSignal(turn.threadId, { type: name, text: payload.text });
    if (bubble) {
      bubble.text.textContent = turn.text || turnProgress(turn);
      bubble.text.parentElement.classList.toggle("message-working", !turn.text);
    }
    if (avatarMode === "face" && visible) updateFaceCaption(turn.text);
    if (follow) scrollDown();
    return;
  } else if (name === "action") {
    if (payload.kind === "reminder") {
      avatarSignal(turn.threadId, { type: "reminder", until: Date.parse(payload.job.next_at) });
    } else if (payload.status === "complete" && ["memory", "remember"].includes(payload.kind)) {
      avatarSignal(turn.threadId, { type: "celebrate" });
    }
  } else if (name === "model_warning") {
    avatarSignal(turn.threadId, { type: "warning" });
  } else if (name === "done") {
    avatarSignal(turn.threadId, { type: "done", remembered: !!turn.reply.remembered?.length });
  } else if (name === "stopped") {
    avatarSignal(turn.threadId, { type: "done" });
  } else if (name === "worker" && bubble) {
    const follow = nearBottom();
    const workers = [...turn.workers.values()];
    const card = workersCard(workers);
    if (card.parentElement !== bubble.cards) bubble.cards.prepend(card);
    if (avatarMode === "face") updateFaceWorkers(workers);
    if (follow) scrollDown();
    return;
  } else if (name === "browse_active") {
    avatarSignal(turn.threadId, { type: "tool_started", title: `Browsing ${payload.domain}` });
  } else if (name === "browse_finished") {
    artifactLibrary.endBrowse(payload.id);
    avatarSignal(turn.threadId, { type: "tool_finished" });
  } else if (name === "tool_started" || name === "tool_finished" || name === "demo_listening") {
    if (bubble && !turn.text) updateText(bubble.text, turnProgress(turn));
    avatarSignal(turn.threadId, { type: name, title: payload.title });
    return;
  } else if (name === "remembered") {
    avatarSignal(turn.threadId, { type: "remembered" });
    return;
  } else if (name === "tool_warning" || name === "demo_warning") {
    avatarSignal(turn.threadId, { type: "warning", detail: name === "demo_warning" ? "Mock demo" : "" });
    return;
  }
  if (turn.threadId === currentThread) renderChat(true);
  else renderThreads();
}

async function chat(prompt, { keepDraft = false, approval, suggestion, threadId = currentThread } = {}) {
  prompt = prompt.trim();
  if (busy || (approval && localTurns().some((turn) => turn.approval?.id === approval.id && !turn.finished))) return;
  const attachments = keepDraft || approval ? [] : attachmentDraft.selected();
  if (!attachments || (!prompt && !approval && !suggestion && !attachments.length)) return;
  voice.cancel();
  const source = approval?.thread_id || threadId;
  const command = !attachments.length && source === mainThread.id && /^\/(side|btw)(?:\s|$)/i.test(prompt);
  const key = Symbol();
  updateConversation({ type: "begin", key, source, turn: {
    threadId: command || suggestion ? undefined : source, selection: selectionVersion, command,
    prompt, approval, suggestion, attachments,
  } });
  schedulePoll();
  showNotice();
  if (!keepDraft) {
    input.value = "";
    attachmentDraft.discard(source);
  }
  resizeInput();
  renderChat(true);
  scrollDown();

  let failure;
  try {
    await connectionRequest;
    const endpoint = suggestion ? "/api/proactivity/do" : approval ? "/api/browse/approve" : "/api/chat";
    const body = suggestion ? { id: suggestion } : approval ? { id: approval.id, thread_id: source }
      : { message: prompt, thread_id: source, attachment_ids: attachments.map((item) => item.id) };
    const response = await fetch(endpoint, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error || "Hearth could not start this turn.");
    }
    if (suggestion && response.headers.get("Content-Type")?.startsWith("application/json")) {
      updateConversation({ type: "discard", key });
      await openSkillChat(await response.json());
      return;
    }
    const parser = createSSEParser();
    for await (const chunk of response.body) {
      for (const event of parser.push(chunk)) readChatEvent(key, event);
    }
    const pending = conversation.turns.get(key);
    if (pending && !pending.reply && !pending.stopped) {
      throw new Error("The reply was interrupted. Check Timeline for any saved actions.");
    }
    return pending;
  } catch (error) {
    const pending = conversation.turns.get(key);
    if (pending && !pending.reply && !pending.stopped) {
      failure = error.message;
      avatarSignal(pending.threadId || source, { type: "error" });
      if (!pending.user) {
        if (!keepDraft) attachmentDraft.restore(source, attachments);
        if (source === currentThread && !input.value) {
          input.value = prompt;
          resizeInput();
        }
      }
      if ((pending.threadId || source) === currentThread) {
        showNotice(failure);
        chatNoticeTurn = key;
      }
    }
    return { ...pending, error: failure };
  } finally {
    const pending = conversation.turns.get(key);
    artifactLibrary.endBrowse(pending?.browse?.id);
    updateConversation({ type: "finish", key, error: failure });
    if (!pending?.threadId || pending.threadId === currentThread) renderChat(true);
    else renderThreads();
    await refreshView().catch(() => {});
  }
}

async function approve(action) {
  if (busy) return;
  setBusy(true);
  showNotice();
  const threadId = action.thread_id || mainThread.id;
  avatarSignal(threadId, { type: "approval_started", title: action.title });
  try {
    const result = await api("/api/approve", { id: action.id });
    if (result.response) gatewayResults.set(action.id, result.response);
    avatarSignal(threadId, { type: "approval_done", success: ["complete", "sent", "simulated"].includes(result.status) });
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
    avatarSignal(threadId, { type: "approval_done", success: false });
    showNotice(error.message);
  } finally {
    setBusy(false);
  }
}

async function undo(action, { confirmed = false, timelineTitle, redo = false } = {}) {
  if (action.job || action.inbox_id || action.undo_task || action.undo_automation || action.automation_id) {
    if (busy) return;
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
    if (busy || (!confirmed && !window.confirm("Undo this memory change?"))) return;
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
    if (busy || (["skill", "goal"].includes(action.kind) && !confirmed && !window.confirm(`Undo this ${action.kind} change?`))) return;
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
    if (busy) return;
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
  if (busy || (!confirmed && !window.confirm(`Restore checkpoint ${action.checkpoint.id}? This rolls back the workspace, including newer chat, memory, and reminders. Delivered email stays delivered.`))) return;
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
      if (state.restore?.action_id === action.id && state.restore.status === "failed") {
        throw new Error("The checkpoint could not be restored.");
      }
      if (!state.actions.some((item) => item.id === action.id && item.checkpoint?.id === action.checkpoint.id)) {
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

function resizeInput() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 132)}px`;
}

function followComposer() {
  const caret = input.selectionStart;
  const start = input.value.slice(0, caret).lastIndexOf("\n") + 1;
  const breakAt = input.value.indexOf("\n", caret);
  const end = breakAt < 0 ? input.value.length : breakAt;
  const gaze = 2 * (caret - start) / Math.max(1, end - start) - 1;
  avatarSignal(currentThread, { type: "typing", gaze });
}

for (const [preset, look] of Object.entries(looks)) {
  const choice = button("", () => {
    avatarLook = preset;
    localStorage.setItem("hearth-avatar-look", preset);
    applyAppearance();
  });
  choice.id = `look-${preset}`;
  const preview = mascot(preset);
  preview.dataset.still = "";
  choice.append(preview, node("span", "", look.name));
  byId("avatar-looks").append(choice);
}
byId("avatar-view").addEventListener("change", (event) => chooseAvatarMode(event.target.value));
byId("ember-view").addEventListener("change", (event) => {
  const mode = event.target.value;
  chooseAvatarMode(mode);
  if (mode === "face") {
    openView("chat");
    byId("avatar-view").focus();
  }
});
byId("avatar-enabled").addEventListener("change", (event) => chooseAvatarMode(event.target.checked ? "beside" : "off"));
byId("avatar-color").addEventListener("input", (event) => {
  avatarColor = event.target.value;
  localStorage.setItem("hearth-avatar-color", avatarColor);
  applyAppearance();
});
byId("avatar-color-reset").addEventListener("click", () => {
  avatarColor = "";
  localStorage.removeItem("hearth-avatar-color");
  applyAppearance();
});
mic.addEventListener("click", () => voice.active ? voice.stop() : startVoice());
byId("call-connections").addEventListener("click", openConnections);
byId("voice-engine").addEventListener("change", showVoiceEngine);
byId("voice-settings-form").addEventListener("submit", (event) => {
  event.preventDefault();
  voicePreferences = {
    engine: byId("voice-engine").value,
    language: byId("voice-language").value,
    seconds: byId("voice-length").valueAsNumber,
    autoSend: byId("voice-auto-send").checked,
  };
  localStorage.setItem("hearth-voice", JSON.stringify(voicePreferences));
  updateText(byId("voice-settings-status"), "Voice settings saved.");
});
document.addEventListener("keydown", (event) => {
  if (voiceCall.open) return;
  if (event.key === "Escape" && voice.active) {
    event.preventDefault();
    voice.cancel();
  } else if (event.key === "Escape" && view === "chat" && avatarMode === "face") {
    chooseAvatarMode("beside");
    if (!mobile.isMobile()) byId("avatar-view").focus();
  } else if (event.code === "Space" && !event.isComposing && !event.altKey && !event.ctrlKey && !event.metaKey) {
    if (spaceHeld) {
      event.preventDefault();
    } else if (!event.repeat && !event.shiftKey && view === "chat" && !busy && !voice.active && !voiceCall.inProgress && !input.value.trim()
        && (event.target === input || event.target === document.body)) {
      event.preventDefault();
      spaceHeld = true;
      startVoice();
    }
  }
});
document.addEventListener("keyup", (event) => {
  if (event.code !== "Space" || !spaceHeld) return;
  event.preventDefault();
  spaceHeld = false;
  if (voicePhase === "recording" || voicePhase === "requesting") voice.stop();
});
setInterval(() => {
  if (!document.hidden) paintAvatars();
}, 100);

byId("composer").addEventListener("submit", (event) => {
  event.preventDefault();
  if (document.activeElement === send) input.focus({ preventScroll: true });
  chat(input.value);
});
byId("voice-cancel").addEventListener("click", () => {
  voice.cancel();
  byId("mic").focus({ preventScroll: true });
});
byId("thread-select").addEventListener("change", (event) => selectThread(event.target.value));
byId("new-thread").addEventListener("click", () => changeThread("create"));
function renameThread(thread) {
  if (!thread || busy || threadBusy) return;
  const title = window.prompt("Rename side chat", thread.title)?.trim();
  if (title && title !== thread.title) changeThread("rename", { thread_id: thread.id, title });
}
function deleteThread(thread) {
  if (thread && !busy && !threadBusy && !isWorking(thread) &&
      window.confirm(`Delete “${thread.title}”? Hearth will save a checkpoint first.`)) {
    changeThread("delete", { thread_id: thread.id });
  }
}
byId("rename-thread").addEventListener("click", () => renameThread(threadList.find((item) => item.id === currentThread)));
byId("delete-thread").addEventListener("click", () => deleteThread(threadList.find((item) => item.id === currentThread)));
function showSummary(summary) {
  const text = byId("thread-summary-text");
  text.textContent = summary;
  text.hidden = !summary;
  byId("thread-summary-status").textContent = summary ? "" : "No summary yet.";
}

async function openSummary(thread) {
  const target = { ...thread };
  summaryThread = target;
  showSummary("");
  byId("thread-summary-thread").textContent = thread.title;
  byId("thread-summary-status").textContent = "Loading summary…";
  const reset = byId("reset-thread-summary");
  reset.disabled = true;
  summarySheet.showModal();
  try {
    const result = await api(`/api/threads/summary?thread=${encodeURIComponent(thread.id)}`);
    if (summarySheet.open && summaryThread === target) {
      showSummary(result.summary);
      reset.disabled = false;
    }
  } catch (error) {
    if (summarySheet.open && summaryThread === target) byId("thread-summary-status").textContent = error.message;
  }
}

byId("reset-thread-summary").addEventListener("click", async (event) => {
  const target = summaryThread;
  if (!target || !window.confirm(`Reset the summary for “${target.title}”?`)) return;
  const reset = event.currentTarget;
  reset.disabled = true;
  try {
    const result = await api("/api/threads/summary/reset", { thread_id: target.id });
    if (summarySheet.open && summaryThread === target) showSummary(result.summary);
  } catch (error) {
    if (summarySheet.open && summaryThread === target) byId("thread-summary-status").textContent = error.message;
  } finally {
    if (summarySheet.open && summaryThread === target) {
      reset.disabled = false;
      reset.focus({ preventScroll: true });
    }
  }
});
threadMenu.addEventListener("click", (event) => {
  const item = event.target.closest('[role="menuitem"]');
  if (!item || item.disabled || item.hidden) return;
  const thread = threadList.find((item) => item.id === threadMenuId);
  threadActions.close();
  if (item.value === "summary" && thread) openSummary(thread);
  if (item.value === "rename") renameThread(thread);
  if (item.value === "delete") deleteThread(thread);
});
function threadMenuTrigger(threadId) {
  return [...byId("threads").querySelectorAll(".thread-overflow")].find((item) => item.dataset.thread === threadId);
}
summarySheet.addEventListener("close", () => {
  if (!threadMenu.hidden || summarySheet.open || (mobile.isMobile() && !byId("workspace-drawer").open)) return;
  (threadMenuTrigger(summaryThread?.id) || byId("new-thread")).focus({ preventScroll: true });
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
for (const [groupName, sections] of settingsGroups) {
  const group = node("div", "settings-group");
  const groupLabel = node("p", "settings-group-label", groupName);
  groupLabel.id = `settings-group-${groupName.toLowerCase()}`;
  group.setAttribute("role", "group");
  group.setAttribute("aria-labelledby", groupLabel.id);
  group.append(groupLabel);
  for (const [section, title, subtitle, symbol] of sections) {
    const panel = byId(`settings-${section}`);
    const disclosure = button("", () => openSettingsSection(isSetting(section) ? undefined : section));
    disclosure.className = "settings-disclosure";
    disclosure.dataset.settings = section;
    disclosure.setAttribute("aria-controls", panel.id);
    disclosure.setAttribute("aria-expanded", "false");
    const copy = node("span", "settings-label");
    const name = node("span", "settings-title", title);
    const description = node("span", "settings-subtitle", subtitle);
    name.id = `${panel.id}-title`;
    description.id = `${panel.id}-subtitle`;
    disclosure.setAttribute("aria-labelledby", name.id);
    disclosure.setAttribute("aria-describedby", description.id);
    copy.append(name, description);
    disclosure.append(icon(symbol), copy, icon("chevron", 18));
    const heading = node("h2", "settings-heading");
    heading.append(disclosure);
    const entry = node("div", "settings-entry");
    entry.append(heading, panel);
    group.append(entry);
    settingsDisclosures.set(section, disclosure);
  }
  byId("settings-sections").append(group);
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
byId("memory-sync").addEventListener("click", () => changePreferences("memory", "sync"));
byId("memory-reindex").addEventListener("click", () => {
  const connected = preferences.memory.info?.available.pinecone;
  const question = connected ? "Rebuild the Pinecone index for this profile from saved memories?"
    : "Rebuild the local index from saved memories?";
  if (window.confirm(question)) changePreferences("memory", "reindex");
});
input.addEventListener("input", () => {
  resizeInput();
  followComposer();
});
input.addEventListener("select", () => {
  if (Date.now() < avatarStates.get(currentThread)?.typing) followComposer();
});
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    chat(input.value);
  }
});
for (const prompt of document.querySelectorAll("[data-prompt]")) {
  prompt.addEventListener("click", () => chat(prompt.dataset.prompt));
}
for (const link of document.querySelectorAll("[data-connection-warning]")) {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    openConnections();
  });
}
for (const item of nav) {
  item.addEventListener("click", () => openView(item.dataset.view));
}
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    spaceHeld = false;
    voice.cancel();
    if (view === "timeline") timeline.hide();
  }
  if (!document.hidden) delivery.poll();
  schedulePoll(true);
});
let lastChatTop = 0;
chatScroll.addEventListener("scroll", () => {
  const top = chatScroll.scrollTop;
  if (view === "chat" && top <= 64 && top < lastChatTop) void loadOlderMessages();
  else void refreshVisibleHistory();
  lastChatTop = top;
}, { passive: true });
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
  const active = busy || threadBusy || localTurns().some((turn) => !turn.finished) ||
    (view === "home" ? homeActive : view === "chat" ? state?.active_work : true);
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
      if (!busy) await refreshPineconeHealth();
    } else if (view === "chat" && !threadBusy) {
      const previous = state;
      if (await refreshState(undefined, { background: true }) && view === "chat") {
        if (previous !== state) renderChat();
        await refreshVisibleHistory();
      }
    } else if (!threadBusy && (view === "home" || (!busy && (["reminders", "inbox"].includes(view) ||
        isSetting("automations") || (immediate && view === "timeline"))))) {
      await refreshView({ background: true });
    }
    if (drawer && view !== "chat" && !threadBusy) await refreshState();
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
applyAppearance();
renderWorkspaceStatus();
syncWorkspaceRoute();
schedulePoll();
if (!document.hidden) delivery.poll();
if (!isSetting("connections")) updateConnections("rescan");
