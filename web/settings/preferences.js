import { render } from "preact";
import { html, Icon } from "../chat/view.js";

import { memoryNames } from "../memory/view.js";

const folderNames = { root: "Profile and approvals", people: "people/", locations: "locations/",
  topics: "Topic notes", projects: "projects/", daily: "daily/" };

function MemoryPreferences() {
  return html`
    <form class="card brain-form memory-review-settings" id="memory-review-settings" aria-labelledby="memory-review-title">
      <h3 id="memory-review-title">Memory review</h3>
      <p class="meta">Hearth collects suggestions for you to review and approve.</p>
      <fieldset disabled>
        <label class="check-label"><input type="checkbox" name="enabled" /> Run nightly</label>
        <div class="memory-review-time">
          <label for="memory-review-time">Time (Pacific)</label>
          <input id="memory-review-time" name="time" type="time" required />
        </div>
        <p class="meta" id="memory-review-next"></p>
        <div class="memory-actions">
          <button class="primary-setting" type="submit" name="save">Save schedule</button>
          <button type="button" name="run"><${Icon} name="play" /> Run now</button>
        </div>
      </fieldset>
      <p class="meta" id="memory-review-settings-status" role="status"></p>
    </form>
    <div class="settings-layout">
      <form class="card brain-form preference-form" id="memory-settings-form">
        <fieldset class="preference-fields" id="memory-fields" disabled>
          <div>
            <label for="memory-backend">Recall store</label>
            <select id="memory-backend" aria-describedby="memory-backend-detail"></select>
            <p class="meta" id="memory-backend-detail"></p>
          </div>
          <div id="memory-model-field" hidden>
            <label for="memory-model">Local embedding model</label>
            <select id="memory-model"></select>
          </div>
          <div class="field-pair">
            <div><label for="memory-top-k">Top-k</label>
              <input id="memory-top-k" type="number" min="1" max="20" required /></div>
            <div><label for="memory-similarity">Min. similarity</label>
              <input id="memory-similarity" type="number" min="0" max="1" step="any" required /></div>
          </div>
          <div>
            <label for="memory-remember">Auto-remember</label>
            <select id="memory-remember">
              <option value="off">Off</option>
              <option value="ask">Ask first</option>
              <option value="automatic">Automatic</option>
            </select>
          </div>
          <label class="check-label"><input id="memory-chat-history" type="checkbox" /> Include chat history from all threads</label>
          <label class="check-label"><input id="memory-summarize-chats" type="checkbox" /> Summarize long chats</label>
          <div class="scope-fields">
            <h3>Recall scope</h3>
            <div id="memory-folders"></div>
          </div>
          <div class="preference-actions"><button class="primary-setting" type="submit">Save</button></div>
        </fieldset>
        <p class="meta" id="memory-feedback" role="status"></p>
      </form>
      <div class="settings-stack">
        <section class="card brain-form utility-card" aria-labelledby="memory-index-title">
          <h3 id="memory-index-title">Pinecone index</h3>
          <dl id="pinecone-index-details" class="memory-index-details"></dl>
          <p class="meta" id="memory-index-status" role="status">Checking index…</p>
          <a class="meta" id="memory-connect" href="#settings/connections" hidden>Open Connections</a>
          <progress id="memory-index-progress" aria-label="Memory index progress" hidden></progress>
          <div class="memory-index-actions">
            <button class="primary-setting" id="memory-sync" type="button" disabled>Sync memories to Pinecone</button>
            <button id="memory-reindex" type="button" disabled>Rebuild index</button>
          </div>
        </section>
        <section class="card brain-form utility-card" aria-labelledby="memory-test-title">
          <h3 id="memory-test-title">Test recall</h3>
          <form id="memory-test-form" class="query-form">
            <label class="visually-hidden" for="memory-test-query">Recall query</label>
            <input type="search" id="memory-test-query" placeholder="Who can’t eat nuts?" maxlength="1000" required />
            <button type="submit" disabled>Test</button>
          </form>
          <div class="field-pair memory-test-filters">
            <div><label for="memory-test-kind">Kind</label><select id="memory-test-kind"></select></div>
            <div><label for="memory-test-thread">Thread</label><select id="memory-test-thread"></select></div>
          </div>
          <div class="query-results" id="memory-test-results" aria-live="polite"></div>
        </section>
      </div>
    </div>
  `;
}

function SearchPreferences() {
  return html`
    <div class="settings-layout">
      <form class="card brain-form preference-form" id="search-settings-form">
        <fieldset class="preference-fields" id="search-fields" disabled>
          <div>
            <label for="search-provider">Search provider</label>
            <select id="search-provider" aria-describedby="search-provider-detail"></select>
            <p class="meta" id="search-provider-detail"></p>
          </div>
          <div class="field-pair">
            <div><label for="search-limit">Max results</label>
              <input id="search-limit" type="number" min="1" max="10" required /></div>
            <div><label for="search-recency">Recency</label>
              <select id="search-recency">
                <option value="any">Any time</option>
                <option value="day">Past day</option>
                <option value="week">Past week</option>
                <option value="month">Past month</option>
                <option value="year">Past year</option>
              </select></div>
          </div>
          <label class="check-label"><input id="search-safe" type="checkbox" /> Safe search</label>
          <p class="meta" id="search-safe-detail" hidden>Hearth applies a basic filter when the provider lacks native Safe Search.</p>
          <div>
            <label for="search-include">Include domains</label>
            <input id="search-include" placeholder="docs.python.org, python.org" maxlength="6000" spellcheck=${false} />
          </div>
          <div>
            <label for="search-exclude">Exclude domains</label>
            <input id="search-exclude" placeholder="example.com" maxlength="6000" spellcheck=${false} />
          </div>
          <div class="preference-actions"><button class="primary-setting" type="submit">Save</button></div>
        </fieldset>
        <p class="meta" id="search-feedback" role="status"></p>
      </form>
      <div class="settings-stack">
        <section class="card brain-form utility-card" aria-labelledby="browsing-settings-title">
          <h3 id="browsing-settings-title">Browserbase</h3>
          <label class="check-label"><input id="allow-browsing" type="checkbox" disabled /> Allow web browsing</label>
          <p class="meta">Use Browserbase to open live pages and capture screenshots.</p>
          <p class="meta" id="browsing-feedback" role="status"></p>
        </section>
        <section class="card brain-form utility-card" aria-labelledby="search-test-title">
          <h3 id="search-test-title">Test search</h3>
          <form id="search-test-form" class="query-form">
            <label class="visually-hidden" for="search-test-query">Search query</label>
            <input type="search" id="search-test-query" placeholder="Python pathlib documentation" maxlength="800" required />
            <button type="submit" disabled>Test</button>
          </form>
          <div class="query-results" id="search-test-results" aria-live="polite"></div>
        </section>
        <section class="card brain-form utility-card" aria-labelledby="search-connectors-title">
          <h3 id="search-connectors-title">Search connections</h3>
          <ul id="search-connections" class="search-connections"></ul>
        </section>
      </div>
    </div>
  `;
}

export function createPreferences({
  byId, api, date, isActive, openConnections, renderRecall, getThreads,
  hasPineconeError, loadReview, refreshState, isBusy, isThreadBusy,
}) {
  render(html`<${MemoryPreferences} />`, byId("settings-memory"));
  render(html`<${SearchPreferences} />`, byId("settings-search"));

  let reindexPoll;
  const preferences = { memory: {}, search: {} };
  function settingOptions(select, options, selected) {
    select.replaceChildren(...options.map(([value, label, disabled]) => {
      const option = new Option(label, value);
      option.disabled = !!disabled && value !== selected;
      return option;
    }));
    select.value = selected;
  }

  function renderMemoryThreadOptions() {
    const select = byId("memory-test-thread");
    settingOptions(select, [["", "All threads"], ...getThreads().map(({ id, title }) => [id, title])], select.value);
  }

  function renderMemoryPreferences(info) {
    const choice = info.selection;
    const stores = choice.backend === "huggingface" ? ["auto", "pinecone", "local", "huggingface"]
      : ["auto", "pinecone", "local"];
    settingOptions(byId("memory-backend"), stores.map((value) => [value, memoryNames[value]]),
      choice.backend === "keyword" ? "local" : choice.backend);
    settingOptions(byId("memory-model"), Object.entries(info.models), choice.model);
    settingOptions(byId("memory-test-kind"), [["", "All kinds"], ...info.kinds.map((kind) =>
      [kind, kind[0].toUpperCase() + kind.slice(1)])], byId("memory-test-kind").value);
    renderMemoryThreadOptions();
    byId("memory-top-k").value = choice.top_k;
    byId("memory-similarity").value = choice.min_similarity;
    byId("memory-chat-history").checked = choice.include_chat;
    byId("memory-summarize-chats").checked = choice.summarize_long_chats;
    byId("memory-remember").value = choice.auto_remember;
    render(html`
      <div class="scope-row"><span>Folder</span><span>Include</span><span>Exclude</span></div>
      ${info.folders.map((folder) => html`
        <div class="scope-row" key=${folder}>
          <span>${folderNames[folder]}</span>
          ${["include", "exclude"].map((field) => html`
            <label class="scope-choice">
              <input type="checkbox" ...${{ [`data-${field}`]: folder }} checked=${choice[field].includes(folder)}
                aria-label=${`${field === "include" ? "Include" : "Exclude"} ${folderNames[folder]}`} />
            </label>
          `)}
        </div>
      `)}
    `, byId("memory-folders"));
    updateMemoryJobs(info);
  }

  function renderSearchPreferences(info) {
    const choice = info.selection;
    const browsing = byId("allow-browsing");
    browsing.checked = info.browsing.allowed;
    browsing.disabled = false;
    const options = info.providers.map((entry) => [entry.provider, entry.connected ? entry.name
      : `${entry.name} · Connect in Connections`, !entry.connected]);
    settingOptions(byId("search-provider"), [["auto", "Auto"], ["off", "Off"], ...options], choice.provider);
    byId("search-limit").value = choice.max_results;
    byId("search-recency").value = choice.recency;
    byId("search-safe").checked = choice.safe_search;
    byId("search-include").value = choice.include_domains.join(", ");
    byId("search-exclude").value = choice.exclude_domains.join(", ");
    render(info.providers.map((entry) => html`
      <li>
        <span>${entry.name}</span>
        ${entry.connected ? html`<span class="meta">Connected</span>` :
          html`<button type="button" onClick=${openConnections}>Connect in Connections</button>`}
      </li>
    `), byId("search-connections"));
  }

  byId("allow-browsing").addEventListener("change", async (event) => {
    const input = event.currentTarget;
    const feedback = byId("browsing-feedback");
    const allowed = input.checked;
    input.disabled = true;
    feedback.textContent = "Saving…";
    try {
      const result = await api("/api/browse/settings", { allowed });
      if (preferences.search.info) preferences.search.info.browsing = result;
      input.checked = result.allowed;
      feedback.textContent = result.allowed ? "Web browsing is on." : "Web browsing is off.";
    } catch (error) {
      input.checked = !allowed;
      feedback.textContent = error.message;
    } finally {
      input.disabled = false;
    }
  });

  function updatePreferenceControls(feature) {
    const { info, pending, indexing } = preferences[feature];
    byId(`${feature}-fields`).disabled = !info || !!pending || !!indexing;
    const test = byId(`${feature}-test-form`).querySelector("button");
    test.disabled = !info || !!pending || !!indexing;
    if (!info) return;
    if (feature === "memory") {
      const backend = byId("memory-backend").value;
      byId("memory-backend-detail").textContent = {
        auto: "Try Pinecone first. Use Local if it’s unavailable or slow.",
        local: "Search the workspace’s notes and saved artifacts offline.",
        huggingface: "Rank local excerpts with Hugging Face embeddings.",
        pinecone: "Search the Pinecone index with Local fallback.",
      }[backend];
      byId("memory-model-field").hidden = backend !== "huggingface";
      byId("memory-similarity").disabled = backend === "local";
      byId("memory-sync").disabled = !!pending || !!preferences.memory.syncing || !info.available.pinecone;
      byId("memory-reindex").disabled = !!pending || !!indexing || !!preferences.memory.syncing;
    } else {
      const provider = byId("search-provider").value;
      const connected = info.providers.filter((entry) => entry.connected);
      const active = provider === "auto" ? connected[0] : connected.find((entry) => entry.provider === provider);
      test.disabled ||= !active;
      byId("search-safe-detail").hidden = !byId("search-safe").checked || !active || active.native_safe;
      byId("search-provider-detail").textContent = provider === "off" ? "Web search is off."
        : active ? provider === "auto" ? `Auto starts with ${active.name}.` : `${active.name} is connected.`
          : "No selected provider is connected. Open Settings → Connections.";
    }
  }

  function updateMemoryJobs({ pinecone, sync, reindex }) {
    clearTimeout(reindexPoll);
    const status = byId("memory-index-status");
    const progress = byId("memory-index-progress");
    const job = pinecone.connected ? sync : reindex;
    preferences.memory.syncing = sync?.status === "running";
    preferences.memory.indexing = reindex?.status === "running";
    const running = job?.status === "running";
    const details = byId("pinecone-index-details");
    const mode = pinecone.integrated && !pinecone.vector_transport ? "integrated" : "dense";
    const synced = pinecone.last_sync ? date(pinecone.last_sync) : "Pending";
    render([
      ["Index", pinecone.name],
      ["Namespace", pinecone.namespace],
      ["Model", pinecone.embedding_model ? `${pinecone.embedding_model} · ${mode}` : undefined],
      ["Dimension", pinecone.dimension],
      ["Records", pinecone.record_count?.toLocaleString()],
      ["Last sync", synced],
    ].flatMap(([label, value]) => html`<dt>${label}</dt><dd>${value ?? "—"}</dd>`), details);

    progress.hidden = !running;
    if (running && (job.work || job.unique)) {
      progress.max = job.work || job.unique;
      progress.value = job.work ? job.upserted + job.deleted : job.embedded + job.reused;
    } else {
      progress.removeAttribute("value");
    }
    if (running) {
      status.textContent = job.phase === "checkpoint" ? "Saving checkpoint…"
        : job.phase === "connecting" ? "Checking the Pinecone connection…"
          : job.work ? `Syncing · ${job.upserted + job.deleted} of ${job.work} changes` : "Checking saved excerpts…";
    } else if (job?.status === "failed") {
      status.textContent = job.error;
    } else if (job && pinecone.connected) {
      status.textContent = `${job.upserted} upserted · ${job.deleted} deleted · ${job.unchanged} unchanged`;
    } else if (job) {
      status.textContent = `Local index · ${job.total} excerpts · ${job.embedded} embedded`;
    } else {
      status.textContent = pinecone.connected ? "Ready to sync memories." : "Pinecone is disconnected.";
    }
    byId("memory-connect").hidden = pinecone.connected && !hasPineconeError();

    updatePreferenceControls("memory");
    if (running && isActive("memory")) {
      reindexPoll = setTimeout(async () => {
        try {
          updateMemoryJobs(await api("/api/memory/reindex"));
        } catch (error) {
          status.textContent = error.message;
          preferences.memory.indexing = false;
          preferences.memory.syncing = false;
          updatePreferenceControls("memory");
        }
      }, 500);
    }
  }

  function readPreferences(feature) {
    if (feature === "search") {
      const domains = (id) => byId(id).value.split(/[\s,]+/).filter(Boolean);
      return { provider: byId("search-provider").value, max_results: byId("search-limit").valueAsNumber,
        recency: byId("search-recency").value, safe_search: byId("search-safe").checked,
        include_domains: domains("search-include"), exclude_domains: domains("search-exclude") };
    }
    const scope = (field) => [...byId("memory-folders").querySelectorAll(`[data-${field}]:checked`)]
      .map((element) => element.dataset[field]);
    return { backend: byId("memory-backend").value, model: byId("memory-model").value,
      top_k: byId("memory-top-k").valueAsNumber, min_similarity: byId("memory-similarity").valueAsNumber,
      include_chat: byId("memory-chat-history").checked, summarize_long_chats: byId("memory-summarize-chats").checked,
      auto_remember: byId("memory-remember").value,
      include: scope("include"), exclude: scope("exclude") };
  }

  async function open(section) {
    if (preferences[section].pending) return;
    if (section === "memory") {
      loadReview();
      if (!isBusy() && !isThreadBusy()) {
        refreshState(undefined, { background: true }).catch(() => {
          // The recall form can still search across all threads.
        });
      }
    }
    try {
      const info = await api(`/api/${section}/settings`);
      if (!isActive(section) || preferences[section].pending) return;
      preferences[section].info = info;
      if (section === "memory") renderMemoryPreferences(info);
      else renderSearchPreferences(info);
      updatePreferenceControls(section);
    } catch (error) {
      byId(`${section}-feedback`).textContent = error.message;
    }
  }

  function renderSearchTest(container, result) {
    const provider = preferences.search.info.providers.find((item) => item.provider === result.provider);
    render(html`
      <p class="meta">${provider?.name || result.provider} · ${result.results.length} results · ${result.latency_ms.toLocaleString()} ms</p>
      ${result.warnings.map((warning) => html`<p class="meta">${warning}</p>`)}
      ${!result.results.length && html`<p class="empty">No search results.</p>`}
      ${result.results.map((hit) => html`
        <article class="result">
          <a class="result-title" href=${hit.url} target="_blank" rel="noreferrer noopener">${hit.title}</a>
          <p class="meta">${hit.published ? `${hit.url} · ${hit.published}` : hit.url}</p>
          ${hit.snippet && html`<p>${hit.snippet}</p>`}
        </article>
      `)}
    `, container);
  }

  async function changePreferences(feature, operation) {
    const state = preferences[feature];
    const form = byId(`${feature}-settings-form`);
    if (!state.info || state.pending || state.indexing || isBusy()) return;
    const indexAction = operation === "reindex" || operation === "sync";
    if (!indexAction && !form.reportValidity()) return;
    const selection = readPreferences(feature);
    const filters = {};
    if (feature === "memory" && operation === "test") {
      const kind = byId("memory-test-kind").value;
      const thread = byId("memory-test-thread").value;
      if (kind) filters.kind = kind;
      if (thread) filters.thread_id = thread;
    }
    const feedback = byId(`${feature}-feedback`);
    const results = byId(`${feature}-test-results`);
    const query = operation === "test" ? byId(`${feature}-test-query`).value.trim() : "";
    if (operation === "test" && !query) return;
    state.pending = operation;
    updatePreferenceControls(feature);
    feedback.textContent = "";
    if (operation === "test") render(html`<p class="meta">Testing…</p>`, results);
    if (operation === "settings") feedback.textContent = "Saving settings…";
    try {
      const result = await api(`/api/${feature}/${operation}`, operation === "test" ? { selection, query, ...filters }
        : indexAction ? {} : selection);
      if (indexAction) {
        updateMemoryJobs(await api("/api/memory/reindex"));
      } else if (operation === "test") {
        if (feature === "memory") renderRecall(results, result);
        else renderSearchTest(results, result);
      } else {
        state.info = result;
        if (feature === "memory") renderMemoryPreferences(result);
        else renderSearchPreferences(result);
        feedback.textContent = "Settings saved.";
      }
    } catch (error) {
      if (operation === "test") render(error.message, results);
      else feedback.textContent = error.message;
    } finally {
      state.pending = undefined;
      updatePreferenceControls(feature);
    }
  }

  for (const feature of ["memory", "search"]) {
    byId(`${feature}-settings-form`).addEventListener("submit", (event) => {
      event.preventDefault();
      changePreferences(feature, "settings");
    });
    byId(`${feature}-settings-form`).addEventListener("change", () => updatePreferenceControls(feature));
    byId(`${feature}-test-form`).addEventListener("submit", (event) => {
      event.preventDefault();
      changePreferences(feature, "test");
    });
  }
  byId("memory-sync").addEventListener("click", () => changePreferences("memory", "sync"));
  byId("memory-reindex").addEventListener("click", () => {
    const connected = preferences.memory.info?.available.pinecone;
    const question = connected ? "Rebuild the Pinecone index for this profile from saved memories?"
      : "Rebuild the local index from saved memories?";
    if (window.confirm(question)) changePreferences("memory", "reindex");
  });

  return {
    open,
    updateThreads: renderMemoryThreadOptions,
    stopPolling() { clearTimeout(reindexPoll); },
  };
}
