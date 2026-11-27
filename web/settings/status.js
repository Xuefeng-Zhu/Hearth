import { render } from "preact";
import { html } from "../chat/view.js";
import { node, updateText } from "../dom.js";
import { modelNames } from "./brain.js";
import { connectorHasError } from "./connections.js";
import { connectionHash } from "./workspace.js";

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
  let model;
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
    updateText(byId("brain-active-model"), id && provider !== "mock" ? `${name} · ${id}` : name);
    paint();
  }

  return {
    paint, updateModel,
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
