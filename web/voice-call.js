import { setPose } from "./avatar.js";

const byId = (id) => document.getElementById(id);
const preferencesKey = "hearth-voice-call";
const demoLabel = "Demo call — Vocal Bridge not connected";
const defaultPreferences = { language: "auto", minutes: 10, autoSave: true };

function readPreferences() {
  try {
    const saved = JSON.parse(localStorage.getItem(preferencesKey));
    if (saved && ["auto", "en", "zh"].includes(saved.language)
        && Number.isInteger(saved.minutes) && saved.minutes >= 1 && saved.minutes <= 60
        && typeof saved.autoSave === "boolean") return saved;
  } catch {
    // Use the defaults if the saved preferences cannot be read.
  }
  return { ...defaultPreferences };
}

export function callDuration(seconds) {
  const clock = [Math.floor(seconds / 60), seconds % 60];
  return clock.map((value) => String(value).padStart(2, "0")).join(":");
}

export function captionLine({ role, text }) {
  const item = document.createElement("li");
  const speaker = document.createElement("strong");
  speaker.textContent = role === "user" ? "You" : "Hearth";
  const caption = document.createElement("span");
  caption.textContent = text;
  item.append(speaker, caption);
  return item;
}

export function createVoiceCall({ api, getThread, isConfigured, prepare, makeMascot, update, onAction, date }) {
  const sheet = byId("call-sheet");
  const phase = byId("call-phase");
  const clock = byId("call-clock");
  const avatar = byId("call-avatar");
  const captions = byId("call-captions");
  const audio = byId("call-enable-audio");
  const mute = byId("call-mute");
  const end = byId("call-end");
  const done = byId("call-done");
  const minimize = byId("minimize-call");
  const resume = byId("return-to-call");
  const retrySave = byId("call-retry-save");
  const feedback = byId("call-feedback");
  let preferences = readPreferences();
  let session;

  const active = (call) => session === call && !call.ended;
  const seconds = (call) => call.startedAt === undefined
    ? 0 : Math.floor((performance.now() - call.startedAt) / 1000);

  function setFeedback(text = "") {
    feedback.textContent = text;
    feedback.hidden = !text;
  }

  function setActivity(call) {
    if (!active(call)) return;
    const pose = call.remoteSpeaking && !call.audioBlocked ? "speaking"
      : call.localSpeaking ? "listening" : call.queries ? "thinking" : "idle";
    call.pose = { pose };
    if (call.mascot) setPose(call.mascot, call.pose);
    byId("call-thinking").hidden = !call.queries;
    update(call);
  }

  function addCaption(call, { role, text }) {
    if (!active(call) || !["user", "agent"].includes(role) || typeof text !== "string" || !text.trim()) return;
    const entry = { role, text: text.trim().slice(0, 4000) };
    const bytes = new TextEncoder().encode(JSON.stringify(entry)).length + 1;
    while (call.lines.length >= 400 || call.bytes + bytes > 480_000) {
      call.bytes -= new TextEncoder().encode(JSON.stringify(call.lines.shift())).length + 1;
      captions.firstElementChild?.remove();
    }
    call.bytes += bytes;
    call.lines.push(entry);
    byId("call-caption-empty").hidden = true;
    captions.append(captionLine(entry));
    captions.scrollTop = captions.scrollHeight;
  }

  function goLive(call) {
    if (!active(call) || call.startedAt !== undefined) return;
    clearTimeout(call.connectTimer);
    call.startedAt = performance.now();
    phase.textContent = "Live";
    clock.hidden = byId("call-caption-panel").hidden = false;
    mute.hidden = minimize.hidden = false;
    end.textContent = "End call";
    const tick = () => {
      const elapsed = seconds(call);
      clock.textContent = callDuration(elapsed);
      if (elapsed >= call.preferences.minutes * 60) endCall("Call time limit reached.");
    };
    tick();
    call.timer = setInterval(tick, 250);
    if (call.client) sendContext(call);
  }

  function sendContext(call) {
    const language = call.preferences.language;
    const participant = call.client.room.localParticipant;
    if (language !== "auto" && participant.permissions?.canUpdateMetadata) {
      participant.setAttributes({ "hearth.language": language }).catch(() => {});
    }
    call.client.sendAction("hearth_context", {
      thread_title: call.thread.title, user_name: call.participantName, language,
    }).catch(() => {
      if (active(call)) setFeedback("The call connected, but Hearth could not send the chat context.");
    });
  }

  async function saveReport(call) {
    retrySave.hidden = true;
    done.disabled = true;
    setFeedback("Saving to this chat…");
    try {
      await api("/api/voice/call/report", call.report, AbortSignal.timeout(10_000));
      call.report = undefined;
      if (session === call) setFeedback(call.preferences.autoSave
        ? "Call card saved to this chat." : "Call card saved. Transcript auto-save is off.");
      update(call, true);
    } catch {
      if (session !== call) return;
      setFeedback("Hearth could not save the call card.");
      retrySave.hidden = false;
    } finally {
      if (session === call) done.disabled = false;
    }
  }

  function endCall(reason = "") {
    const call = session;
    if (!call || !active(call)) return;
    call.ended = true;
    call.controller.abort();
    clearInterval(call.timer);
    clearTimeout(call.connectTimer);
    for (const timer of call.demoTimers) clearTimeout(timer);
    const room = call.client?.room;
    call.client?.disconnect().catch(() => {}).finally(() => call.client?.room?.disconnect().catch(() => {}));
    // Interrupt room negotiation even if the SDK is still waiting for microphone permission.
    if (!call.ready) room?.disconnect().catch(() => {});

    phase.textContent = call.startedAt === undefined ? (reason ? "Call unavailable" : "Call canceled") : "Call ended";
    minimize.hidden = mute.hidden = end.hidden = audio.hidden = byId("call-thinking").hidden = true;
    if (call.mascot) setPose(call.mascot, { pose: "idle" });
    if (reason) addFeedbackLine(reason);
    done.hidden = false;
    if (sheet.open) done.focus();
    if (call.startedAt === undefined) {
      setFeedback("");
      update(call);
      return;
    }
    const elapsed = Math.min(seconds(call), call.preferences.minutes * 60);
    clock.textContent = callDuration(elapsed);
    call.report = {
      id: call.id, thread_id: call.thread.id, duration: elapsed, demo: call.demo,
      lines: call.preferences.autoSave ? call.lines : [],
    };
    update(call);
    saveReport(call);
  }

  function addFeedbackLine(text) {
    const line = document.createElement("p");
    line.id = "call-end-reason";
    line.className = "meta";
    line.textContent = text;
    feedback.before(line);
  }

  function demoCall(call) {
    const cue = (delay, action) => call.demoTimers.push(setTimeout(() => {
      if (active(call)) action();
    }, delay));
    cue(550, () => goLive(call));
    cue(950, () => {
      call.localSpeaking = !call.muted;
      if (!call.muted) addCaption(call, { role: "user", text: "Can you remind me to check the oven?" });
      setActivity(call);
    });
    cue(1800, () => {
      call.localSpeaking = false;
      call.queries = 1;
      setActivity(call);
    });
    cue(2600, () => {
      call.queries = 0;
      call.remoteSpeaking = true;
      setActivity(call);
      addCaption(call, { role: "agent", text: "In a live call, I can set that reminder and show it in your Timeline." });
    });
    cue(5500, () => {
      call.remoteSpeaking = false;
      setActivity(call);
    });
  }

  async function askHearth(call, query) {
    if (!active(call)) return "";
    call.queries++;
    setActivity(call);
    try {
      const { reply } = await api("/api/voice/call/query", {
        thread_id: call.thread.id, query: query.trim().slice(0, 4000),
      }, AbortSignal.timeout(117_000));
      return active(call) ? reply : "";
    } catch (error) {
      if (active(call)) setFeedback(error.message);
      return "I couldn't finish that request. You can check Hearth for the turn's status.";
    } finally {
      call.queries--;
      setActivity(call);
      update(call, true);
    }
  }

  async function connect(call) {
    let tokenError;
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        endCall("Microphone access requires HTTPS or localhost and a compatible browser.");
        return;
      }
      const [{ VocalBridge, RoomEvent, setLogLevel }, status] = await Promise.all([
        import("./vendor/vocalbridge.mjs"),
        api("/api/voice/call/status", undefined, AbortSignal.timeout(8000)),
      ]);
      if (!active(call)) return;
      setLogLevel("silent");
      call.participantName = status.participant_name || "User";
      const client = new VocalBridge({
        auth: { tokenProvider: async () => {
          try {
            return await api("/api/voice/call/token", {}, call.controller.signal);
          } catch (error) {
            tokenError = error.message;
            throw error;
          }
        } },
        participantName: call.participantName,
        maxReconnectAttempts: 0,
      });
      call.client = client;
      client.onAIAgentQuery((query) => askHearth(call, query));
      client.on("transcript", (entry) => addCaption(call, entry));
      client.on("agentAction", ({ action, payload }) => {
        if (active(call) && ["open_timeline", "show_reminder"].includes(action)) {
          hideSheet();
          onAction(action, payload);
        }
      });
      client.on("connectionStateChanged", (state) => {
        if (!active(call)) return;
        if (state === "waiting_for_agent") phase.textContent = "Waiting for Vocal Bridge…";
        if (state === "connected" && call.ready) goLive(call);
        if (state === "disconnected" && call.ready) endCall("The voice connection closed.");
      });
      client.on("error", ({ code }) => {
        if (active(call) && code === "MICROPHONE_ERROR") endCall("Allow microphone access in your browser and try again.");
      });
      await client.connect();
      if (!active(call)) return;
      call.ready = true;
      const room = client.room;
      room.on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
        call.localSpeaking = speakers.some((speaker) => speaker.isLocal);
        call.remoteSpeaking = speakers.some((speaker) => !speaker.isLocal);
        setActivity(call);
      });
      const playback = () => {
        if (!active(call)) return;
        call.audioBlocked = !room.canPlaybackAudio;
        audio.hidden = !call.audioBlocked;
        setActivity(call);
      };
      room.on(RoomEvent.AudioPlaybackStatusChanged, playback);
      playback();
      if (client.state === "connected") goLive(call);
      else {
        clearTimeout(call.connectTimer);
        call.connectTimer = setTimeout(() => endCall("The Vocal Bridge agent did not join. Check its deployment."), 20_000);
      }
    } catch (error) {
      if (!active(call)) return;
      const cause = error.cause?.name;
      endCall(tokenError || (["NotAllowedError", "NotFoundError", "NotReadableError"].includes(cause)
        ? "Check microphone permissions and try again." : "Hearth could not connect to Vocal Bridge. Try again."));
    }
  }

  function showSheet() {
    resume.hidden = true;
    sheet.showModal();
  }

  function hideSheet() {
    sheet.close();
    resume.hidden = false;
  }

  function start() {
    if (session) {
      if (!sheet.open) showSheet();
      return;
    }
    if (isConfigured() == null || !prepare()) return;
    const call = {
      id: Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, "0")).join(""),
      thread: getThread(), demo: !isConfigured(),
      preferences: { ...preferences }, lines: [], bytes: 0, queries: 0, demoTimers: [],
      controller: new AbortController(), pose: { pose: "idle" }, mascot: makeMascot(),
    };
    session = call;
    avatar.replaceChildren(...(call.mascot ? [call.mascot] : []));
    avatar.hidden = !call.mascot;
    byId("call-thread").textContent = call.thread.title;
    byId("call-demo-label").textContent = demoLabel;
    byId("call-demo-label").hidden = !call.demo;
    byId("call-end-reason")?.remove();
    captions.replaceChildren();
    byId("call-caption-empty").hidden = false;
    phase.textContent = "Connecting…";
    minimize.hidden = mute.hidden = audio.hidden = done.hidden = retrySave.hidden = true;
    clock.hidden = byId("call-caption-panel").hidden = byId("call-thinking").hidden = true;
    mute.textContent = "Mute";
    mute.setAttribute("aria-pressed", "false");
    end.hidden = false;
    end.textContent = "Cancel";
    setFeedback();
    showSheet();
    if (call.demo) demoCall(call);
    else {
      call.connectTimer = setTimeout(() => endCall("The connection took too long. Try again."), 125_000);
      connect(call);
    }
    update(call);
  }

  async function refreshSettings() {
    const badge = byId("call-engine-status");
    const check = byId("call-engine-check");
    try {
      const info = await api("/api/voice/call/status", undefined, AbortSignal.timeout(8000));
      badge.textContent = info.configured ? "Connected" : "Not configured";
      badge.className = `connection-status ${info.configured ? "ok" : "not_set_up"}`;
      byId("call-setup").hidden = info.configured;
      const last = info.last_check;
      const outcome = { configured: "Connector found", missing: "No connector found", passed: "Passed", failed: "Failed", denied: "Access denied" };
      const kind = { discovery: "Discovery", token: "Token mint", authorization: "Access check" };
      check.textContent = last ? `${kind[last.kind]} · ${outcome[last.status]} · ${date(last.at)}${last.detail ? ` · ${last.detail}` : ""}` : "";
    } catch {
      badge.textContent = "Status unavailable";
      badge.className = "connection-status unknown";
      check.textContent = "";
    }
  }

  byId("start-call").addEventListener("click", start);
  resume.addEventListener("click", showSheet);
  minimize.addEventListener("click", hideSheet);
  end.addEventListener("click", () => endCall());
  done.addEventListener("click", () => {
    sheet.close();
    session = undefined;
    resume.hidden = true;
  });
  retrySave.addEventListener("click", () => saveReport(session));
  sheet.addEventListener("cancel", (event) => {
    event.preventDefault();
    if (session?.ended) done.click();
    else endCall();
  });
  window.addEventListener("pagehide", () => {
    session?.controller.abort();
    session?.client?.room?.disconnect().catch(() => {});
  });
  mute.addEventListener("click", async () => {
    const call = session;
    const muted = !call.muted;
    mute.disabled = true;
    try {
      if (call.client) await call.client.setMicrophoneEnabled(!muted);
      if (!active(call)) return;
      call.muted = muted;
      mute.textContent = muted ? "Unmute" : "Mute";
      mute.setAttribute("aria-pressed", String(muted));
    } catch {
      if (active(call)) setFeedback("Hearth could not change the microphone. Try again.");
    } finally {
      mute.disabled = false;
    }
  });
  audio.addEventListener("click", async () => {
    try {
      await session.client.room.startAudio();
    } catch {
      setFeedback("Your browser still blocks call audio.");
    }
  });
  byId("call-settings-form").addEventListener("submit", (event) => {
    event.preventDefault();
    preferences = {
      language: byId("call-language").value, minutes: byId("call-limit").valueAsNumber,
      autoSave: byId("call-save-transcript").checked,
    };
    localStorage.setItem(preferencesKey, JSON.stringify(preferences));
    byId("call-settings-status").textContent = "Call settings saved.";
  });

  return {
    get open() { return sheet.open; },
    get inProgress() { return !!session && !session.ended; },
    poseFor(threadId) { return session?.thread.id === threadId && !session.ended ? session.pose : undefined; },
    refreshSettings,
    syncSettings() {
      byId("call-language").value = preferences.language;
      byId("call-limit").value = preferences.minutes;
      byId("call-save-transcript").checked = preferences.autoSave;
      return refreshSettings();
    },
  };
}
