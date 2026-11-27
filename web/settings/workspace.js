import { render } from "preact";
import { html, Icon } from "../chat/view.js";

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
const sectionNames = new Set(settingsGroups.flatMap(([, sections]) => sections.map(([section]) => section)));
export const configTabs = ["configured", "not-configured"];

export function settingsHash(section, target) {
  return "#settings" + (section ? `/${section}` : "") + (target ? `/${encodeURIComponent(target)}` : "");
}

export function connectionHash(tab) {
  return settingsHash("connections", tab);
}

export function settingsRoute(hash) {
  if (hash === "#settings") return { view: "settings", hash };
  const [root, ...path] = hash.slice(1).split("/");
  const [section, item, extra] = root === "settings" ? path : [root, ...path];
  if (extra !== undefined || (root !== "settings" && root !== "connections") || !sectionNames.has(section)) return;
  const target = section === "connections" && configTabs.includes(item) ? item : undefined;
  return { view: "settings", section, target, hash: settingsHash(section, target) };
}

function SettingsSections({ active, onSelect }) {
  return settingsGroups.map(([group, sections]) => {
    const groupId = `settings-group-${group.toLowerCase()}`;
    return html`
      <div class="settings-group" role="group" aria-labelledby=${groupId}>
        <p class="settings-group-label" id=${groupId}>${group}</p>
        ${sections.map(([section, title, subtitle, symbol]) => {
          const panel = `settings-${section}`;
          const expanded = active === section;
          return html`
            <div class="settings-entry" key=${section}>
              <h2 class="settings-heading">
                <button type="button" class="settings-disclosure" data-settings=${section}
                  aria-controls=${panel} aria-expanded=${String(expanded)}
                  aria-labelledby=${panel + "-title"} aria-describedby=${panel + "-subtitle"}
                  onClick=${() => onSelect(expanded ? undefined : section)}>
                  <${Icon} name=${symbol} /><span class="settings-label">
                    <span class="settings-title" id=${panel + "-title"}>${title}</span>
                    <span class="settings-subtitle" id=${panel + "-subtitle"}>${subtitle}</span>
                  </span><${Icon} name="chevron" size=${18} />
                </button>
              </h2>
              <div class="settings-body" id=${panel} hidden=${!expanded}></div>
            </div>
          `;
        })}
      </div>
    `;
  });
}

export function createSettings(onSelect, { api, renderRefreshStatus }) {
  const host = document.getElementById("settings-sections");
  const panels = [...host.children];
  let active;
  function paint() {
    render(html`<${SettingsSections} active=${active} onSelect=${onSelect} />`, host);
  }
  host.replaceChildren();
  paint();
  for (const panel of panels) document.getElementById(panel.id).append(...panel.childNodes);
  render(html`
    <div class="card">
      <p>Deployed commit</p>
      <p><code id="hearth-version" class="self-update-version">Checking…</code></p>
    </div>
  `, document.getElementById("settings-about"));

  return {
    get section() { return active; },
    async open(section, focus, load) {
      active = section;
      paint();
      renderRefreshStatus();
      if (!section) return;
      const control = host.querySelector(`[data-settings="${section}"]`);
      control.scrollIntoView({ block: "nearest" });
      if (focus) {
        const previous = control.closest(".settings-entry").previousElementSibling;
        (previous.matches(".settings-group-label") ? previous : control).scrollIntoView({ block: "start" });
        control.focus({ preventScroll: true });
      }
      if (section === "about") {
        const version = document.getElementById("hearth-version");
        try {
          version.textContent = (await api("/health")).version || "Local checkout";
        } catch (error) {
          version.textContent = error.message;
        }
        return;
      }
      return load(section);
    },
  };
}
