import { render } from "preact";
import { html } from "./view.js";
import { avatarEvent, avatarPose, newAvatar } from "../avatar-state.js";
import { announcePose, looks, mascot, poseLabel, setLook, setPose } from "../avatar.js";
import { createVoiceInput } from "../voice.js";
import { mountAppearance, readAppearance, createVoiceSettings, readVoiceSettings } from "../settings/persona.js";
import { createVoiceCall } from "../voice-call.js";
import { fileAnswerSources } from "../file-questions.js";
import { ChannelChip } from "../reminders/view.js";
import { button, node, updateText } from "../dom.js";
import { arrive, prepareListMotion, showLoading } from "../motion.js";
import { setupMobile } from "../mobile.js";
import { createThreadMenu } from "../thread-menu.js";
import { createChatSearch } from "./search.js";
import { createAttachments } from "../attachments.js";
import { icon, iconButton } from "../icons.js";
import { setTimeZone, timeFormatter } from "../time.js";
import { skillChip } from "../skills/workspace.js";
import { createWorkersCard } from "../workers.js";
import { conversationView, newConversation, reconcile } from "../chat-state.js";
import { createSSEParser } from "../sse.js";
import { updateCard } from "../self-update.js";
import { createStore } from "../store.js";
import { renderConversation } from "./conversation.js";
import { mountComposer } from "./composer.js";
import { mountThreads, renderThreadMenu } from "./threads.js";

export const mainThread = { id: "main", title: "Main", busy: false };

export function createChatWorkspace({
  requestedThread, byId, api, trackRefresh, readResponse, showNotice, showConnectionGuidance, date,
  currentView, currentSettings, getConnections, getConnectionRequest, openView, refreshView,
  getArtifacts, onThreadsChanged, renderBrain, schedulePoll, approvalCard, approve, undo, gatewayResults,
  memoryLabel, openMemorySource, stopWorkers, openVoiceAction, openConnections,
}) {
  const store = createStore({
    currentThread: requestedThread || sessionStorage.getItem("hearth-thread") || mainThread.id,
    threads: [mainThread], threadEntries: [mainThread], busy: false, uploading: false,
    sendLabel: "Send message", canStop: false, stoppingReply: false, callActive: false,
    dictation: { phase: "idle", interim: "" }, ...readAppearance(), ...readVoiceSettings(),
  });
  mountComposer(byId("composer"), store, {
    onSend: chat, onStop: stopActiveReply, onAttach: () => attachmentDraft.pick(),
    onInput() { resizeInput(); followComposer(); },
    onSelect() { if (Date.now() < avatarStates.get(store.state.currentThread)?.typing) followComposer(); },
    onMic: () => voice.active ? voice.stop() : startVoice(),
    onCancelVoice() { voice.cancel(); byId("mic").focus({ preventScroll: true }); },
  });
  const transcript = byId("transcript");
  const input = byId("message");
  const stopReply = byId("stop-reply");
  const replyStatus = byId("reply-status");
  const chatScroll = byId("chat-scroll");
  const threadMenu = byId("thread-menu");
  const threadActions = createThreadMenu(threadMenu);
  const mobile = setupMobile({
    nearBottom, scrollDown, refreshThreads: refreshDrawerThreads, closeThreadMenu: threadActions.close,
  });
  const messageTime = timeFormatter({ hour: "numeric", minute: "2-digit" });
  const threadDrafts = new Map();
  let conversation = newConversation(store.state.currentThread);
  const localTurns = () => [...conversation.turns.values()];
  const turnBubbles = new Map();
  const stopping = new Set();
  let chatNoticeTurn;
  let sendingTestReminder = false;
  let selectionVersion = 0;
  let stateRequest = 0;
  let threadSignature;
  let threadListReady = false;
  let seenReplies;
  try {
    seenReplies = new Map(JSON.parse(localStorage.getItem("hearth-seen-replies") || "[]"));
  } catch {
    seenReplies = new Map();
  }
  let chatSignature;
  let chatRows = new Map();
  let nextRowKey = 0;
  let chatMotion;
  const workerCards = new Map();
  let threadBusy = false;
  syncThreadMenu();
  let serverState;
  let stateTag;
  let stateVariant;
  let olderRequest;
  let historyRefresh;
  let aroundMessage;
  let windowRequest;
  let searchHit;
  let searchHitTimer;
  let sidebarRequest;
  let sidebarTail = [];
  const chatSearch = createChatSearch({
    api, thread: () => store.state.currentThread, jump: openChatSearchResult, reveal: revealChatSearchResult,
    prepareFind: () => { if (store.state.avatarMode === "face") chooseAvatarMode("beside"); },
  });
  const attachmentDraft = createAttachments({
    thread: () => store.state.currentThread, isChat: () => currentView() === "chat", isBusy: () => store.state.busy,
    onChange(pending) {
      const follow = nearBottom();
      store.update({ uploading: pending });
      if (follow) scrollDown();
    },
  });
  const faceWorkers = createWorkersCard({ stop: stopWorkers });
  mountThreads({
    store, list: byId("threads"), select: byId("thread-select"), avatarSelect: byId("avatar-view"),
    onSelect: openThreadFromList, openMenu: openThreadMenu, menuId: threadMenu.id, onAvatarChange: chooseAvatarMode,
  });
  const avatarStates = new Map();
  const headerMascot = mascot(store.state.avatarLook, store.state.avatarColor);
  const portraitMascot = mascot(store.state.avatarLook, store.state.avatarColor);
  byId("avatar-header").append(headerMascot);
  byId("avatar-portrait").append(portraitMascot);
  mountAppearance(byId("settings-appearance"), store, {
    onMode: chooseAvatarMode, applyAppearance,
    onFace() {
      openView("chat");
      byId("avatar-view").focus();
    },
  });
  const voiceSettings = createVoiceSettings({ store, byId, api, date, openConnections, whisperConnected });
  const voiceLevel = byId("voice-level");
  let spaceHeld = false;
  const voice = createVoiceInput({
    update: updateVoice,
    meter: (level) => { voiceLevel.value = level; },
    deliver: fillFromVoice,
  });
  const voiceCall = createVoiceCall({
    api,
    getPreferences: () => store.state.callPreferences,
    getThread: () => ({ id: store.state.currentThread, title: threadSource({ thread_id: store.state.currentThread }) }),
    isConfigured: () => serverState?.voice_call_available,
    prepare: () => {
      if (store.state.busy) return false;
      voice.cancel();
      spaceHeld = false;
      return true;
    },
    makeMascot: () => store.state.avatarMode === "off" ? null : mascot(store.state.avatarLook, store.state.avatarColor),
    update: (_, refresh) => {
      store.update({ callActive: voiceCall.inProgress });
      paintAvatars();
      if (refresh) refreshView().catch((error) => showNotice(error.message));
      if (currentView() === "settings" && currentSettings() === "voice" && !voiceCall.inProgress) voiceSettings.refreshCall();
    },
    onAction: openVoiceAction,
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

  function paintAvatars() {
    if (currentView() !== "chat" || store.state.avatarMode === "off") return;
    const now = Date.now();
    const active = store.state.threads.find((thread) => thread.id === store.state.currentThread) || { id: store.state.currentThread };
    const current = threadPose(active, now);
    setPose(store.state.avatarMode === "face" ? portraitMascot : headerMascot, current);
    updateText(byId("avatar-caption"), current.pose === "idle" ? "" : poseLabel(current));
    byId("avatar-caption").hidden = current.pose === "idle";
    updateText(byId("face-status"), poseLabel(current));
    updateText(byId("avatar-status"), announcePose(current));
    for (const turn of conversation.turns.values()) {
      const bubble = turnBubbles.get(turn.key);
      if (turn.threadId === store.state.currentThread && bubble?.avatar && !turn.finished) {
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

  function replyArtifacts(message, linkedArtifacts = serverState?.message_artifacts?.[message?.id]) {
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
    if (store.state.avatarMode !== "face") return;
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
    if (linked.length) details.querySelector(".cards").append(getArtifacts().chatActions(linked));
    if (screenshots?.length) details.querySelector(".cards").append(...screenshots.map(browseScreenshot));
  }

  function applyAppearance() {
    const hidden = store.state.avatarMode === "off";
    const full = store.state.avatarMode === "face";
    byId("avatar-header").hidden = hidden;
    byId("face-stage").hidden = !full;
    byId("chat-view").classList.toggle("avatar-off", hidden);
    byId("chat-view").classList.toggle("face-view", full);
    mobile.placeCallControls();
    if (hidden) {
      byId("avatar-caption").hidden = true;
      updateText(byId("avatar-status"), "");
    }
    setLook(headerMascot, store.state.avatarLook, store.state.avatarColor);
    setLook(portraitMascot, store.state.avatarLook, store.state.avatarColor);
    updateText(byId("avatar-name"), looks[store.state.avatarLook].name);
    renderChat(true);
  }

  function chooseAvatarMode(mode) {
    const leavingFace = store.state.avatarMode === "face" && mode !== "face";
    if (mode === "face") mobile.closeDrawer();
    store.update({ avatarMode: mode });
    localStorage.setItem("hearth-avatar-view", mode);
    applyAppearance();
    if (leavingFace && mobile.isMobile() && currentView() === "chat") byId("open-menu").focus();
  }

  function whisperConnected() {
    const connection = getConnections()?.providers?.huggingface?.status;
    return connection === "connected" || (connection == null && serverState?.whisper_available === true);
  }

  function updateVoice({ thread, phase, interim = "", engine, message }) {
    const recording = phase === "recording";
    const processing = phase === "processing";
    const previous = store.state.dictation.phase;
    const follow = previous !== phase && nearBottom();
    if (previous !== phase) {
      if (recording || previous === "recording") avatarSignal(thread, { type: "recording", active: recording });
      if (processing || previous === "processing") avatarSignal(thread, { type: "voice_processing", active: processing });
    }
    store.update({ dictation: { phase, engine, interim, held: spaceHeld } });
    if (!recording) voiceLevel.value = 0;
    if (follow) scrollDown();
    if (message) showNotice(message);
  }

  function fillFromVoice({ thread, text, autoSend }) {
    if (thread !== store.state.currentThread || currentView() !== "chat") return;
    if (autoSend && !store.state.busy) {
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
    if (currentView() !== "chat" || store.state.busy || voiceCall.inProgress) return;
    showNotice();
    voice.start(store.state.currentThread, store.state.voicePreferences, whisperConnected());
  }

  function scrollDown() {
    chatScroll.scrollTop = chatScroll.scrollHeight;
  }

  function nearBottom() {
    return chatScroll.scrollHeight - chatScroll.scrollTop - chatScroll.clientHeight < 65;
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
    arrive([toast]);
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
    attachmentDraft.restore(store.state.currentThread, prompt.attachments);
    resizeInput();
    input.focus();
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
    const threadId = store.state.currentThread;
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

  const messageActions = {
    votes: messageVotes, copy: copyMessage, restore: restorePrompt, date, bindMenu: bindMessageMenu,
    time: (value) => messageTime.format(new Date(value)),
    showError: showConnectionGuidance, checkCollapsed: checkCollapsedReplies, scrollDown,
    isVisible: () => currentView() === "chat",
  };

  function messageRow(role, content, { message, status, prompt, working, streaming = working, attachments = [],
    skill = message?.skill, linkedArtifacts, uploadMetadata = serverState?.message_uploads, warnings = [], error, errorInNotice } = {}) {
    const extras = [];
    if (message?.file_answer) extras.push(fileAnswerSources(message.file_answer));
    if (message?.source === "voice-call" && role === "assistant") extras.push(node("p", "meta", "Voice call"));
    if (message?.remembered?.length) {
      const sources = node("details", "remembered");
      const count = message.remembered.length;
      const summary = node("summary", "", `${count} memory ${count === 1 ? "source" : "sources"}`);
      const sourceThread = store.state.currentThread;
      summary.addEventListener("click", () => avatarSignal(sourceThread, { type: "remembered" }));
      sources.append(summary);
      sources.append(...message.remembered.map((hit) =>
        button(memoryLabel(hit), () => openMemorySource(hit))));
      extras.push(sources);
    }
    if (attachments.length) extras.push(getArtifacts().attachmentCards(attachments));
    if (message?.attachment_citations?.length) {
      const sources = node("div", "attachment-sources");
      sources.setAttribute("aria-label", "Attachment sources");
      sources.append(node("span", "", "Sources"));
      for (const id of message.attachment_citations) {
        const file = uploadMetadata?.[id] || localTurns().flatMap((turn) => turn.attachments || [])
          .find((item) => item.id === id);
        if (!file) continue;
        const source = button("", (event) => getArtifacts().openAttachment(file, event.currentTarget));
        source.setAttribute("aria-haspopup", "dialog");
        source.title = file.filename;
        source.append(icon("paperclip", 14), node("span", "", file.filename));
        sources.append(source);
      }
      if (sources.childElementCount > 1) extras.push(sources);
    }
    if (role === "assistant" && message?.id) {
      const linked = replyArtifacts(message, linkedArtifacts);
      if (linked.length) extras.push(getArtifacts().chatActions(linked));
      if (message.browse_images?.length) extras.push(...message.browse_images.map(browseScreenshot));
    }
    const row = {
      key: nextRowKey++, role, content, message, status, prompt, streaming, working, extras, warnings, error, errorInNotice,
      skill: skill && skillChip(skill), avatarLook: store.state.avatarLook, avatarColor: store.state.avatarColor,
      cards: [],
      bindItem(item) { row.item = item; },
      bindCards(element) { row.cardsElement = element; },
    };
    return row;
  }

  function threadSource(item, fallback = "Main") {
    return store.state.threads.find((thread) => thread.id === item.thread_id)?.title || item.thread_title || fallback;
  }

  function timelineSource(item) {
    const name = threadSource(item);
    return item.source === "voice-call" ? `${name} · Voice call` : name;
  }

  function browseScreenshot(image) {
    const open = button("", (event) => getArtifacts().openBrowse(image, event.currentTarget));
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
      const watch = button("Watch live", (event) => getArtifacts().openBrowse(browse, event.currentTarget));
      watch.setAttribute("aria-haspopup", "dialog");
      card.append(watch);
    }
    return card;
  }

  function actionCard(action) {
    if (action.tool) return approvalCard(action);
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
      render(html`<${ChannelChip} channel=${action.job.channel} />`, chip);
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
    for (const item of card.querySelectorAll("button")) item.disabled = store.state.busy;
    return card;
  }

  function isWorking(thread) {
    return thread?.busy || localTurns().some((turn) => turn.threadId === thread?.id && !turn.finished);
  }

  const summarySheet = byId("thread-summary");
  let threadMenuId;
  let summaryThread;

  function syncThreadMenu(thread) {
    renderThreadMenu(threadMenu, thread, thread?.id === mainThread.id, store.state.busy || threadBusy);
  }

  function openThreadMenu(thread, trigger, options) {
    threadMenuId = thread.id;
    syncThreadMenu(thread);
    threadActions.open(trigger, options);
  }

  function isSendingReminder(threadId) {
    return serverState?.reminder_sending?.includes(threadId) || (threadId === mainThread.id && sendingTestReminder);
  }

  function markSeenReplies() {
    if (!serverState) return;
    let changed = false;
    for (const thread of store.state.threads) {
      const canRead = currentView() === "chat" && !document.hidden && !byId("workspace-drawer").open
        && !aroundMessage && serverState.thread_id === thread.id && store.state.currentThread === thread.id;
      if ((!seenReplies.has(thread.id) || canRead) && seenReplies.get(thread.id) !== thread.last_reply) {
        seenReplies.set(thread.id, thread.last_reply);
        changed = true;
      }
    }
    if (changed) localStorage.setItem("hearth-seen-replies", JSON.stringify([...seenReplies]));
  }

  function renderThreads() {
    const entries = store.state.threads.map((thread) => {
      const working = isWorking(thread);
      const unread = thread.last_reply && seenReplies.get(thread.id) !== thread.last_reply;
      const status = isSendingReminder(thread.id) ? "Sending reminder"
        : working ? "Working" : unread ? "Unread reply" : "";
      return { ...thread, busy: working, status };
    });
    const active = entries.find((item) => item.id === store.state.currentThread);
    const signature = JSON.stringify([entries, store.state.currentThread, store.state.busy, threadBusy, store.state.avatarMode]);
    if (signature === threadSignature) return;
    threadSignature = signature;
    const list = byId("threads");
    const play = threadListReady ? prepareListMotion(list, entries.map((thread) => thread.id)) : undefined;
    const focused = list.contains(document.activeElement) ? document.activeElement : null;
    updateText(byId("thread-list-status"), entries.filter((thread) => thread.status)
      .map((thread) => `${thread.title}: ${thread.status}`).join(". "));
    store.update({ threadEntries: entries });
    play?.();
    if (focused && !focused.isConnected) list.querySelector('[aria-current="true"]')?.focus({ preventScroll: true });
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
    byId("thread-title").textContent = active?.title || (store.state.currentThread === mainThread.id ? "Main" : "Side chat");
    const activity = byId("thread-activity");
    activity.hidden = store.state.avatarMode !== "off" || !active?.status || active.status === "Unread reply";
    updateText(activity, active?.status || "");
    byId("thread-controls").hidden = !active || active.id === mainThread.id;
    byId("new-thread").disabled = store.state.busy || threadBusy;
    byId("rename-thread").disabled = store.state.busy || threadBusy;
    const remove = byId("delete-thread");
    remove.disabled = store.state.busy || threadBusy || !!active?.busy;
    remove.title = active?.busy ? "Wait for this chat to finish" : "Delete this side chat";
    store.update({ sendLabel: active?.busy ? "Queue follow-up" : "Send message" });
    paintAvatars();
  }

  function openThreadFromList(id) {
    if (currentView() !== "chat") {
      activateThread(id);
      openView("chat");
    } else {
      const fromDrawer = mobile.closeDrawer({ restoreFocus: false });
      selectThread(id);
      if (fromDrawer) byId("thread-title").focus({ preventScroll: true });
    }
  }

  function rememberThread(thread) {
    const entries = store.state.threads.slice();
    const index = entries.findIndex((item) => item.id === thread.id);
    if (index < 0) entries.push(thread);
    else entries[index] = { ...entries[index], ...thread };
    store.update({ threads: entries });
  }

  function workersCard(workers) {
    const turnId = workers[0].turn_id;
    if (!workerCards.has(turnId)) workerCards.set(turnId, createWorkersCard({ stop: stopWorkers }));
    const widget = workerCards.get(turnId);
    widget.update(workers);
    return widget.card;
  }

  const activeReply = () => localTurns().find((turn) =>
    turn.threadId === store.state.currentThread && turn.id && !turn.finished && !turn.reply && !turn.stopped);

  function updateStopReply() {
    const turn = activeReply();
    if (!turn && document.activeElement === stopReply) input.focus({ preventScroll: true });
    store.update({ canStop: !!turn, stoppingReply: stopping.has(turn?.key) });
  }

  async function stopActiveReply() {
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
  }

  function updateConversation(update) {
    const result = reconcile(conversation, update);
    const changed = conversation !== result.state;
    conversation = result.state;
    const announcements = [];
    for (const { turn, reply } of result.completed) {
      if (update.type !== "stream") {
        getArtifacts().endBrowse(turn.browse?.id);
        avatarSignal(turn.threadId, { type: "done", remembered: !!reply.remembered?.length });
      }
      if (chatNoticeTurn === turn.key) {
        showNotice();
      }
      if (turn.threadId === store.state.currentThread && currentView() === "chat" && !byId("workspace-drawer").open) {
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
    const { transcript: history, local: pending } = conversationView(conversation);
    const local = conversation.snapshot?.around ? [] : pending;
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
    const thread = store.state.threads.find((item) => item.id === store.state.currentThread);
    const remoteBrowse = thread?.activity?.browse;
    const remoteSkill = thread?.activity?.skill;
    const signature = JSON.stringify([store.state.currentThread, messages, store.state.threads.map((thread) => thread.title),
      store.state.avatarLook, store.state.avatarColor, store.state.busy,
      history.message_artifacts, history.message_uploads, history.self_updates, serverState?.timezone, history.workers, remoteBrowse, remoteSkill, thread?.skill,
      local.map(({ user, reply, approval, finished }) => [user?.id, reply?.id, approval?.id, finished]),
      messages.flatMap((message) => (message.action_ids || []).map((id) => actions.get(id)))]);
    if (!force && signature === chatSignature) return;
    chatSignature = signature;
    const follow = !preserveScroll && nearBottom();
    const previousMotion = chatMotion?.thread === store.state.currentThread ? chatMotion : undefined;
    const arrivals = [];
    const live = currentView() === "chat" && previousMotion && !preserveScroll && !conversation.snapshot?.around;
    const tail = previousMotion?.last ? messages.findIndex((message) => message.id === previousMotion.last) + 1 : 0;
    const newHistory = live && previousMotion.loaded && (!previousMotion.last || tail > 0);
    const optimistic = newHistory && new Set([...local, ...previousMotion.turns.values()]
      .flatMap((turn) => [turn.user?.id, turn.reply?.id].filter(Boolean)));
    chatMotion = { thread: store.state.currentThread, loaded: !!conversation.snapshot,
      last: messages.at(-1)?.id, turns: new Map(local.map((turn) => [turn.key, turn])) };
    turnBubbles.clear();
    const rows = [];
    const nextRows = new Map();
    byId("welcome").hidden = store.state.currentThread !== mainThread.id || !!(messages.length || local.length);
    byId("side-welcome").hidden = store.state.currentThread === mainThread.id || !!(messages.length || local.length);
    byId("side-skill").hidden = !thread?.skill;
    byId("side-skill").replaceChildren(...(thread?.skill ? [skillChip(thread.skill, "Skill ready")] : []));
    const context = history.previous_prompt;
    let previousPrompt = context ? { text: context.content,
      attachments: context.attachment_ids.map((id) => history.message_uploads?.[id]).filter(Boolean) } : undefined;
    for (const [index, stored] of messages.entries()) {
      const message = stored.id ? stored : { ...stored, id: `${store.state.currentThread}:${index + 1}` };
      const attachments = (message.attachment_ids || []).map((id) => history.message_uploads?.[id]).filter(Boolean);
      const cards = [...new Set(message.action_ids || [])].map((id) => actions.get(id)).filter(Boolean);
      const rowSignature = JSON.stringify([store.state.currentThread, message, cards, cards.map((action) => threadSource(action)),
        cards.length ? [store.state.busy, local.map(({ approval, finished }) => [approval?.id, finished])] : false,
        history.message_artifacts?.[message.id], attachments, serverState?.timezone, store.state.avatarLook, store.state.avatarColor,
        message.attachment_citations?.map((id) => history.message_uploads?.[id]),
        message.role === "assistant" ? previousPrompt : null]);
      let row = chatRows.get(message.id);
      if (row?.signature !== rowSignature) {
        row = messageRow(message.role, message.content, {
          message, prompt: previousPrompt, attachments, linkedArtifacts: history.message_artifacts?.[message.id],
          uploadMetadata: history.message_uploads, warnings: message.notices || [],
        });
        row.signature = rowSignature;
        row.actionCards = message.role === "call" ? [] : cards.map(actionCard);
      }
      if (message.role !== "call") {
        const workerRows = workers.get(message.worker_turn_id);
        const proposal = proposals.get(message.self_update_id);
        if (proposal) {
          if (row.proposalCard) row.proposalCard.render(proposal);
          else row.proposalCard = updateCard(proposal, { perform: changeSelfUpdate, announce: announceSelfUpdate });
        }
        row.cards = [
          ...(workerRows ? [workersCard(workerRows)] : []),
          ...row.actionCards,
          ...(row.proposalCard ? [row.proposalCard.card] : []),
        ];
      }
      nextRows.set(message.id, row);
      row.searchHit = searchHit === message.id;
      rows.push(row);
      if (newHistory && index >= tail && !optimistic.has(message.id) && !optimistic.has(message.reply_to)) {
        arrivals.push(row);
      }
      if (workers.has(message.id) && !localPrompts.has(message.id) && !savedBatches.has(message.id)) {
        const activity = messageRow("assistant", "");
        activity.cards.push(workersCard(workers.get(message.id)));
        for (const action of actions.values()) {
          if (action.worker_turn_id === message.id) activity.cards.push(actionCard(action));
        }
        rows.push(activity);
      }
      if (message.role === "user") previousPrompt = { text: message.content, attachments };
    }
    for (const turn of local) {
      const previousTurn = previousMotion?.turns.get(turn.key);
      if (turn.showPrompt) {
        const row = messageRow("user", turn.user?.content || turn.prompt, {
          message: turn.user, status: turn.user ? undefined : "Queued", attachments: turn.attachments,
        });
        rows.push(row);
        if (live && !previousTurn?.showPrompt) arrivals.push(row);
      }
      if (!turn.showReply) continue;
      const content = turn.reply ? turn.reply.content
        : turn.text || turn.error || (turn.stopped ? "Reply stopped." : turn.browse ? "" : turnProgress(turn));
      const streaming = !turn.reply && !turn.error && !turn.browse && !turn.stopped;
      const row = messageRow("assistant", content, {
        message: turn.reply, skill: turn.skill, prompt: { text: turn.prompt, attachments: turn.attachments },
        streaming, working: streaming && !turn.text, error: turn.error, errorInNotice: !!turn.text,
        warnings: turn.stopped && turn.text ? [...turn.warnings, "Reply stopped."] : turn.warnings,
      });
      turnBubbles.set(turn.key, row);
      rows.push(row);
      if (live && !previousTurn?.showReply) arrivals.push(row);
      const workerRows = turn.workers?.size ? [...turn.workers.values()] : workers.get(turn.user?.id);
      if (workerRows?.length) row.cards.push(workersCard(workerRows));
      for (const action of turn.actions.values()) {
        const saved = actions.get(action.id);
        const current = action.worker_id && (action.status !== "pending" || saved?.status === "pending") ? action : saved;
        row.cards.push(actionCard(current || action));
      }
      if (turn.browse) row.cards.push(browseCard(turn.browse));
      if (turn.error) row.cards.push(iconButton("retry", "Edit and retry", () =>
        restorePrompt({ text: turn.user?.content || turn.prompt, attachments: turn.attachments })));
    }
    if ((remoteBrowse || remoteSkill) && !local.length) {
      const activity = messageRow("assistant", "", { skill: remoteSkill });
      if (remoteBrowse) activity.cards.push(browseCard(remoteBrowse));
      rows.push(activity);
    }
    renderConversation(transcript, rows, messageActions);
    arrive(arrivals.slice(-6).map((row) => row.item));
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
    for (const thread of [...serverState.threads.slice(0, serverState.next_thread_offset ?? undefined), ...sidebarTail]) {
      entries.set(thread.id, thread);
    }
    for (const thread of serverState.threads) entries.set(thread.id, thread);
    for (const [id, thread] of entries) {
      const active = serverState.thread_activity;
      entries.set(id, { ...thread, busy: Object.hasOwn(active, id), activity: Object.hasOwn(active, id) ? active[id] : undefined });
    }
    for (const thread of store.state.threads) {
      const browse = thread.activity?.browse;
      if (browse && (complete || entries.has(thread.id)) && entries.get(thread.id)?.activity?.browse?.id !== browse.id) {
        getArtifacts().endBrowse(browse.id);
      }
    }
    store.update({ threads: [...entries.values()] });
    onThreadsChanged();
    markSeenReplies();
    renderThreads();
    threadListReady ||= complete;
  }

  async function extendSidebar() {
    const revision = serverState.thread_revision;
    if (sidebarRequest?.revision === revision) return;
    const request = { revision };
    sidebarRequest = request;
    let offset = serverState.next_thread_offset;
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
      if (currentView() === "chat") renderChat();
    } catch {
      if (sidebarRequest === request) sidebarRequest = undefined;
    }
  }

  async function loadOlderMessages() {
    if (olderRequest || !conversation.snapshot) return false;
    const before = (conversation.pages[0] || conversation.snapshot).before;
    if (!before) return false;
    const thread = store.state.currentThread, version = selectionVersion;
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
    if (historyRefresh || currentView() !== "chat" || document.hidden || !conversation.pages.length) return;
    const viewport = chatScroll.getBoundingClientRect();
    const page = conversation.pages.find(({ messages, cursor, record_revision: revision }) => {
      if (!cursor || revision === serverState.record_revision) return false;
      const first = chatRows.get(messages[0]?.id)?.item;
      const last = chatRows.get(messages.at(-1)?.id)?.item;
      return first && last && first.getBoundingClientRect().top < viewport.bottom &&
        last.getBoundingClientRect().bottom > viewport.top;
    });
    if (!page) return;
    historyRefresh = page;
    try {
      const latest = await transcriptPage(store.state.currentThread, page.cursor);
      const { changed } = updateConversation({ type: "page", page: latest, previous: page });
      if (changed && currentView() === "chat") renderChat(true, true);
    } catch {
      // A changed or unavailable page can be retried on the next refresh.
    } finally {
      if (historyRefresh === page) historyRefresh = undefined;
    }
  }

  async function refreshState(actionId, { background, signal, around = aroundMessage } = {}) {
    if (background && windowRequest) return false;
    const request = ++stateRequest;
    const thread = store.state.currentThread;
    const params = new URLSearchParams({ thread });
    if (actionId) params.set("action", actionId);
    if (around) params.set("around", around);
    const variant = params.toString();
    const headers = conversation.snapshot && stateTag && stateVariant === variant ? { "If-None-Match": stateTag } : {};
    const load = async () => {
      const timeout = AbortSignal.timeout(6000);
      const response = await fetch(`/api/state?${variant}`, {
        headers, signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
      });
      return [response, response.status === 304 ? null : await readResponse(response)];
    };
    const [response, next] = await (currentView() === "chat" ? trackRefresh("/api/state", background, load) : load());
    if (signal?.aborted) return false;
    if (response.status === 304) {
      const current = request === stateRequest && thread === store.state.currentThread;
      if (current) {
        markSeenReplies();
        void extendSidebar();
      }
      return current;
    }
    if (request !== stateRequest || thread !== store.state.currentThread) return false;
    if (next.thread_id !== store.state.currentThread) {
      const deleted = store.state.currentThread;
      activateThread(next.thread_id);
      threadDrafts.delete(deleted);
      attachmentDraft.discard(deleted);
      avatarStates.delete(deleted);
      updateConversation({ type: "delete-thread", threadId: deleted });
    }
    if (conversation.snapshot?.history_revision !== next.history_revision ||
        conversation.snapshot?.around !== next.around) olderRequest = undefined;
    aroundMessage = next.around;
    byId("chat-history-navigation").hidden = !aroundMessage;
    serverState = next;
    updateConversation({ type: "snapshot", snapshot: next });
    setTimeZone(serverState.timezone);
    stateTag = response.headers.get("ETag");
    stateVariant = variant;
    byId("start-call").disabled = typeof serverState.voice_call_available !== "boolean";
    installSidebar(serverState.next_thread_offset == null || sidebarRequest?.revision === serverState.thread_revision);
    void extendSidebar();
    renderBrain(serverState);
    paintAvatars();
    schedulePoll();
    if (currentView() === "settings" && currentSettings() === "voice") voiceSettings.showEngine();
    return true;
  }

  function refreshDrawerThreads() {
    if (store.state.busy || threadBusy) return;
    refreshState().catch((error) => {
      if (byId("workspace-drawer").open) showNotice(error.message);
    });
  }

  function activateThread(threadId) {
    if (store.state.currentThread === threadId) return;
    voice.cancel();
    threadDrafts.set(store.state.currentThread, input.value);
    store.update({ currentThread: threadId });
    aroundMessage = undefined;
    byId("chat-history-navigation").hidden = true;
    clearChatSearchHit();
    selectionVersion++;
    stateRequest++;
    updateConversation({ type: "select", threadId });
    replyStatus.replaceChildren();
    olderRequest = undefined;
    historyRefresh = undefined;
    sessionStorage.setItem("hearth-thread", threadId);
    input.value = threadDrafts.get(threadId) || "";
    attachmentDraft.render();
    resizeInput();
    renderChat(true);
    scrollDown();
    chatSearch.threadChanged();
  }

  async function selectThread(threadId, focus = false) {
    if (threadId === store.state.currentThread && aroundMessage) aroundMessage = undefined;
    activateThread(threadId);
    if (focus && mobile.isMobile()) mobile.closeDrawer();
    showNotice();
    if (focus && currentView() === "chat") {
      if (!mobile.isMobile()) input.focus();
    }
    try {
      await refreshView();
    } catch (error) {
      if (store.state.currentThread === threadId) showNotice(error.message);
    }
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
    if (store.state.busy) throw new Error("Wait for the current Chat action to finish, then try again.");
    return chat(prompt, { keepDraft: true, threadId: mainThread.id });
  }

  async function openArtifactThread(threadId, messageId) {
    activateThread(threadId);
    await openView("chat");
    const version = selectionVersion;
    if (aroundMessage && threadId === store.state.currentThread && !chatRows.has(messageId)) {
      try {
        await latestChatMessages();
      } catch (error) {
        showNotice(error.message);
        return;
      }
    }
    let message = chatRows.get(messageId)?.item;
    while (!message && threadId === store.state.currentThread && currentView() === "chat" && version === selectionVersion &&
        await loadOlderMessages()) {
      message = chatRows.get(messageId)?.item;
    }
    if (message) {
      message.classList.add("artifact-anchor");
      message.tabIndex = -1;
      message.focus({ preventScroll: true });
      message.scrollIntoView({ block: "center" });
    } else if (threadId !== store.state.currentThread) {
      showNotice("The source chat is no longer available.");
    }
  }

  async function openChatSearchResult({ thread_id: thread, id }, signal) {
    signal.throwIfAborted();
    if (store.state.avatarMode === "face") chooseAvatarMode("beside");
    activateThread(thread);
    if (!chatRows.has(id)) {
      try {
        if (await refreshChatWindow(id, signal)) renderChat(true, true);
      } finally {
        if (currentView() === "chat" && store.state.currentThread === thread && !conversation.snapshot) schedulePoll(true);
      }
    }
    const item = chatRows.get(id)?.item;
    if (!item || signal.aborted || store.state.currentThread !== thread || currentView() !== "chat") throw new Error("Message unavailable.");
    return item;
  }

  async function refreshChatWindow(around, signal) {
    const request = {};
    windowRequest = request;
    try {
      return await refreshState(undefined, { around, signal });
    } finally {
      if (windowRequest === request) windowRequest = undefined;
    }
  }

  function clearChatSearchHit() {
    clearTimeout(searchHitTimer);
    chatRows.get(searchHit)?.item.classList.remove("chat-search-hit");
    searchHit = undefined;
  }

  function revealChatSearchResult(item, { focus } = {}) {
    clearChatSearchHit();
    searchHit = item.dataset.messageId;
    item.classList.add("chat-search-hit");
    if (focus) {
      item.tabIndex = -1;
      item.focus({ preventScroll: true });
    }
    item.scrollIntoView({ block: "center", behavior: "instant" });
    searchHitTimer = setTimeout(clearChatSearchHit, 3200);
  }

  async function latestChatMessages() {
    if (!aroundMessage) return true;
    if (!await refreshChatWindow(null)) return false;
    clearChatSearchHit();
    renderChat(true);
    scrollDown();
    return true;
  }

  async function changeThread(operation, body = {}) {
    if (threadBusy || store.state.busy) return;
    threadBusy = true;
    renderThreads();
    const selection = selectionVersion;
    try {
      await getConnectionRequest();
      const result = await api(`/api/threads/${operation}`, body);
      if (operation === "create" || operation === "rename") rememberThread(result);
      if (operation === "create" && selection === selectionVersion) {
        await selectThread(result.id, true);
        if (currentView() !== "chat") await openView("chat");
      } else if (operation === "delete") {
        store.update({ threads: store.state.threads.filter((item) => item.id !== body.thread_id) });
        if (store.state.currentThread === body.thread_id) activateThread(mainThread.id);
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
    const visible = turn.threadId === store.state.currentThread;
    const bubble = visible && turnBubbles.get(key);

    if (name === "queued") {
      avatarSignal(turn.threadId, { type: "queued" });
      rememberThread(payload.thread);
      if (turn.suggestion && turn.selection === selectionVersion) {
        activateThread(turn.threadId);
        void openView("chat");
      } else if (turn.command && turn.selection === selectionVersion) {
        activateThread(turn.threadId);
        if (currentView() === "chat") input.focus();
      }
    } else if (name === "started") {
      rememberThread(payload.thread);
      if (conversation.turns.has(key)) avatarSignal(turn.threadId, { type: "started" });
    } else if (name === "token" || name === "reset") {
      const follow = visible && nearBottom();
      avatarSignal(turn.threadId, { type: name, text: payload.text });
      bubble?.setStream({ content: turn.text || turnProgress(turn), working: !turn.text, follow });
      if (store.state.avatarMode === "face" && visible) updateFaceCaption(turn.text);
      if (!bubble && follow) scrollDown();
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
      if (card.parentElement !== bubble.cardsElement) bubble.cardsElement.prepend(card);
      if (store.state.avatarMode === "face") updateFaceWorkers(workers);
      if (follow) scrollDown();
      return;
    } else if (name === "browse_active") {
      avatarSignal(turn.threadId, { type: "tool_started", title: `Browsing ${payload.domain}` });
    } else if (name === "browse_finished") {
      getArtifacts().endBrowse(payload.id);
      avatarSignal(turn.threadId, { type: "tool_finished" });
    } else if (name === "tool_started" || name === "tool_finished" || name === "demo_listening") {
      if (bubble && !turn.text) bubble.setStream({ content: turnProgress(turn), working: true });
      avatarSignal(turn.threadId, { type: name, title: payload.title });
      return;
    } else if (name === "remembered") {
      avatarSignal(turn.threadId, { type: "remembered" });
      return;
    } else if (name === "tool_warning" || name === "demo_warning") {
      avatarSignal(turn.threadId, { type: "warning", detail: name === "demo_warning" ? "Mock demo" : "" });
      return;
    }
    if (turn.threadId === store.state.currentThread) renderChat(true);
    else renderThreads();
  }

  async function chat(prompt, { keepDraft = false, approval, suggestion, threadId = store.state.currentThread } = {}) {
    prompt = prompt.trim();
    if (store.state.busy || (approval && localTurns().some((turn) => turn.approval?.id === approval.id && !turn.finished))) return;
    const attachments = keepDraft || approval ? [] : attachmentDraft.selected();
    if (!attachments || (!prompt && !approval && !suggestion && !attachments.length)) return;
    voice.cancel();
    const source = approval?.thread_id || threadId;
    if (source === store.state.currentThread && aroundMessage) {
      try {
        if (!await latestChatMessages() || source !== store.state.currentThread) return;
      } catch (error) {
        showNotice(error.message);
        return;
      }
    }
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
      await getConnectionRequest();
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
          if (source === store.state.currentThread && !input.value) {
            input.value = prompt;
            resizeInput();
          }
        }
        if ((pending.threadId || source) === store.state.currentThread) {
          showNotice(failure);
          chatNoticeTurn = key;
        }
      }
      return { ...pending, error: failure };
    } finally {
      const pending = conversation.turns.get(key);
      getArtifacts().endBrowse(pending?.browse?.id);
      updateConversation({ type: "finish", key, error: failure });
      if (!pending?.threadId || pending.threadId === store.state.currentThread) renderChat(true);
      else renderThreads();
      await refreshView().catch(() => {});
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
    avatarSignal(store.state.currentThread, { type: "typing", gaze });
  }

  function composerShortcut(event) {
    if (event.key === "Escape" && voice.active) {
      event.preventDefault();
      voice.cancel();
    } else if (event.key === "Escape" && currentView() === "chat" && store.state.avatarMode === "face") {
      chooseAvatarMode("beside");
      if (!mobile.isMobile()) byId("avatar-view").focus();
    } else if (event.code === "Space" && !event.isComposing && !event.altKey && !event.ctrlKey && !event.metaKey) {
      if (spaceHeld) {
        event.preventDefault();
      } else if (!event.repeat && !event.shiftKey && currentView() === "chat" && !store.state.busy && !voice.active && !voiceCall.inProgress && !input.value.trim()
          && (event.target === input || event.target === document.body)) {
        event.preventDefault();
        spaceHeld = true;
        startVoice();
      }
    }
  }
  document.addEventListener("keyup", (event) => {
    if (event.code !== "Space" || !spaceHeld) return;
    event.preventDefault();
    spaceHeld = false;
    if (["recording", "requesting"].includes(store.state.dictation.phase)) voice.stop();
  });
  setInterval(() => {
    if (!document.hidden) paintAvatars();
  }, 100);

  byId("thread-select").addEventListener("change", (event) => selectThread(event.target.value));
  byId("chat-latest").addEventListener("click", async () => {
    try {
      if (await latestChatMessages()) byId("thread-title").focus({ preventScroll: true });
    } catch (error) {
      showNotice(error.message);
    }
  });
  byId("new-thread").addEventListener("click", () => changeThread("create"));
  function renameThread(thread) {
    if (!thread || store.state.busy || threadBusy) return;
    const title = window.prompt("Rename side chat", thread.title)?.trim();
    if (title && title !== thread.title) changeThread("rename", { thread_id: thread.id, title });
  }
  function deleteThread(thread) {
    if (thread && !store.state.busy && !threadBusy && !isWorking(thread) &&
        window.confirm(`Delete “${thread.title}”? Hearth will save a checkpoint first.`)) {
      changeThread("delete", { thread_id: thread.id });
    }
  }
  byId("rename-thread").addEventListener("click", () => renameThread(store.state.threads.find((item) => item.id === store.state.currentThread)));
  byId("delete-thread").addEventListener("click", () => deleteThread(store.state.threads.find((item) => item.id === store.state.currentThread)));
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
    showLoading(byId("thread-summary-status"), "Loading summary…");
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
    const thread = store.state.threads.find((item) => item.id === threadMenuId);
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
  for (const prompt of document.querySelectorAll("[data-prompt]")) {
    prompt.addEventListener("click", () => chat(prompt.dataset.prompt));
  }
  let lastChatTop = 0;
  chatScroll.addEventListener("scroll", () => {
    const top = chatScroll.scrollTop;
    if (currentView() === "chat" && top <= 64 && top < lastChatTop) void loadOlderMessages();
    else void refreshVisibleHistory();
    lastChatTop = top;
  }, { passive: true });

  return {
    activateThread, applyAppearance, composerShortcut, openArtifactThread, openDemo, openMainChat,
    openPanelChat, openSkillChat, paintAvatars, refreshState, refreshVisibleHistory, renderChat,
    send: chat, sendPanelPrompt, voiceSettings,
    mobile, voiceCall, signalAvatar: avatarSignal,
    get threads() { return store.state.threads; },
    get busy() { return store.state.busy; },
    get snapshot() { return serverState; },
    get threadBusy() { return threadBusy; },
    get hasPendingTurns() { return localTurns().some((turn) => !turn.finished); },
    closeThreadMenu: threadActions.close,
    clearNoticeTurn() { chatNoticeTurn = undefined; },
    closeSearch: chatSearch.close,
    searchShortcut(event) {
      return chatSearch.shortcut(event, currentView() === "chat" && !document.querySelector("dialog[open]:not(#chat-search-dialog)"));
    },
    cancelVoice({ releaseKey = false } = {}) {
      if (releaseKey) spaceHeld = false;
      voice.cancel();
    },
    fillDraft(text) {
      input.value = text;
      resizeInput();
    },
    setBusy(value) {
      store.update({ busy: value });
      renderThreads();
    },
    reminderSending(sending) {
      sendingTestReminder = sending;
      renderThreads();
      avatarSignal(mainThread.id, sending ? { type: "tool_started", title: "Sending reminder" } : { type: "tool_finished" });
    },
  };
}
