import { render } from "preact";
import { useRef } from "preact/hooks";
import { html, Icon } from "../chat/view.js";
import { configTabs, connectionHash } from "./workspace.js";

const connectorFields = {
  pinecone: { field: "index", label: "Index name", placeholder: "hearth-memory", maxLength: 45 },
  agentmail: { field: "inbox_id", label: "Inbox ID", placeholder: "your-inbox@agentmail.to", maxLength: 254 },
};
const tabStorage = "hearth-connections-tab";
const labels = {
  ok: "OK", ready: "Ready", checking: "Checking", error: "Error", untested: "Untested", unauthorized: "Found but not authorized",
  not_set_up: "Not set up", unknown: "Not checked", not_used: "Not used by Hearth",
};

export function connectorHasError(entry) {
  return entry?.uses.length > 0 && (entry.status === "unauthorized" || ["failed", "denied"].includes(entry.test_status)
    || entry.index_state === "Unavailable");
}

function ConnectorForm({ provider, entry, info, drafts, update }) {
  const id = `connection-${provider}`;
  return html`
    <form class="connector-settings" onSubmit=${(event) => {
      event.preventDefault();
      update("settings", { provider, value: event.currentTarget.querySelector("input").value });
    }}>
      <label for=${id}>${info.label}</label>
      <div class="connector-controls">
        <input id=${id} type=${info.field === "inbox_id" ? "email" : "text"} required=${info.field === "index"}
          maxlength=${info.maxLength} autocomplete="off" spellcheck=${false} placeholder=${info.placeholder}
          value=${drafts.get(provider) ?? entry.settings[info.field]}
          onInput=${({ currentTarget }) => drafts.set(provider, currentTarget.value)} />
        <button type="submit" aria-label=${`Save ${entry.name} settings`}>Save</button>
      </div>
    </form>
  `;
}

function GitHubSettings({ settings, save }) {
  const toggleChanged = useRef(false);
  return html`
    <form class="self-update-settings" onSubmit=${async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const [repository, required, enabled] = form.elements;
      const body = { repository: repository.value.trim(), enabled: enabled.checked,
        required_checks: required.value.split(",").map((name) => name.trim()) };
      for (const control of form.elements) control.disabled = true;
      try {
        await save(body);
      } catch (error) {
        form.querySelector("[role=status]").textContent = error.message;
      } finally {
        for (const control of form.elements) control.disabled = false;
      }
    }}>
      <label>Repository<input type="text" maxlength="140" required spellcheck=${false} autocapitalize="none"
        defaultValue=${settings.repository} onInput=${({ currentTarget }) => {
          if (toggleChanged.current) return;
          const target = currentTarget.value.trim().toLowerCase();
          currentTarget.form.elements[2].checked =
            target === settings.repository.toLowerCase() ? settings.enabled : target === "xuefeng-zhu/hearth";
        }} /></label>
      <label>Required CI jobs (comma-separated)<input type="text" maxlength="2040" required spellcheck=${false}
        autocapitalize="none" defaultValue=${settings.required_checks.join(", ")} /></label>
      <label class="self-update-toggle"><input type="checkbox" defaultChecked=${settings.enabled}
        onChange=${() => { toggleChanged.current = true; }} />Allow Hearth to propose changes to itself</label>
      <button>Save GitHub settings</button>
      <p class="self-update-detail" role="status"></p>
    </form>
  `;
}

function ConnectionCard({ provider, entry, promoted, github, githubRevision, drafts, update, test, saveGitHub }) {
  const configured = entry.status === "connected";
  const used = entry.uses.length > 0;
  const check = connectorHasError(entry) ? "error"
    : entry.index_state === "Ready" ? "ready" : entry.index_state === "Connecting" ? "checking"
      : entry.test_status === "passed" ? "ok" : entry.test_status ? "error" : "untested";
  const status = used ? (configured ? check : entry.status) : "not_used";
  const tone = status === "ready" ? "ok" : status === "checking" ? "untested" : status;
  const fly = configured ? "Open in Fly" : entry.status === "unauthorized" ? "Review in Fly" : "Add in Fly";
  const info = Object.hasOwn(connectorFields, provider) && connectorFields[provider];
  return html`
    <article class=${promoted ? "card connection-card newly-configured" : "card connection-card"} data-provider=${provider}>
      <div class="card-header"><h4>${entry.name}</h4><span class=${`connection-status ${tone}`}>${labels[status]}</span></div>
      ${entry.auth && html`<p class="meta">${entry.auth}</p>`}
      <p class="connection-description">${entry.description}</p>
      ${configured && used && html`<p class="connection-uses"><strong>Used for</strong>${` ${entry.uses.join(" · ")}`}</p>`}
      ${info && html`<${ConnectorForm} ...${{ provider, entry, info, drafts, update }} />`}
      ${provider === "github" && github && html`<${GitHubSettings} key=${githubRevision} settings=${github} save=${saveGitHub} />`}
      ${entry.index_error ? html`<p class="connection-test failed">${entry.index_error}</p>` : entry.test_detail &&
        html`<p class=${used ? `connection-test ${entry.test_status}` : "meta"}>${entry.test_detail}</p>`}
      <div class="connector-footer">
        <span class="connector-access">${entry.access_rule}</span>
        <div class="connector-links">
          ${[[fly, entry.dashboard_url], ["Docs", entry.docs_url]].map(([label, url]) => html`
            <a href=${url ?? ""} target="_blank" rel="noopener noreferrer">${label}${url && html`${" "}<${Icon} name="external" size=${14} />`}</a>
          `)}
          ${entry.can_test && html`<button type="button" id=${`test-connection-${provider}`} aria-label=${`Test ${entry.name}`}
            title=${entry.test_path ? null : "Check gateway authorization."} onClick=${() => test(provider)}>Test</button>`}
        </div>
      </div>
    </article>
  `;
}

function Connections({ selectTab, update }) {
  return html`
    <div class="settings-actions">
      <p class="meta" id="connection-notice" role="status">Checking connections…</p>
      <button type="button" class="settings-button" id="rescan-connections" onClick=${() => update("rescan")}>Refresh</button>
    </div>
    <section id="email-hearth-connection" class="card email-hearth-card" aria-label="Email Hearth"></section>
    <div class="connection-tabs" id="connection-tabs" role="tablist" aria-label="Connector configuration">
      ${configTabs.map((tab, index) => html`
        <button type="button" id=${tab + "-tab"} data-connection-tab=${tab} role="tab" aria-controls=${tab + "-panel"}
          aria-selected=${String(!!index)} tabindex=${index ? null : -1} onClick=${() => selectTab(tab)}
          onKeyDown=${(event) => {
            const other = configTabs[1 - index];
            const target = { ArrowLeft: other, ArrowRight: other, Home: configTabs[0], End: configTabs[1] }[event.key];
            if (!target) return;
            event.preventDefault();
            selectTab(target);
          }}>
          ${index ? "Not configured " : "Configured "}<span class="connection-badge" hidden></span>
        </button>
      `)}
    </div>
    <p class="connection-promotion" id="connection-promotion" role="status" hidden></p>
    <section id="configured-panel" role="tabpanel" aria-labelledby="configured-tab" tabindex="0" hidden></section>
    <section id="not-configured-panel" role="tabpanel" aria-labelledby="not-configured-tab" tabindex="0">
      <p class="connection-setup">Add a connector in the Fly dashboard. Turn off <strong>Allow all sprites</strong>, set <strong>Name Prefix</strong> to <strong>hearth</strong>, then click <strong>Refresh</strong> here.</p>
    </section>
    <template id="connection-content"></template>
  `;
}

function ConnectionFilters() {
  return html`
    <div class="connection-filters">
      <label>Search providers<input type="search" placeholder="Name or capability" autocomplete="off" /></label>
      <label>Category<select><option value="">All categories</option></select></label>
    </div>
    <div class="connection-summary" role="status">
      <p class="empty connection-count"></p><a class="connection-match-link" hidden></a>
    </div>
    <div class="connection-groups"></div>
  `;
}

export function createConnections({ byId, api, date, trackRefresh, refreshAPI, isActive, onData, onUpdate, loadMail, pollMail }) {
  const connectionPanels = new Map();
  const connectionDrafts = new Map();
  let connectionState;
  let connectionRequest;
  let connectionTabPreference = localStorage.getItem(tabStorage);
  let newlyConfigured = new Set();
  let githubRevision = 0;

  function selectConnectionTab(tab) {
    rememberTab(tab);
    if (location.hash !== connectionHash(tab)) history.pushState(history.state, "", connectionHash(tab));
    renderConnections();
    connectionPanels.get(tab).button.focus();
  }

  function rememberTab(tab) {
    connectionTabPreference = tab;
    localStorage.setItem(tabStorage, tab);
  }

  function applyConnections(data) {
    connectionState = data;
    renderConnections();
    onData(data);
  }

  function renderConnections() {
    const entries = Object.entries(connectionState?.providers ?? {});
    const configured = entries.filter(([, entry]) => entry.status === "connected");
    const unconfigured = entries.filter(([, entry]) => entry.status !== "connected");
    const providersByTab = { configured, "not-configured": unconfigured };
    const defaultTab = configured.length ? "configured" : "not-configured";
    const activeConnectionTab = configTabs.includes(connectionTabPreference) ? connectionTabPreference : defaultTab;
    if (isActive() && location.hash === connectionHash()
        && (connectionState || connectionTabPreference === activeConnectionTab)) {
      history.replaceState(history.state, "", connectionHash(activeConnectionTab));
    }

    const categories = [...new Set(entries.map(([, entry]) => entry.category))].sort();
    for (const [tab, controls] of connectionPanels) {
      const selected = tab === activeConnectionTab;
      controls.button.setAttribute("aria-selected", String(selected));
      controls.button.tabIndex = selected ? 0 : -1;
      controls.badge.hidden = !connectionState;
      controls.badge.textContent = providersByTab[tab].length;
      controls.panel.hidden = !selected;
      if (!selected) render(null, controls.groups);
      const filter = controls.filter;
      if (categories.join("|") !== filter.dataset.categories) {
        const category = filter.value;
        filter.replaceChildren(new Option("All categories", ""), ...categories.map((name) => new Option(name, name)));
        filter.value = categories.includes(category) ? category : "";
        filter.dataset.categories = categories.join("|");
      }
    }
    if (!connectionState) return;

    const controls = connectionPanels.get(activeConnectionTab);
    const terms = controls.search.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const matchesFilters = ([provider, entry]) => {
      if (controls.filter.value && controls.filter.value !== entry.category) return false;
      const searchable = [provider, entry.gateway_provider, entry.name, entry.category, entry.auth, entry.description,
        ...entry.uses].join(" ").toLowerCase();
      return terms.every((term) => searchable.includes(term));
    };
    const active = providersByTab[activeConnectionTab];
    const matches = active.filter(matchesFilters);
    const otherTab = configTabs.find((tab) => tab !== activeConnectionTab);
    const otherMatches = terms.length ? providersByTab[otherTab].filter(matchesFilters).length : 0;
    controls.count.textContent = matches.length ? `${matches.length} of ${active.length} providers`
      : active.length ? "No providers match your filters."
      : activeConnectionTab === "configured" ? "No configured connectors yet." : "All providers are configured.";
    controls.link.hidden = !otherMatches;
    controls.link.href = connectionHash(otherTab);
    controls.link.textContent = `${otherMatches} ${otherMatches === 1 ? "match" : "matches"} in the other tab`;
    render(connectionGroups(matches), controls.groups);
    if (connectionRequest) setConnectionsBusy(true);
  }

  function connectionGroups(entries) {
    const groups = new Map();
    const unused = [];
    for (const [provider, entry] of entries) {
      const card = html`<${ConnectionCard} key=${provider} ...${{
        provider, entry, promoted: newlyConfigured.delete(provider), github: connectionState.self_update, githubRevision,
        drafts: connectionDrafts, update: updateConnections, test, saveGitHub,
      }} />`;
      if (!entry.uses.length) {
        unused.push(card);
        continue;
      }
      const group = entry.pinned ? "Hearth essentials" : entry.category;
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group).push(card);
    }
    if (unused.length) groups.set("Available, not used", unused);
    return [...groups].map(([name, cards]) => html`
      <section class="connection-section" key=${name}>
        <h3>${name}</h3><div class="connection-grid">${cards}</div>
      </section>
    `);
  }

  async function test(provider) {
    await updateConnections("test", { provider });
    if (isActive() && document.activeElement === document.body) byId(`test-connection-${provider}`)?.focus();
  }

  async function saveGitHub(settings) {
    const result = await api("/api/self-update/settings", settings);
    githubRevision += 1;
    applyConnections(result);
    byId("connection-notice").textContent = "GitHub settings saved.";
    document.querySelector('[data-provider="github"] input')?.focus();
  }

  function setConnectionsBusy(value) {
    byId("rescan-connections").setAttribute("aria-disabled", String(value));
    for (const control of byId("settings-connections").querySelectorAll(".connection-grid button, .connection-grid input")) {
      control.disabled = value;
    }
  }

  function announceNewConnections(previous, current) {
    const promoted = Object.entries(current.providers).filter(([provider, entry]) =>
      entry.status === "connected" && previous.providers[provider]?.status !== "connected");
    newlyConfigured = new Set(promoted.map(([provider]) => provider));
    const notice = byId("connection-promotion");
    notice.hidden = !promoted.length;
    const names = promoted.map(([, entry]) => entry.name);
    render(names.length ? html`
      ${names.length === 1 ? `${names[0]} moved to Configured. ` : `${names.length} connectors moved to Configured. `}
      <a href=${connectionHash("configured")} onClick=${(event) => {
        event.preventDefault();
        const controls = connectionPanels.get("configured");
        controls.search.value = controls.filter.value = "";
        selectConnectionTab("configured");
      }}>Show configured</a>
    ` : null, notice);
  }

  function updateConnections(operation, body = {}) {
    if (connectionRequest) return connectionRequest;
    const feedback = byId("connection-notice");
    const name = connectionState?.providers[body.provider]?.name;
    feedback.textContent = { rescan: "Checking connections…", test: `Testing ${name}…`, settings: "Saving settings…" }[operation];
    setConnectionsBusy(true);
    connectionRequest = (async () => {
      try {
        const previous = connectionState;
        const data = await trackRefresh("/api/connections", false, () => api(`/api/connections/${operation}`, body));
        if (operation === "rescan" && previous && !data.scan_error) {
          announceNewConnections(previous, data);
        }
        if (operation === "settings") connectionDrafts.delete(body.provider);
        applyConnections(data);
        onUpdate();
        const entry = connectionState.providers[body.provider];
        feedback.textContent = {
          rescan: connectionState.scan_error || `Last checked ${date(connectionState.last_scan)}.`,
          test: entry ? `${name} · ${entry.test_detail}` : "",
          settings: `${name} settings saved.`,
        }[operation];
      } catch (error) {
        feedback.textContent = error.message;
        if (!connectionState) {
          try {
            applyConnections(await refreshAPI("/api/connections"));
          } catch {
            // The request message remains visible until a re-scan succeeds.
          }
        }
      } finally {
        connectionRequest = undefined;
        setConnectionsBusy(false);
      }
    })();
    return connectionRequest;
  }

  async function refreshPineconeHealth() {
    const previous = connectionState;
    const entry = previous?.providers.pinecone;
    if (connectionRequest || entry?.status !== "connected" ||
        (entry.index_state === "Ready" && !connectorHasError(entry))) return;
    const data = await refreshAPI("/api/connections", { background: true, signal: AbortSignal.timeout(6000) });
    if (isActive() && !connectionRequest && connectionState === previous &&
        JSON.stringify(data.providers.pinecone) !== JSON.stringify(entry)) {
      applyConnections(data);
    }
  }

  render(html`<${Connections} selectTab=${selectConnectionTab} update=${updateConnections} />`, byId("settings-connections"));
  render(html`<${ConnectionFilters} />`, byId("connection-content").content);
  for (const tab of configTabs) {
    const panel = byId(`${tab}-panel`);
    panel.append(byId("connection-content").content.cloneNode(true));
    const controls = {
      panel, button: byId(`${tab}-tab`), badge: byId(`${tab}-tab`).querySelector(".connection-badge"),
      search: panel.querySelector("input"), filter: panel.querySelector("select"),
      count: panel.querySelector(".connection-count"), link: panel.querySelector(".connection-match-link"),
      groups: panel.querySelector(".connection-groups"),
    };
    connectionPanels.set(tab, controls);
    controls.search.addEventListener("input", renderConnections);
    controls.filter.addEventListener("change", renderConnections);
    controls.link.addEventListener("click", (event) => {
      event.preventDefault();
      const otherTab = configTabs.find((item) => item !== tab);
      const other = connectionPanels.get(otherTab);
      other.search.value = controls.search.value;
      other.filter.value = controls.filter.value;
      selectConnectionTab(otherTab);
    });
  }

  return {
    get state() { return connectionState; },
    get request() { return connectionRequest; },
    syncTab(tab) {
      if (tab) rememberTab(tab);
      if (!isActive()) return false;
      renderConnections();
      return true;
    },
    async open() {
      renderConnections();
      const mail = loadMail();
      await updateConnections("rescan");
      await mail;
      if (isActive()) pollMail();
    },
    update: updateConnections,
    refreshHealth: refreshPineconeHealth,
  };
}
