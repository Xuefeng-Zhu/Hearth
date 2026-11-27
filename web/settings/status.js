import { render } from "preact";
import { html } from "../ui.js";
import { node, updateText } from "../dom.js";
import { connectionHash } from "./routes.js";

export const modelNames = {
  mock: "Mock", meta: "Muse Spark", openrouter: "OpenRouter", openai: "OpenAI", anthropic: "Claude",
  gemini: "Gemini", ollama: "Ollama Cloud", huggingface: "Hugging Face", digitalocean: "DigitalOcean Inference",
  fireworks: "Fireworks", nscale: "Nscale", parasail: "Parasail", zerogpu: "ZeroGPU", echo: "Echo by Fulcrum",
};

export function connectorHasError(entry) {
  return entry?.uses.length > 0 && (entry.status === "unauthorized" || ["failed", "denied"].includes(entry.test_status)
    || entry.index_state === "Unavailable");
}

const connectionsLabel = "Settings → Connections";

export function showConnectionGuidance(target, message) {
  const start = message.indexOf(connectionsLabel);
  if (start === -1) {
    target.textContent = message;
    return;
  }
  const link = node("a", "connection-guidance", connectionsLabel);
  link.href = connectionHash();
  target.replaceChildren(message.slice(0, start), link, message.slice(start + connectionsLabel.length));
}

function Status({ text, warning, openConnections }) {
  return html`<span class="dot" aria-hidden="true"></span><span data-workspace-status="" hidden=${!text}>${text}</span><a
    href=${connectionHash()} data-connection-warning="" hidden=${!warning}
    onClick=${(event) => { event.preventDefault(); openConnections(); }}>Check connections</a>`;
}

export function createWorkspaceStatus({ byId, isHome, openConnections }) {
  const hosts = document.querySelectorAll(".workspace-status");
  let model, modelLabel;
  function paintModel() {
    const active = byId("brain-active-model");
    if (active && modelLabel) updateText(active, modelLabel);
  }
  let providers;
  let connectorError = false;
  let homeError = false;

  function paint() {
    const warning = navigator.onLine && (connectorError || (isHome() && homeError));
    const text = !navigator.onLine ? "Offline" : !warning && model === "mock" ? "Mock mode" : "";
    for (const host of hosts) {
      render(html`<${Status} text=${text} warning=${warning} openConnections=${openConnections} />`, host);
      host.hidden = !text && !warning;
    }
  }

  function updateModel({ model: provider, model_id: id }) {
    model = provider;
    const name = modelNames[provider] || providers?.[provider]?.name || provider || "Unavailable";
    modelLabel = id && provider !== "mock" ? `${name} · ${id}` : name;
    paintModel();
    paint();
  }

  return {
    paint, paintModel, updateModel,
    updateConnections(data) {
      providers = data.providers;
      connectorError = !!data.scan_error || Object.values(providers).some(connectorHasError);
      updateModel(data);
    },
    updateHome(data) {
      const { error, items } = data.builtin.connections;
      homeError = !!error || items.some((entry) => entry.status === "error");
      updateModel(data);
    },
  };
}
