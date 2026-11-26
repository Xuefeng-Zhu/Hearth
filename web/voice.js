const recordTypes = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/ogg", "audio/mp4"];

const captureErrors = {
  NotAllowedError: "Microphone permission was denied. Allow access in your browser and try again.",
  SecurityError: "Microphone permission was denied. Allow access in your browser and try again.",
  NotFoundError: "No microphone was found. Connect a microphone and try again.",
  NotReadableError: "Hearth could not open the microphone. Check whether another app is using it.",
};
const recognitionErrors = {
  "not-allowed": captureErrors.NotAllowedError,
  "service-not-allowed": "The browser blocked its speech recognition service. Try Whisper in Settings → Voice.",
  "audio-capture": captureErrors.NotFoundError,
  "language-not-supported": "Browser speech recognition does not support this language.",
  "no-speech": "No speech was detected. Try speaking closer to the microphone.",
  network: "The browser’s speech recognition service is unavailable. Try Whisper in Settings → Voice.",
};

async function transcriptResponse(path, options) {
  const response = await fetch(path, options);
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.text) {
    throw new Error(result.error || "Hearth could not transcribe this recording.");
  }
  return result.text;
}

export function createVoiceInput({ update, meter, deliver }) {
  let active;

  function report(session, phase, interim = "") {
    session.phase = phase;
    update({ thread: session.thread, phase, interim, engine: session.engine });
  }

  function releaseMicrophone(session) {
    clearTimeout(session.limit);
    cancelAnimationFrame(session.frame);
    session.stream?.getTracks().forEach((track) => track.stop());
    session.stream = undefined;
    if (session.context && session.context.state !== "closed") {
      session.context.close().catch(() => {});
    }
    session.context = undefined;
  }

  function finish(session, { text, message } = {}) {
    if (session !== active) return;
    active = undefined;
    clearTimeout(session.finalLimit);
    clearTimeout(session.uploadLimit);
    session.controller.abort();
    try {
      if (session.recorder?.state === "recording") session.recorder.stop();
      if (session.recognizer && !session.ended) session.recognizer.abort();
    } catch {
      // The browser may have already closed the capture session.
    }
    releaseMicrophone(session);
    update({ thread: session.thread, phase: "idle", message });
    if (text) deliver({ thread: session.thread, text, autoSend: session.autoSend });
  }

  function watchLevel(session) {
    if (!session.context) return;
    const source = session.context.createMediaStreamSource(session.stream);
    const analyser = session.context.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);
    const samples = new Float32Array(analyser.fftSize);
    let level = 0;
    function sample() {
      if (session !== active || session.phase !== "recording") return;
      analyser.getFloatTimeDomainData(samples);
      let energy = 0;
      for (const value of samples) energy += value * value;
      const current = Math.min(1, Math.sqrt(energy / samples.length) * 5);
      level = Math.max(current, level * .88);
      meter(level);
      session.frame = requestAnimationFrame(sample);
    }
    sample();
  }

  async function transcribe(session, path, options) {
    if (session !== active) return;
    releaseMicrophone(session);
    report(session, "processing");
    session.uploadLimit = setTimeout(() => finish(session, { message: "Transcription timed out. Try a shorter recording." }), 65_000);
    try {
      const text = await transcriptResponse(path, { ...options, method: "POST", signal: session.controller.signal });
      finish(session, { text });
    } catch (error) {
      const message = error instanceof TypeError ? "Hearth could not reach the transcription service." : error.message;
      finish(session, { message });
    }
  }

  function startWhisper(session, mime) {
    const recorder = new MediaRecorder(session.stream, { mimeType: mime, audioBitsPerSecond: 32_000 });
    session.recorder = recorder;
    const chunks = [];
    recorder.ondataavailable = (event) => {
      if (session === active && event.data.size) chunks.push(event.data);
    };
    recorder.onerror = () => finish(session, { message: "Hearth could not record audio in this browser." });
    recorder.onstop = () => {
      if (session !== active) return;
      const recording = new Blob(chunks, { type: recorder.mimeType || mime });
      chunks.length = 0;
      if (!recording.size) {
        finish(session, { message: "No audio was recorded. Try holding the microphone open a little longer." });
        return;
      }
      const language = session.language.split("-")[0];
      const params = new URLSearchParams({ language, thread: session.thread });
      transcribe(session, `/api/voice/transcribe?${params}`, {
        body: recording, headers: { "Content-Type": recording.type },
      });
    };
    recorder.start();
  }

  function startBrowser(session, Recognition) {
    const recognition = new Recognition();
    session.recognizer = recognition;
    recognition.continuous = true;
    recognition.interimResults = true;
    if (session.language !== "auto") recognition.lang = session.language;
    let final = "";
    recognition.onresult = (event) => {
      if (session !== active) return;
      final = "";
      let interim = "";
      for (const result of event.results) {
        if (result.isFinal) final += `${result[0].transcript.trim()} `;
        else interim += `${result[0].transcript.trim()} `;
      }
      if (session.phase === "recording") report(session, "recording", `${final}${interim}`.trim());
    };
    recognition.onerror = (event) => {
      if (event.error === "no-speech" && final.trim()) return;
      finish(session, { message: recognitionErrors[event.error] || "Browser speech recognition stopped. Try again." });
    };
    recognition.onend = () => {
      session.ended = true;
      clearTimeout(session.finalLimit);
      if (session !== active) return;
      if (!final.trim()) {
        finish(session, { message: recognitionErrors["no-speech"] });
        return;
      }
      transcribe(session, `/api/voice/redact?thread=${encodeURIComponent(session.thread)}`, {
        body: JSON.stringify({ text: final.trim().slice(0, 4000) }), headers: { "Content-Type": "application/json" },
      });
    };
    recognition.start();
  }

  function stop() {
    const session = active;
    if (!session) return;
    if (session.phase !== "recording") {
      finish(session);
      return;
    }
    report(session, "processing");
    try {
      if (session.recorder?.state === "recording") session.recorder.stop();
      if (session.recognizer) {
        session.recognizer.stop();
        session.finalLimit = setTimeout(() => finish(session, { message: "Browser speech recognition timed out." }), 12_000);
      }
    } catch {
      finish(session, { message: "The browser closed the microphone before transcription." });
    }
    releaseMicrophone(session);
  }

  async function start(thread, preferences, connected) {
    if (active) return;
    const engine = preferences.engine === "auto" ? (connected ? "whisper" : "browser") : preferences.engine;
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const mime = engine === "whisper" && window.MediaRecorder
      ? recordTypes.find((type) => MediaRecorder.isTypeSupported(type)) : "";
    let unsupported;
    if (!window.isSecureContext) unsupported = "Voice input requires HTTPS or localhost.";
    else if (engine === "whisper" && !connected) unsupported = "Connect Hugging Face in Settings → Connections to use Whisper.";
    else if (engine === "whisper" && !mime) unsupported = "This browser cannot record audio for Whisper. Try Browser in Settings → Voice.";
    else if (engine === "browser" && !Recognition) unsupported = "This browser does not support speech recognition. Connect Hugging Face to use Whisper.";
    else if (!navigator.mediaDevices?.getUserMedia) unsupported = "Microphone capture is unavailable in this browser.";
    if (unsupported) {
      update({ thread, phase: "idle", message: unsupported });
      return;
    }
    const session = { ...preferences, thread, engine, controller: new AbortController() };
    active = session;
    report(session, "requesting");
    const Audio = window.AudioContext || window.webkitAudioContext;
    try {
      if (Audio) {
        session.context = new Audio();
        session.context.resume().catch(() => {});
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 }, video: false });
      if (session !== active) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      session.stream = stream;
      if (engine === "whisper") startWhisper(session, mime);
      else startBrowser(session, Recognition);
      report(session, "recording");
      session.limit = setTimeout(stop, session.seconds * 1000);
      watchLevel(session);
    } catch (error) {
      finish(session, { message: captureErrors[error.name] || "Hearth could not start the microphone." });
    }
  }

  return { start, stop, get active() { return !!active; }, cancel() { if (active) finish(active); } };
}
