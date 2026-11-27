import { render } from "preact";
import { html, Icon } from "../ui.js";
import { showLoading } from "../motion.js";
import { settingsGroups } from "./routes.js";

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
  let active;
  function paint() {
    render(html`<${SettingsSections} active=${active} onSelect=${onSelect} />`, host);
  }
  paint();
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
      if (!load) return;
      const panel = document.getElementById(`settings-${section}`);
      const status = panel.childElementCount ? null : document.createElement("p");
      if (status) {
        status.className = "meta";
        status.setAttribute("role", "status");
        panel.append(showLoading(status, "Loading settings…"));
      }
      try {
        return await load();
      } finally {
        status?.remove();
      }
    },
  };
}
