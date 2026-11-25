export const IDLE_MS = 120_000;
const TYPING_MS = 1_650;
const REMEMBER_MS = 1_450;
const HAPPY_MS = 1_250;
const CONCERN_MS = 1_750;

export function newAvatar(now) {
  return { last: now, phase: "idle" };
}

export function mouthFor(text) {
  const chars = [...text.trim()];
  if (!chars.length) return 0;
  const strength = Math.min(1, .22 + chars.length * .06);
  return /[.!?。！？…]$/u.test(text.trim()) ? strength * .25
    : /[,;:，、；：]$/u.test(text.trim()) ? strength * .55 : strength;
}

export function avatarEvent(state, event, now) {
  const next = { ...state, last: now };
  switch (event.type) {
    case "typing":
      return { ...next, typing: now + TYPING_MS, gaze: event.gaze, sleepUntil: 0 };
    case "recording":
      return { ...next, recording: event.active, typing: 0, sleepUntil: 0 };
    case "voice_processing":
      return { ...next, voiceProcessing: event.active };
    case "demo_listening":
      return { ...next, demoListening: true };
    case "queued":
      return { ...next, typing: 0, sleepUntil: 0 };
    case "started":
      return { ...next, phase: "thinking", title: "", mouth: 0, typing: 0, demoListening: false,
        happy: 0, remembered: 0, concerned: 0, scheduled: 0, sleepUntil: 0 };
    case "tool_started":
      return { ...next, phase: "working", title: event.title, mouth: 0 };
    case "tool_finished":
      return { ...next, phase: "thinking", title: "" };
    case "token":
      return { ...next, phase: "speaking", mouth: mouthFor(event.text), mouthUntil: now + 160 };
    case "reset":
      return { ...next, phase: "thinking", mouth: 0, title: "" };
    case "reminder":
      return { ...next, scheduled: event.until > now ? event.until : 0 };
    case "done": {
      const start = Math.max(now, state.concerned || 0);
      const remembered = event.remembered ? start + REMEMBER_MS : 0;
      return { ...next, phase: "idle", title: "", mouth: 0, remembered,
        happy: (remembered || start) + HAPPY_MS, sleepUntil: state.scheduled, scheduled: 0 };
    }
    case "remembered":
      return { ...next, remembered: now + REMEMBER_MS, sleepUntil: 0 };
    case "celebrate":
      return { ...next, happy: now + HAPPY_MS, sleepUntil: 0 };
    case "approval_started":
      return { ...next, approval: event.title, sleepUntil: 0 };
    case "approval_done":
      return event.success ? { ...next, approval: "", happy: now + HAPPY_MS }
        : { ...next, approval: "", concerned: now + CONCERN_MS };
    case "warning":
      return { ...next, concerned: now + CONCERN_MS, concernDetail: event.detail };
    case "error":
      return { ...next, phase: "idle", title: "", mouth: 0, concerned: now + CONCERN_MS,
        concernDetail: "", demoListening: false, scheduled: 0 };
    default:
      return state;
  }
}

export function avatarPose(state, now, busy = false) {
  if (state.recording) return { pose: "listening", detail: "Microphone on", gaze: 0 };
  if (state.voiceProcessing) return { pose: "working", detail: "Transcribing audio" };
  if (now < state.concerned) return { pose: "concerned", detail: state.concernDetail };
  if (state.demoListening) return { pose: "listening", detail: "Mock demo" };
  if (now < state.typing) return { pose: "listening", gaze: state.gaze };
  if (state.approval) return { pose: "working", detail: state.approval };
  if (state.phase === "working") return { pose: "working", detail: state.title };
  if (state.phase === "speaking") {
    return { pose: "speaking", mouth: now < state.mouthUntil ? state.mouth : 0 };
  }
  if (state.phase === "thinking") return { pose: "thinking" };
  if (now < state.remembered) return { pose: "remembering" };
  if (now < state.happy) return { pose: "happy" };
  if (busy) return { pose: "thinking" };
  if (now < state.sleepUntil) return { pose: "sleeping", detail: "Reminder scheduled" };
  if (now - state.last >= IDLE_MS) return { pose: "sleeping" };
  return { pose: "idle" };
}
