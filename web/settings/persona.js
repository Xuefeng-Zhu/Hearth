import { render } from "preact";
import { useLayoutEffect, useRef } from "preact/hooks";
import { looks, mascot, setLook } from "../avatar.js";
import { html } from "../ui.js";
import { updateText } from "../dom.js";
import { mountStore, useAppState } from "../store.js";

export function readAppearance() {
  const avatarModes = ["off", "beside", "face"];
  const savedMode = localStorage.getItem("hearth-avatar-view");
  const savedLook = localStorage.getItem("hearth-avatar-look");
  const savedColor = localStorage.getItem("hearth-avatar-color") || "";
  return {
    avatarMode: avatarModes.includes(savedMode) ? savedMode : "beside",
    avatarLook: Object.hasOwn(looks, savedLook) ? savedLook : "ember",
    avatarColor: /^#[0-9a-f]{6}$/i.test(savedColor) ? savedColor : "",
  };
}

function AvatarPreview({ preset, look, selected, color, onSelect }) {
  const control = useRef();
  useLayoutEffect(() => {
    const preview = mascot(preset);
    preview.dataset.still = "";
    control.current.prepend(preview);
  }, [preset]);
  useLayoutEffect(() => {
    setLook(control.current.firstChild, preset, selected && color ? color : look.color);
  }, [preset, selected, color, look]);
  return html`
    <button type="button" id=${`look-${preset}`} ref=${control} aria-pressed=${String(selected)}
      onClick=${() => onSelect(preset)}><span>${look.name}</span></button>
  `;
}

function Appearance({ onMode, onFace, onLook, onColor }) {
  const { avatarMode, avatarLook, avatarColor } = useAppState();
  return html`
    <div class="card appearance-card">
      <label class="appearance-toggle"><input type="checkbox" id="avatar-enabled" checked=${avatarMode !== "off"}
          onChange=${({ currentTarget }) => onMode(currentTarget.checked ? "beside" : "off")} /> Show avatar in chat</label>
      <label class="mobile-only ember-view-setting" for="ember-view">
        Ember view
        <select class="avatar-view" id="ember-view" value=${avatarMode} onChange=${({ currentTarget }) => {
          const mode = currentTarget.value;
          onMode(mode);
          if (mode === "face") onFace();
        }}>
          <option value="off">Off</option>
          <option value="beside">Beside chat</option>
          <option value="face">Full screen</option>
        </select>
      </label>
      <fieldset class="avatar-looks">
        <legend>Avatar preset</legend>
        <div id="avatar-looks" class="avatar-choices">
          ${Object.entries(looks).map(([preset, look]) => html`
            <${AvatarPreview} key=${preset} preset=${preset} look=${look}
              selected=${preset === avatarLook} color=${avatarColor} onSelect=${onLook} />
          `)}
        </div>
      </fieldset>
      <div class="avatar-color">
        <label for="avatar-color">Avatar color</label>
        <input type="color" id="avatar-color" value=${avatarColor || looks[avatarLook].color}
          onInput=${({ currentTarget }) => onColor(currentTarget.value)} />
        <button type="button" id="avatar-color-reset" disabled=${!avatarColor}
          onClick=${() => onColor("")}>Use preset color</button>
      </div>
    </div>
  `;
}

export function mountAppearance(host, store, { onMode, onFace, applyAppearance }) {
  mountStore(host, store, Appearance, {
    onMode, onFace,
    onLook(avatarLook) {
      store.update({ avatarLook });
      localStorage.setItem("hearth-avatar-look", avatarLook);
      applyAppearance();
    },
    onColor(avatarColor) {
      store.update({ avatarColor });
      if (avatarColor) localStorage.setItem("hearth-avatar-color", avatarColor);
      else localStorage.removeItem("hearth-avatar-color");
      applyAppearance();
    },
  }, ["avatarMode", "avatarLook", "avatarColor"]);
}

const voiceKey = "hearth-voice";
const languages = {
  "auto": "Auto", "en-US": "English", "zh-CN": "中文", "es-ES": "Español", "fr-FR": "Français", "de-DE": "Deutsch",
  "pt-BR": "Português", "it-IT": "Italiano", "ja-JP": "日本語", "ko-KR": "한국어", "ar": "العربية", "hi-IN": "हिन्दी",
};
const callKey = "hearth-voice-call";
const defaultPreferences = { language: "auto", minutes: 10, autoSave: true };

function readCallPreferences() {
  try {
    const saved = JSON.parse(localStorage.getItem(callKey));
    if (saved && ["auto", "en", "zh"].includes(saved.language)
        && Number.isInteger(saved.minutes) && saved.minutes >= 1 && saved.minutes <= 60
        && typeof saved.autoSave === "boolean") return saved;
  } catch {
    // Use the defaults if the saved preferences cannot be read.
  }
  return { ...defaultPreferences };
}

function readVoicePreferences() {
  const preferences = { engine: "auto", language: "auto", autoSend: false, seconds: 60 };
  try {
    const saved = JSON.parse(localStorage.getItem(voiceKey));
    if (["auto", "browser", "whisper"].includes(saved?.engine)) preferences.engine = saved.engine;
    if (Object.hasOwn(languages, saved?.language)) preferences.language = saved.language;
    if (Number.isInteger(saved?.seconds) && saved.seconds >= 5 && saved.seconds <= 120) preferences.seconds = saved.seconds;
    preferences.autoSend = saved?.autoSend === true;
  } catch {
    // Start from the default settings if the saved value is unreadable.
  }
  return preferences;
}


export function readVoiceSettings() {
  return { voicePreferences: readVoicePreferences(), callPreferences: readCallPreferences() };
}

function VoiceSettings({ onSaveCall, onSaveVoice, showEngine, openConnections }) {
  return html`
    <form class="card brain-form voice-settings" id="call-settings-form" onSubmit=${onSaveCall}>
      <fieldset class="preference-fields call-settings-card">
        <legend>Voice calls</legend>
        <div class="call-engine">
          <div><span class="meta">Call engine</span><strong>Vocal Bridge</strong></div>
          <span class="connection-status unknown" id="call-engine-status" role="status">Checking…</span>
        </div>
        <p class="meta" id="call-engine-check"></p>
        <div id="call-setup" class="call-setup" hidden>
          <p>Create and deploy a Vocal Bridge agent with AI Agent Integration set to the client data channel. Add its agent-scoped key in Fly with Name Prefix <code>hearth</code>.</p>
          <button type="button" id="call-connections" onClick=${openConnections}>Open Connections</button>
        </div>
        <div class="field-pair">
          <div>
            <label for="call-language">Call language</label>
            <select id="call-language"><option value="auto">Auto</option><option value="en">English</option><option value="zh">中文</option></select>
          </div>
          <div>
            <label for="call-limit">Max call minutes</label>
            <input type="number" id="call-limit" min="1" max="60" value="10" required />
          </div>
        </div>
        <label class="check-label"><input type="checkbox" id="call-save-transcript" checked /> Auto-save call transcript</label>
        <p class="meta">Hearth replies and actions stay in the thread even when the call transcript is off.</p>
        <div class="preference-actions"><button class="primary-setting" type="submit">Save call settings</button></div>
      </fieldset>
      <p class="meta" id="call-settings-status" role="status"></p>
    </form>
    <form class="card brain-form voice-settings" id="voice-settings-form" onSubmit=${onSaveVoice}>
      <fieldset class="preference-fields">
        <legend>Dictation</legend>
        <div>
          <label for="voice-engine">Transcription engine</label>
          <select id="voice-engine" onChange=${showEngine}>
            <option value="auto">Auto</option>
            <option value="browser">Browser</option>
            <option value="whisper">Hugging Face Whisper</option>
          </select>
          <p class="meta" id="voice-engine-status"></p>
        </div>
        <div class="field-pair">
          <div>
            <label for="voice-language">Language</label>
            <select id="voice-language">
              ${Object.entries(languages).map(([code, label]) => html`<option value=${code}>${label}</option>`)}
            </select>
          </div>
          <div>
            <label for="voice-length">Max recording (seconds)</label>
            <input type="number" id="voice-length" min="5" max="120" value="60" required />
          </div>
        </div>
        <label class="check-label"><input type="checkbox" id="voice-auto-send" /> Send automatically after transcription</label>
        <p class="meta">Whisper uses Hugging Face through your Sprite. Browser uses your browser’s speech service.</p>
        <div class="preference-actions"><button class="primary-setting" type="submit">Save</button></div>
      </fieldset>
      <p class="meta" id="voice-settings-status" role="status"></p>
    </form>
  `;
}

export function createVoiceSettings({ store, byId, api, date, openConnections, whisperConnected }) {
  let callStatusRequest = 0;

  function showEngine() {
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

  async function refreshCall() {
    const request = ++callStatusRequest;
    const badge = byId("call-engine-status");
    const check = byId("call-engine-check");
    try {
      const info = await api("/api/voice/call/status", undefined, AbortSignal.timeout(8000));
      if (request !== callStatusRequest) return;
      badge.textContent = info.configured ? "Connected" : "Not configured";
      badge.className = `connection-status ${info.configured ? "ok" : "not_set_up"}`;
      byId("call-setup").hidden = info.configured;
      const last = info.last_check;
      const outcome = { configured: "Connector found", missing: "No connector found", passed: "Passed", failed: "Failed", denied: "Access denied" };
      const kind = { discovery: "Discovery", token: "Token mint", authorization: "Access check" };
      check.textContent = last ? `${kind[last.kind]} · ${outcome[last.status]} · ${date(last.at)}${last.detail ? ` · ${last.detail}` : ""}` : "";
    } catch {
      if (request !== callStatusRequest) return;
      badge.textContent = "Status unavailable";
      badge.className = "connection-status unknown";
      check.textContent = "";
    }
  }

  render(html`<${VoiceSettings} ...${{
    showEngine, openConnections,
    onSaveVoice(event) {
      event.preventDefault();
      const voicePreferences = {
        engine: byId("voice-engine").value, language: byId("voice-language").value,
        seconds: byId("voice-length").valueAsNumber, autoSend: byId("voice-auto-send").checked,
      };
      store.update({ voicePreferences });
      localStorage.setItem(voiceKey, JSON.stringify(voicePreferences));
      updateText(byId("voice-settings-status"), "Voice settings saved.");
    },
    onSaveCall(event) {
      event.preventDefault();
      const callPreferences = {
        language: byId("call-language").value, minutes: byId("call-limit").valueAsNumber,
        autoSave: byId("call-save-transcript").checked,
      };
      store.update({ callPreferences });
      localStorage.setItem(callKey, JSON.stringify(callPreferences));
      updateText(byId("call-settings-status"), "Call settings saved.");
    },
  }} />`, byId("settings-voice"));

  return {
    showEngine, refreshCall,
    open() {
      const { voicePreferences, callPreferences } = store.state;
      byId("voice-engine").value = voicePreferences.engine;
      byId("voice-language").value = voicePreferences.language;
      byId("voice-length").value = voicePreferences.seconds;
      byId("voice-auto-send").checked = voicePreferences.autoSend;
      byId("call-language").value = callPreferences.language;
      byId("call-limit").value = callPreferences.minutes;
      byId("call-save-transcript").checked = callPreferences.autoSave;
      showEngine();
      return refreshCall();
    },
  };
}
