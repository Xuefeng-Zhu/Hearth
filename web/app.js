import { avatarEvent, avatarPose, newAvatar } from "./avatar-state.js";
import { announcePose, looks, mascot, poseLabel, setLook, setPose } from "./avatar.js";
import { createVoiceInput } from "./voice.js";
import { callDuration, captionLine, createVoiceCall } from "./voice-call.js";
import { createTimeline } from "./timeline.js";
import { artifactFilterFromHash, createArtifacts, markdown } from "./artifacts.js";
import { channelChip, createReminders } from "./reminders.js";
import { reconcileChildren } from "./dom.js";
import { setupMobile } from "./mobile.js";
import { createAttachments } from "./attachments.js";
import { icon, iconButton, mountIcons } from "./icons.js";
import { setTimeZone, timeFormatter } from "./time.js";
import { createHome } from "./home.js";
import { createAutomation } from "./automation.js";
import { createSkills, skillChip } from "./skills.js";

mountIcons();

const byId = (id) => document.getElementById(id);
const nav = [...document.querySelectorAll("[data-view]")];
const transcript = byId("transcript");
const input = byId("message");
const send = byId("send");
const notice = byId("notice");
const chatScroll = byId("chat-scroll");
const mobile = setupMobile({ nearBottom, scrollDown });
const settingsTabs = [...document.querySelectorAll("[data-settings]")];
const settingsDisclosures = new Map();
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
const turns = new Set();
const mainThread = { id: "main", title: "Main", busy: false };
let threadList = [mainThread];
const requestedThread = new URLSearchParams(location.search).get("thread");
let currentThread = requestedThread || sessionStorage.getItem("hearth-thread") || mainThread.id;
let selectionVersion = 0;
let stateRequest = 0;
let threadSignature;
let chatSignature;
let chatRows = new Map();
let threadBusy = false;
let state;
let stateTag;
let view = "home";
let selectedFile;
let selectedSource;
let fileRequest = 0;
let memoryFindRequest = 0;
let busy = false;
let connectionState;
let workspaceModel;
let workspaceConnectorError = false;
let homeConnectorError = false;
const workspaceStatusLabels = document.querySelectorAll("[data-workspace-status]");
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
let expandedSetting;
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
  api, approve, undo, gatewayResults, isBusy: () => busy,
  onFilter() {
    if (location.hash === timelineErrorRoute) {
      history.replaceState({ hearthView: "timeline" }, "", location.pathname + location.search);
    }
  },
});
const artifactLibrary = createArtifacts({
  api, showNotice, openThread: openArtifactThread,
  openConnections: () => openView("connections"),
  refreshChat: async () => { if (view === "chat") await refreshView(); },
  onFilter: selectArtifactFilter,
});
const automation = createAutomation({
  api, refresh: refreshView, undo, openThread: async (thread) => {
    activateThread(thread);
    await openView("chat");
  },
});
const skills = createSkills({ api, openChat: openSkillChat });
const homePage = createHome({
  api, openView, openWeatherSettings, openPanelChat, openDemo,
  openFile: (file, trigger) => artifactLibrary.open(file.id, trigger, file),
  onData(data) {
    setTimeZone(data.timezone);
    automation.home(data.approvals || []);
    const connections = data.builtin.connections;
    homeConnectorError = !!connections.error || connections.items.some((entry) => entry.status === "error");
    renderBrain(data);
  },
});
const delivery = createReminders({
  api, openView, openSettings, onInbox: automation.inbox, currentView: () => view, currentSettings: () => settingsSection,
  startSending: () => avatarSignal(currentThread, { type: "tool_started", title: "Sending reminder" }),
  stopSending: () => avatarSignal(currentThread, { type: "tool_finished" }),
});
const memoryNames = { auto: "Auto", pinecone: "Pinecone", local: "Local", keyword: "Local", huggingface: "Local · Hugging Face embeddings" };
const folderNames = { root: "Root · USER.md", people: "people/", topics: "topics/", daily: "daily/" };
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
const avatarThreads = new Map();
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
  if (state?.reminder_sending?.includes(thread.id)) return { pose: "working", detail: "Sending reminder" };
  const pose = avatarPose(avatarState(thread.id, now), now, isWorking(thread));
  const local = [...turns].some((turn) => turn.threadId === thread.id && turn.user && !turn.finished);
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
  for (const thread of threadList) {
    if (avatarThreads.has(thread.id)) setPose(avatarThreads.get(thread.id), threadPose(thread, now));
  }
  for (const turn of turns) {
    if (turn.threadId === currentThread && turn.bubble?.avatar && !turn.finished) {
      setPose(turn.bubble.avatar, current);
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

function replyArtifacts(message) {
  const linked = message?.artifacts || state?.message_artifacts?.[message?.id] || [];
  const legacyPages = (message?.pages || []).map((page) => ({
    ...page, kind: "page", format: "html", version_number: page.version,
  }));
  return [...linked, ...legacyPages];
}

function renderFace(local, messages, actions, remoteBrowse, remoteSkill) {
  if (avatarMode !== "face") return;
  const active = local.find((turn) => (turn.user || turn.approval) && !turn.reply && !turn.finished);
  const latest = [...local].reverse().find((turn) => turn.reply || turn.error);
  const saved = messages.findLast((message) => message.role === "assistant");
  const reply = latest?.reply || saved;
  const skill = active ? active.skill : remoteSkill || reply?.skill;
  byId("face-skill").hidden = !skill;
  byId("face-skill").replaceChildren(...(skill ? [skillChip(skill)] : []));
  updateFaceCaption(active ? active.text : latest?.error || reply?.content || "");
  const items = active ? [...active.actions.values()]
    : (reply?.action_ids || []).map((id) => actions.get(id) || latest?.actions.get(id)).filter(Boolean);
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
  byId("avatar-enabled").checked = !hidden;
  byId("avatar-header").hidden = hidden;
  byId("face-stage").hidden = !full;
  byId("chat-view").classList.toggle("avatar-off", hidden);
  byId("chat-view").classList.toggle("face-view", full);
  mobile.placeAvatarControl();
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
    ? (connected ? "Hugging Face is connected." : "Connect Hugging Face in Connections to use Whisper.")
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
  const target = byId("workspace-drawer").open ? byId("drawer-notice") : notice;
  target.hidden = !message;
  target.textContent = message;
}

async function api(path, data, signal) {
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
  if (message.routing) {
    const route = message.routing;
    const model = shortModel(route);
    const label = node("span", "", model);
    label.title = route.model || model;
    footer.append(label);
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

function messageBubble(role, content, { message, status, prompt, working, attachments = [], skill = message?.skill } = {}) {
  const item = node("article", `message ${role}`);
  let avatar;
  if (role === "assistant") {
    avatar = mascot(avatarLook, avatarColor);
    if (!working) avatar.dataset.still = "";
    item.append(avatar);
  }
  const body = node("div", "message-body");
  if (skill) body.append(skillChip(skill));
  const text = role === "assistant" && message?.id ? markdown(content, "chat-markdown") : node("p", "", content);
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
  if (message?.source === "voice-call" && role === "assistant") body.append(node("p", "meta", "Voice call"));
  if (message?.remembered?.length) {
    const sources = node("details", "remembered");
    const best = message.remembered[0];
    const via = memoryNames[best.backend];
    const detail = via ? ` · via ${via}${Number.isFinite(best.score) ? ` · ${best.score.toFixed(3)}` : ""}` : "";
    const summary = node("summary", "", `Remembered · ${message.remembered.length}${detail}`);
    const sourceThread = currentThread;
    summary.addEventListener("click", () => avatarSignal(sourceThread, { type: "remembered" }));
    sources.append(summary);
    sources.append(...message.remembered.map((hit) => {
      const caption = Number.isFinite(hit.score) ? ` · ${hit.score.toFixed(3)}` : "";
      return button(memoryLabel(hit) + caption, () => openMemorySource(hit));
    }));
    body.append(sources);
  }
  if (attachments.length) body.append(artifactLibrary.attachmentCards(attachments));
  if (message?.attachment_citations?.length) {
    const sources = node("div", "attachment-sources");
    sources.setAttribute("aria-label", "Attachment sources");
    sources.append(node("span", "", "Sources"));
    for (const id of message.attachment_citations) {
      const file = state?.message_uploads?.[id] || [...turns].flatMap((turn) => turn.attachments || [])
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
    const linked = replyArtifacts(message);
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
    pending: "Awaiting approval", changing: "Interrupted", partial: "Partially applied",
    simulated: "Simulated send", unknown: "Delivery unknown", sending: "Delivery unknown",
    sent: "Sent", complete: action.kind === "gateway" ? "Completed" : "", request_unknown: "Request unconfirmed",
  };
  header.append(node("h4", "", action.title), node("span", "meta", statuses[action.status] || ""));
  card.append(header, node("p", "thread-source", `From ${timelineSource(action)}`));
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
      approveBrowse.disabled = [...turns].some((turn) => turn.approval?.id === action.id && !turn.finished);
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
  const signature = JSON.stringify([entries, currentThread, busy, threadBusy, avatarMode, avatarLook, avatarColor]);
  if (signature === threadSignature) return;
  threadSignature = signature;
  const list = byId("threads");
  const focused = list.contains(document.activeElement) && document.activeElement.dataset.thread;
  avatarThreads.clear();
  list.replaceChildren(...entries.map((thread) => {
    const item = button("", () => {
      mobile.closeDrawer();
      activateThread(thread.id);
      if (view !== "chat") openView("chat");
      else selectThread(thread.id);
    });
    item.className = "thread-link";
    item.dataset.thread = thread.id;
    item.title = thread.title;
    item.append(node("span", "", thread.title));
    if (thread.id === currentThread) item.setAttribute("aria-current", "true");
    if (avatarMode !== "off") {
      const avatar = mascot(avatarLook, avatarColor);
      avatar.dataset.still = "";
      avatarThreads.set(thread.id, avatar);
      item.append(avatar);
    } else if (thread.busy) {
      const dot = node("span", "thread-dot");
      dot.setAttribute("aria-hidden", "true");
      item.append(dot);
    }
    if (thread.busy) item.append(node("span", "visually-hidden", " · Replying"));
    return item;
  }));
  if (focused) [...list.children].find((item) => item.dataset.thread === focused)?.focus();
  const select = byId("thread-select");
  select.replaceChildren(...entries.map((thread) => new Option(thread.busy ? `${thread.title} · Replying` : thread.title, thread.id)));
  select.value = currentThread;
  byId("thread-title").textContent = active?.title || (currentThread === mainThread.id ? "Main" : "Side chat");
  byId("thread-activity").hidden = avatarMode !== "off" || !active?.busy;
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

function renderChat(force = false) {
  renderThreads();
  const actions = new Map((state?.actions || []).map((action) => [action.id, action]));
  const messages = state?.thread_id === currentThread ? state.messages : [];
  const local = [...turns].filter((turn) => turn.threadId === currentThread);
  const thread = threadList.find((item) => item.id === currentThread);
  const remoteBrowse = thread?.activity?.browse;
  const remoteSkill = thread?.activity?.skill;
  const signature = JSON.stringify([currentThread, messages, threadList.map((thread) => thread.title),
    avatarLook, avatarColor, busy,
    state?.message_artifacts, state?.message_uploads, state?.timezone, remoteBrowse, remoteSkill, thread?.skill,
    local.map(({ approval, finished }) => [approval?.id, finished]),
    messages.flatMap((message) => (message.action_ids || []).map((id) => actions.get(id)))]);
  if (!force && signature === chatSignature) return;
  chatSignature = signature;
  const follow = nearBottom();
  const saved = new Set(messages.map((message) => message.id));
  const rows = [];
  const nextRows = new Map();
  byId("welcome").hidden = currentThread !== mainThread.id || !!(messages.length || local.length);
  byId("side-welcome").hidden = currentThread === mainThread.id || !!(messages.length || local.length);
  byId("side-skill").hidden = !thread?.skill;
  byId("side-skill").replaceChildren(...(thread?.skill ? [skillChip(thread.skill, "Skill ready")] : []));
  let previousPrompt;
  for (const [index, stored] of messages.entries()) {
    const message = stored.id ? stored : { ...stored, id: `${currentThread}:${index + 1}` };
    const attachments = (message.attachment_ids || []).map((id) => state?.message_uploads?.[id]).filter(Boolean);
    const cards = [...new Set(message.action_ids || [])].map((id) => actions.get(id)).filter(Boolean);
    const rowSignature = JSON.stringify([currentThread, message, cards, cards.map((action) => threadSource(action)),
      cards.length ? [busy, local.map(({ approval, finished }) => [approval?.id, finished])] : false,
      state?.message_artifacts?.[message.id], attachments, state?.timezone, avatarLook, avatarColor]);
    let row = chatRows.get(message.id);
    if (row?.signature !== rowSignature) {
      let item;
      if (message.role === "call") {
        item = callCard(message);
      } else {
        const bubble = messageBubble(message.role, message.content, { message, prompt: previousPrompt, attachments });
        for (const notice of message.notices || []) bubble.notices.append(node("p", "model-warning", notice));
        for (const action of cards) bubble.cards.append(actionCard(action));
        item = bubble.item;
      }
      row = { item, signature: rowSignature };
    }
    nextRows.set(message.id, row);
    rows.push(row.item);
    if (message.role === "user") previousPrompt = { text: message.content, attachments };
  }
  for (const turn of local) {
    turn.bubble = undefined;
    if (!turn.approval && !saved.has(turn.user?.id)) {
      rows.push(messageBubble("user", turn.user?.content || turn.prompt, {
        message: turn.user, status: turn.user ? undefined : "Queued", attachments: turn.attachments,
      }).item);
    }
    if (saved.has(turn.reply?.id) || (!turn.user && !turn.approval && !turn.error)) continue;
    const content = turn.reply ? turn.reply.content : turn.text || turn.error || (turn.browse ? "" : turnProgress(turn));
    turn.bubble = messageBubble("assistant", content, {
      message: turn.reply, skill: turn.skill, prompt: { text: turn.prompt, attachments: turn.attachments },
      working: !turn.reply && !turn.error && !turn.text && !turn.browse,
    });
    turn.bubble.text.hidden = !content && !!turn.browse;
    rows.push(turn.bubble.item);
    for (const warning of turn.warnings) turn.bubble.notices.append(node("p", "model-warning", warning));
    for (const action of turn.actions.values()) turn.bubble.cards.append(actionCard(actions.get(action.id) || action));
    if (turn.browse) turn.bubble.cards.append(browseCard(turn.browse));
    if (turn.error) {
      if (turn.text) turn.bubble.notices.append(node("p", "model-warning", turn.error));
      const retry = iconButton("retry", "Edit and retry", () =>
        restorePrompt({ text: turn.user?.content || turn.prompt, attachments: turn.attachments }));
      turn.bubble.cards.append(retry);
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
  renderFace(local, messages, actions, remoteBrowse, remoteSkill);
  paintAvatars();
  if (follow) scrollDown();
}

async function refreshState() {
  const request = ++stateRequest;
  const thread = currentThread;
  const headers = stateTag && state?.thread_id === thread ? { "If-None-Match": stateTag } : {};
  const response = await fetch(`/api/state?thread=${encodeURIComponent(thread)}`, {
    headers, signal: AbortSignal.timeout(6000),
  });
  if (response.status === 304) return request === stateRequest && thread === currentThread;
  const next = await readResponse(response);
  if (request !== stateRequest || thread !== currentThread) return false;
  state = next;
  setTimeZone(state.timezone);
  stateTag = response.headers.get("ETag");
  byId("start-call").disabled = typeof state.voice_call_available !== "boolean";
  for (const thread of threadList) {
    const browse = thread.activity?.browse;
    if (browse && state.threads.find((item) => item.id === thread.id)?.activity?.browse?.id !== browse.id) {
      artifactLibrary.endBrowse(browse.id);
    }
  }
  threadList = state.threads;
  renderThreads();
  if (state.thread_id !== currentThread) {
    const deleted = currentThread;
    activateThread(state.thread_id);
    threadDrafts.delete(deleted);
    attachmentDraft.discard(deleted);
    avatarStates.delete(deleted);
    for (const turn of turns) if (turn.threadId === deleted) turns.delete(turn);
  }
  const saved = new Set(state.messages.map((message) => message.id));
  for (const turn of turns) if (saved.has(turn.reply?.id)) turns.delete(turn);
  renderBrain(state);
  paintAvatars();
  if (view === "settings" && settingsSection === "voice") showVoiceEngine();
  return true;
}

function renderBrain({ model, model_id: id }) {
  workspaceModel = model;
  const name = modelNames[model] || connectionState?.providers[model]?.name || model || "Unavailable";
  byId("brain-active-model").textContent = id && model !== "mock" ? `${name} · ${id}` : name;
  renderWorkspaceStatus();
}

function renderWorkspaceStatus() {
  const connectorError = view === "home" ? homeConnectorError : workspaceConnectorError;
  const status = !navigator.onLine ? "Offline" : connectorError ? "Connector error"
    : workspaceModel === "mock" ? "Mock mode" : "";
  for (const label of workspaceStatusLabels) {
    label.textContent = status;
    label.parentElement.hidden = !status;
  }
}

function connectorHasError(entry) {
  return entry.status === "unauthorized" || ["failed", "denied"].includes(entry.test_status)
    || entry.index_state === "Unavailable";
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
  const data = await api("/api/connections");
  if (view === "connections" && !connectionRequest && connectionState === previous &&
      JSON.stringify(data.providers.pinecone) !== JSON.stringify(entry)) {
    applyConnections(data);
  }
}

function memoryLabel(hit) {
  if (hit.artifact_id) return hit.heading || "Artifact";
  return `${hit.message_id ? hit.heading : hit.path} · line ${hit.line}`;
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
    const file = hit?.message_id
      ? await api(`/api/memory/chat?thread=${encodeURIComponent(hit.thread_id)}&message=${encodeURIComponent(hit.message_id)}`)
      : await api(`/api/memory?path=${encodeURIComponent(path)}`);
    if (request !== fileRequest) return;
    byId("file-name").textContent = hit?.message_id ? memoryLabel(file) : file.path;
    const preview = byId("file-content");
    if (hit?.message_id || !hit || !file.content) {
      preview.textContent = file.excerpt || file.content || "This note is empty.";
    } else {
      preview.replaceChildren(...file.content.split(/\r?\n/).map((line, index) => {
        const active = index + 1 >= hit.line && index + 1 <= hit.end_line;
        return node("span", `file-line${active ? " is-highlighted" : ""}`, line || " ");
      }));
      preview.querySelector(".is-highlighted")?.scrollIntoView({ block: "nearest" });
    }
    forget.textContent = hit?.message_id ? "Forget message" : "Forget note";
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
  const path = files.includes(selectedFile) || selectedSource?.message_id ? selectedFile
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
  if (hit.artifact_id) {
    await openView("artifacts");
    return artifactLibrary.open(hit.artifact_id);
  }
  selectedFile = hit.path;
  selectedSource = hit;
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
    const score = hit.backend === "pinecone"
      ? `Score ${hit.score.toFixed(3)} · ${result.reranked ? "Reranked" : "Cosine similarity"}`
      : hit.similarity === null ? `Keyword ${hit.keyword.toFixed(3)}`
        : `Score ${hit.score.toFixed(3)} · Similarity ${hit.similarity.toFixed(3)} · Keyword ${hit.keyword.toFixed(3)}`;
    article.append(open, node("p", "meta", score), node("p", "", hit.excerpt));
    if (allowForget && !hit.artifact_id) {
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
  const check = connectorHasError(entry) ? "error"
    : entry.index_state === "Ready" ? "ready" : entry.index_state === "Connecting" ? "checking"
      : entry.test_status === "passed" ? "ok" : entry.test_status ? "error" : "untested";
  const status = configured ? check : entry.status;
  const labels = {
    ok: "OK", ready: "Ready", checking: "Checking", error: "Error", untested: "Untested", unauthorized: "Found but not authorized",
    not_set_up: "Not set up", unknown: "Not checked",
  };
  const heading = node("div", "card-header");
  const tone = status === "ready" ? "ok" : status === "checking" ? "untested" : status;
  heading.append(node("h4", "", entry.name), node("span", `connection-status ${tone}`, labels[status]));
  card.append(heading);
  if (entry.auth) card.append(node("p", "meta", entry.auth));
  card.append(node("p", "connection-description", entry.description));
  if (configured) {
    const uses = node("p", "connection-uses");
    uses.append(node("strong", "", "Used for"), ` ${entry.uses.join(" · ")}`);
    card.append(uses);
  }
  if (Object.hasOwn(connectorSettings, provider)) card.append(connectorForm(provider, entry, connectorSettings[provider]));
  if (entry.index_error) card.append(node("p", "connection-test failed", entry.index_error));
  else if (entry.test_detail) card.append(node("p", `connection-test ${entry.test_status}`, entry.test_detail));

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

function artifactHash(filter = "all") {
  return filter === "all" ? "#artifacts" : `#artifacts/${filter}`;
}

function selectArtifactFilter(filter) {
  if (location.hash !== artifactHash(filter)) history.pushState(history.state, "", artifactHash(filter));
  artifactLibrary.selectFormat(filter);
}

function syncWorkspaceRoute() {
  if (isConnectionsRoute()) {
    const tab = tabFromHash();
    if (tab) rememberConnectionTab(tab);
    if (view === "connections") renderConnections();
    else openView("connections", false);
  } else if (artifactFilterFromHash(location.hash)) {
    const filter = artifactFilterFromHash(location.hash);
    if (location.hash === "#pages") history.replaceState(history.state, "", artifactHash(filter));
    if (view === "artifacts") artifactLibrary.selectFormat(filter);
    else openView("artifacts", false);
  } else if (location.hash === timelineErrorRoute) {
    openView("timeline", false);
  } else if (view === "connections" || view === "artifacts" || view === "timeline") {
    openView(history.state?.hearthView || "home", false);
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
      const data = await api(`/api/connections/${operation}`, body);
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
          applyConnections(await api("/api/connections"));
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
  const stores = choice.backend === "huggingface" ? ["auto", "pinecone", "local", "huggingface"]
    : ["auto", "pinecone", "local"];
  settingOptions(byId("memory-backend"), stores.map((value) => [value, memoryNames[value]]),
    choice.backend === "keyword" ? "local" : choice.backend);
  settingOptions(byId("memory-model"), Object.entries(info.models), choice.model);
  settingOptions(byId("memory-test-kind"), [["", "All kinds"], ...info.kinds.map((kind) =>
    [kind, kind[0].toUpperCase() + kind.slice(1)])], byId("memory-test-kind").value);
  settingOptions(byId("memory-test-thread"), [["", "All threads"], ...(state?.threads || []).map((thread) =>
    [thread.id, thread.title])], byId("memory-test-thread").value);
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
      : button("Connect in Connections", () => openView("connections")));
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
        : "No selected provider is connected. Connect in Connections.";
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
    status.textContent = pinecone.connected ? "Ready to sync memories." : "Connect Pinecone in Connections.";
  }

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
    include_chat: byId("memory-chat-history").checked, auto_remember: byId("memory-remember").value,
    include: scope("include"), exclude: scope("exclude") };
}

function expandSetting(section) {
  expandedSetting = section;
  for (const [key, disclosure] of settingsDisclosures) {
    disclosure.setAttribute("aria-expanded", String(key === section));
  }
  if (mobile.isMobile()) settingsDisclosures.get(section)?.scrollIntoView({ block: "nearest" });
}

async function openSettings(section, expand = true) {
  settingsSection = section;
  if (expand) expandSetting(section);
  clearTimeout(reindexPoll);
  for (const item of settingsTabs) {
    const active = item.dataset.settings === section;
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
    byId(`settings-${item.dataset.settings}`).hidden = !active;
  }
  if (section === "brain") return openBrainSettings();
  if (section === "appearance") return;
  if (section === "artifacts") return artifactLibrary.settings();
  if (section === "home") return homePage.settings();
  if (section === "approvals") return automation.settings();
  if (section === "reminders") return delivery.settings();
  if (section === "voice") {
    syncVoiceSettings();
    return voiceCall.syncSettings();
  }
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

async function refreshView() {
  if (view === "skills") return skills.load();
  if (view === "home") return homePage.load();
  if (view === "timeline") return timeline.show();
  if (view === "artifacts") return artifactLibrary.show();
  if (view === "reminders") return automation.tasksActive() ? automation.loadTasks() : delivery.reminders();
  if (view === "inbox") return delivery.inbox();
  if (!await refreshState()) return;
  if (view === "chat") renderChat();
  else if (view === "memory") await renderMemory();
}

async function openView(nextView, updateHistory = true) {
  const previousView = view;
  mobile.closeDrawer();
  if (nextView !== "chat") voice.cancel();
  if (updateHistory) {
    const routedView = isConnectionsRoute() ? "connections" : artifactFilterFromHash(location.hash) ? "artifacts"
      : location.hash === timelineErrorRoute ? "timeline" : null;
    const hash = nextView === "connections" ? connectionHash() : nextView === "artifacts" ? artifactHash() : null;
    if (hash && nextView !== routedView) {
      if (!routedView) history.replaceState({ ...history.state, hearthView: view }, "");
      history.pushState(null, "", hash);
    } else if (!hash && routedView) {
      history.pushState({ hearthView: nextView }, "", location.pathname + location.search);
    }
  }
  if (view === "timeline" && nextView !== view) timeline.hide();
  view = nextView;
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
  paintAvatars();
  renderWorkspaceStatus();
  if (view === "timeline") timeline.setTodayErrors(location.hash === timelineErrorRoute);
  if (view === "connections") {
    renderConnections();
    const mailCard = delivery.connections();
    await updateConnections("rescan");
    await mailCard;
    delivery.poll();
  } else if (view === "settings") {
    await openSettings(settingsSection, false);
  } else if (view === "home") {
    if (previousView !== "home") byId("home-view").scrollTop = 0;
    await homePage.load();
  } else if (view === "artifacts") {
    artifactLibrary.selectFormat(artifactFilterFromHash(location.hash) || "all");
    await artifactLibrary.show();
  } else if (view === "skills") {
    await skills.load();
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

async function openWeatherSettings() {
  settingsSection = "home";
  await openView("settings");
  expandSetting("home");
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

async function openArtifactThread(threadId, messageId) {
  activateThread(threadId);
  await openView("chat");
  const message = [...transcript.querySelectorAll("[data-message-id]")].find((item) => item.dataset.messageId === messageId);
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

function turnProgress(turn) {
  return turn.activity ? `${turn.activity}…` : "Thinking…";
}

function readChatEvent(turn, name, payload) {
  if (name === "queued") {
    turn.threadId = payload.thread.id;
    turn.prompt = payload.prompt;
    if (payload.attachments) turn.attachments = payload.attachments;
    avatarSignal(turn.threadId, { type: "queued" });
    rememberThread(payload.thread);
    if (turn.command && turn.selection === selectionVersion) {
      activateThread(turn.threadId);
      if (view === "chat") input.focus();
    }
  } else if (name === "started") {
    turn.user = payload.message;
    rememberThread(payload.thread);
    avatarSignal(turn.threadId, { type: "started" });
  } else if (name === "token" || name === "reset") {
    const follow = turn.threadId === currentThread && nearBottom();
    turn.text = name === "reset" ? "" : turn.text + payload.text;
    avatarSignal(turn.threadId, { type: name, text: payload.text });
    if (turn.bubble) {
      turn.bubble.text.textContent = turn.text || turnProgress(turn);
      turn.bubble.text.parentElement.classList.toggle("message-working", !turn.text);
    }
    if (avatarMode === "face" && turn.threadId === currentThread) updateFaceCaption(turn.text);
    if (follow) scrollDown();
    return;
  } else if (name === "action") {
    turn.actions.set(payload.id, payload);
    if (payload.kind === "reminder") {
      avatarSignal(turn.threadId, { type: "reminder", until: Date.parse(payload.job.next_at) });
    } else if (payload.status === "complete" && ["memory", "remember"].includes(payload.kind)) {
      avatarSignal(turn.threadId, { type: "celebrate" });
    }
  } else if (name === "model_warning") {
    turn.warnings.push(payload.message);
    avatarSignal(turn.threadId, { type: "warning" });
  } else if (name === "done") {
    turn.reply = payload.message;
    avatarSignal(turn.threadId, { type: "done", remembered: !!turn.reply.remembered?.length });
  } else if (name === "skill_loaded") {
    turn.skill = payload;
  } else if (name === "error") {
    throw new Error(payload.message);
  } else if (name === "browse_active") {
    turn.browse = payload;
    avatarSignal(turn.threadId, { type: "tool_started", title: `Browsing ${payload.domain}` });
  } else if (name === "browse_finished") {
    turn.browse = undefined;
    artifactLibrary.endBrowse(payload.id);
    avatarSignal(turn.threadId, { type: "tool_finished" });
  } else if (name === "browse_approved") {
    turn.activity = "Starting approved browser action";
  } else if (name === "tool_started" || name === "tool_finished" || name === "demo_listening") {
    turn.activity = payload.title;
    if (turn.bubble && !turn.text) updateText(turn.bubble.text, turnProgress(turn));
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

async function chat(prompt, { keepDraft = false, approval } = {}) {
  prompt = prompt.trim();
  if (busy || (approval && [...turns].some((turn) => turn.approval?.id === approval.id && !turn.finished))) return;
  const attachments = keepDraft || approval ? [] : attachmentDraft.selected();
  if (!attachments || (!prompt && !approval && !attachments.length)) return;
  voice.cancel();
  const source = approval?.thread_id || currentThread;
  const command = !attachments.length && source === mainThread.id && /^\/(side|btw)(?:\s|$)/i.test(prompt);
  const turn = { threadId: command ? undefined : source, selection: selectionVersion, command,
    prompt, approval, attachments, text: "", warnings: [], actions: new Map() };
  for (const previous of turns) if (previous.threadId === source && previous.error) turns.delete(previous);
  turns.add(turn);
  showNotice();
  if (!keepDraft) {
    input.value = "";
    attachmentDraft.discard(source);
  }
  resizeInput();
  renderChat(true);
  scrollDown();
  try {
    await connectionRequest;
    const response = await fetch(approval ? "/api/browse/approve" : "/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(approval ? { id: approval.id, thread_id: source } : { message: prompt, thread_id: source, attachment_ids: attachments.map((item) => item.id) }),
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
    avatarSignal(turn.threadId || source, { type: "error" });
    if (!turn.user) {
      turns.delete(turn);
      if (!keepDraft) attachmentDraft.restore(source, attachments);
      if (source === currentThread && !input.value) {
        input.value = prompt;
        resizeInput();
      }
    }
    if ((turn.threadId || source) === currentThread) showNotice(error.message);
  } finally {
    artifactLibrary.endBrowse(turn.browse?.id);
    turn.browse = undefined;
    turn.finished = true;
    if (turn.threadId === currentThread || !turn.threadId) renderChat(true);
    else {
      // The server saves completed replies before emitting done.
      if (turn.reply) turns.delete(turn);
      renderThreads();
    }
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
  if (action.job || action.inbox_id || action.undo_task) {
    if (busy) return;
    setBusy(true);
    try {
      await api(action.inbox_id ? "/api/inbox/undo" : "/api/undo", { id: action.inbox_id || action.id });
      await refreshView();
      showNotice(action.inbox_id ? "Email acceptance undone." : action.undo_task ? "Task restored." : "Reminder canceled.");
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
  if (action.kind === "page" || action.kind === "skill") {
    if (busy || (action.kind === "skill" && !confirmed && !window.confirm("Undo this skill change?"))) return;
    setBusy(true);
    try {
      await api("/api/undo", { id: action.id });
      await refreshView();
      showNotice(action.kind === "skill" ? "Skill change undone." : "Page change undone.");
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
        if (!await refreshState()) continue;
      } catch {
        continue;
      }
      if (state.restore?.action_id === action.id && state.restore.status === "failed") {
        throw new Error("The checkpoint could not be restored.");
      }
      if (!state.actions.some((item) => item.id === action.id && item.checkpoint?.id === action.checkpoint.id)) {
        timeline.restored(action, timelineTitle);
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
byId("call-connections").addEventListener("click", () => openView("connections"));
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
  chat(input.value);
});
byId("voice-cancel").addEventListener("click", () => {
  voice.cancel();
  byId("mic").focus({ preventScroll: true });
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
byId("forget-file").addEventListener("click", () => {
  if (selectedFile) forgetMemory(selectedSource || { path: selectedFile });
});
for (const tab of settingsTabs) {
  const section = tab.dataset.settings;
  const panel = byId(`settings-${section}`);
  tab.addEventListener("click", () => openSettings(section));
  const disclosure = button(tab.textContent, () => {
    if (expandedSetting === section) expandSetting();
    else openSettings(section);
  });
  disclosure.className = "settings-disclosure";
  disclosure.setAttribute("aria-controls", panel.id);
  disclosure.setAttribute("aria-expanded", "false");
  settingsDisclosures.set(section, disclosure);
  const heading = node("h2", "mobile-only settings-heading");
  heading.append(disclosure);
  byId("settings-sections").append(heading, panel);
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
  if (!document.hidden && (["home", "timeline", "reminders", "inbox"].includes(view) || (view === "chat" && !busy))) {
    refreshView().catch((error) => showNotice(error.message));
  }
});
let polling = false;
window.addEventListener("offline", renderWorkspaceStatus);
window.addEventListener("online", renderWorkspaceStatus);
setInterval(async () => {
  if (!["chat", "reminders", "connections", "home", "inbox"].includes(view) || busy || threadBusy || document.hidden || polling) return;
  polling = true;
  try {
    if (view === "connections") await refreshPineconeHealth();
    else await refreshView();
  } catch {
    // Leave the current view intact during a transient connection failure.
  } finally {
    polling = false;
  }
}, 3_000);
setInterval(() => { if (!document.hidden) delivery.poll(); }, 60_000);
applyAppearance();
renderWorkspaceStatus();
if (isConnectionsRoute() || artifactFilterFromHash(location.hash) || location.hash === timelineErrorRoute) syncWorkspaceRoute();
else openView(requestedThread ? "chat" : "home", false);
if (!document.hidden) delivery.poll();
if (!isConnectionsRoute()) updateConnections("rescan");
