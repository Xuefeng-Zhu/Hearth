import { useLayoutEffect } from "preact/hooks";
import { mountStore, useAppState } from "../store.js";
import { html, Icon } from "./view.js";

function Composer({ form, onSend, onStop, onAttach, onInput, onSelect, onMic, onCancelVoice }) {
  const { currentThread, busy, uploading, sendLabel, canStop, stoppingReply, callActive, dictation } = useAppState();
  const { phase, interim, engine, held } = dictation;
  const recording = phase === "recording";
  const active = phase !== "idle";
  const micLabel = recording ? "Stop voice recording" : active ? "Cancel voice input" : "Start voice input";
  const voiceStatus = recording ? `Recording · ${engine === "whisper" ? "Whisper" : "Browser"}`
    : phase === "processing" ? "Transcribing…" : active ? "Waiting for microphone…" : "";

  useLayoutEffect(() => {
    const submit = (event) => {
      event.preventDefault();
      const { message, send } = form.elements;
      if (document.activeElement === send) message.focus({ preventScroll: true });
      onSend(message.value);
    };
    form.addEventListener("submit", submit);
    return () => form.removeEventListener("submit", submit);
  }, [form, onSend]);

  function editorKeys(event) {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    onSend(event.currentTarget.value);
  }

  return html`
    <div id="voice-bar" class="voice-bar" hidden=${!active} data-phase=${active ? phase : null}>
      <div class="voice-reading">
        <span class="voice-dot" aria-hidden="true"></span>
        <span id="voice-phase" role="status">${voiceStatus}</span>
        <meter id="voice-level" aria-label="Microphone level" min="0" max="1" hidden=${!recording}></meter>
      </div>
      <span id="voice-key" class="voice-key" aria-hidden="true">
        ${recording && held ? "Release Space to finish · Esc to cancel" : "Esc to cancel"}
      </span>
      <button type="button" class="mobile-only voice-cancel" id="voice-cancel" onClick=${onCancelVoice}>Cancel</button>
      <p id="voice-interim" hidden=${!interim}>${interim}</p>
    </div>
    <div id="composer-attachments" class="composer-attachments" hidden></div>
    <p id="attachment-status" class="attachment-status" role="status" hidden></p>
    <input id="attachment-files" type="file" multiple hidden />
    <button type="button" id="attach" aria-label="Attach files" title="Attach files" disabled=${busy} onClick=${onAttach}>
      <${Icon} name="paperclip" />
    </button>
    <label class="visually-hidden" for="message">Message Hearth</label>
    <textarea id="message" maxlength="4000" rows="1"
      placeholder=${currentThread === "main" ? "Message Hearth…" : "Message this side chat…"}
      onInput=${onInput} onSelect=${onSelect} onKeyDown=${editorKeys}></textarea>
    <button type="button" id="mic" aria-label=${micLabel} aria-pressed=${String(active)}
      title=${active ? micLabel : "Start voice input. Hold Space in an empty composer to talk."}
      disabled=${callActive} onClick=${onMic}>
      <span class="mic-on"><${Icon} name="mic" /></span>
      <span class="mic-stop"><${Icon} name="stop" /></span>
    </button>
    <button type="submit" id="send" aria-label=${sendLabel} title=${sendLabel} disabled=${busy || uploading}>
      <${Icon} name="send" />
    </button>
    <button type="button" id="stop-reply" aria-label="Stop reply" title="Stop reply"
      hidden=${!canStop} aria-disabled=${String(stoppingReply)} onClick=${onStop}><${Icon} name="stop" /></button>
  `;
}

export function mountComposer(form, store, handlers) {
  mountStore(form, store, Composer, { form, ...handlers }, [
    "currentThread", "busy", "uploading", "sendLabel", "canStop", "stoppingReply", "callActive", "dictation",
  ]);
}
