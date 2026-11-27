import { render } from "preact";
import { showLoading } from "../motion.js";
import { html } from "../ui.js";
import { modelNames } from "./status.js";

const poolFields = [
  ["speed", "Speed", ["slow", "balanced", "fast"]],
  ["cost", "Cost tier", ["low", "medium", "high"]],
  ["tools", "Tool reliability", ["low", "medium", "high"]],
];

function PoolEntry({ model, entry, summary, stats, date, onChange, onRemove }) {
  const tags = entry.tags;
  let performance;
  if (stats) {
    const latency = stats.p50_ms === null ? "" : `${stats.p50_ms.toLocaleString()} ms median · `;
    const failure = stats.last_failure === null ? "" : ` · Last failure ${date(stats.last_failure * 1000)}`;
    performance = `${latency}${Math.round(stats.error_rate * 100)}% errors${failure}`;
  }
  function tag(key, read) {
    return ({ currentTarget }) => {
      if (!currentTarget.reportValidity()) return;
      tags[key] = read(currentTarget);
      onChange();
    };
  }
  return html`
    <details class="pool-entry" data-model=${model}>
      <summary>${summary}</summary>
      ${stats && html`<p class="meta">${performance}</p>`}
      <div class="pool-tags">
        ${poolFields.map(([key, label, values]) => html`
          <label>${label}<select value=${tags[key]} onChange=${tag(key, (field) => field.value)}>
            ${values.map((value) => html`<option value=${value}>${value}</option>`)}
          </select></label>
        `)}
        <label>Context (tokens)<input type="number" min="1" max="10000000" required
          value=${tags.context} onChange=${tag("context", (field) => field.valueAsNumber)} /></label>
        <label class="check-label"><input type="checkbox" checked=${tags.multilingual}
          onChange=${tag("multilingual", (field) => field.checked)} />Multilingual</label>
      </div>
      <button type="button" aria-label=${`Remove ${entry.model}`} onClick=${onRemove}>Remove model</button>
    </details>
  `;
}

function Brain() {
  return html`
    <p class="brain-active meta"><strong>Active model</strong> <span id="brain-active-model">Checking…</span></p>
    <div class="settings-layout">
      <form class="card brain-form" id="brain-form">
        <label for="brain-provider">Routing mode</label>
        <select id="brain-provider" aria-describedby="brain-provider-detail" disabled>
          <option value="priority">Auto (priority)</option>
        </select>
        <p class="meta" id="brain-provider-detail">Checking connections…</p>
        <div id="brain-model-fields" hidden>
          <label for="brain-model">Model</label>
          <select id="brain-model" aria-describedby="brain-model-detail"></select>
          <div id="brain-custom-field" hidden>
            <label for="brain-custom">Custom model ID</label>
            <input type="text" id="brain-custom" maxlength="150" autocomplete="off" spellcheck=${false} placeholder="Enter a model ID" />
          </div>
          <p class="meta" id="brain-model-detail" role="status"></p>
        </div>
        <label for="brain-workers">Parallel workers</label>
        <select id="brain-workers" aria-describedby="brain-workers-detail" disabled>
          <option value="1">1 worker</option>
          <option value="2">2 workers</option>
          <option value="3">3 workers</option>
          <option value="4" selected>4 workers</option>
          <option value="5">5 workers</option>
          <option value="6">6 workers</option>
        </select>
        <p class="meta" id="brain-workers-detail">Maximum running at once across chats and recurring tasks.</p>
        <fieldset id="brain-pool" hidden>
          <legend>Routing pool</legend>
          <div id="brain-pool-rows"></div>
          <div class="field-pair pool-add">
            <div>
              <label for="pool-provider">Provider</label>
              <select id="pool-provider"></select>
            </div>
            <div>
              <label for="pool-model">Model to add</label>
              <select id="pool-model"></select>
            </div>
          </div>
          <p class="meta" id="pool-status" role="status"></p>
          <button type="button" id="pool-add">Add model</button>
        </fieldset>
        <div class="brain-controls">
          <button type="button" id="brain-test" disabled>Test model</button>
          <button type="submit" id="brain-save" disabled>Save</button>
        </div>
        <p class="brain-feedback" id="brain-feedback" role="status" hidden></p>
        <div class="brain-test-result" id="brain-test-result" role="status" hidden>
          <p class="meta" id="brain-test-latency"></p>
          <pre id="brain-test-reply"></pre>
        </div>
      </form>
      <div class="settings-stack">
        <section class="card brain-form utility-card" aria-labelledby="routing-preview-title">
          <h3 id="routing-preview-title">Routing preview</h3>
          <table class="routing-preview">
            <thead><tr><th scope="col">Turn type</th><th scope="col">First model</th></tr></thead>
            <tbody id="routing-preview"></tbody>
          </table>
          <p class="meta" id="routing-preview-status" role="status"></p>
        </section>
        <form class="card brain-form utility-card" id="routing-test-form">
          <h3>Test routing</h3>
          <label for="routing-prompt">Prompt</label>
          <div class="query-form">
            <input id="routing-prompt" maxlength="4000" required placeholder="e.g. Remind me to check the oven" />
            <button type="submit" id="routing-test" disabled>Test routing</button>
          </div>
          <p class="meta">Preview the order without calling a model.</p>
          <div id="routing-result" class="brain-test-result" role="status" hidden></div>
        </form>
      </div>
    </div>
  `;
}

function shortModel({ name, model, provider }) {
  return provider === "mock" ? "Mock" : model?.split("/").at(-1).split(":")[0] || name;
}

export function createBrain({ byId, api, date, updateConnections, renderBrain, isBusy, isActive }) {
  render(html`<${Brain} />`, byId("settings-brain"));
  let brainSettings;
  let brainBusy = false;
  let modelRequest;
  let routingRequest;
  let poolRequest;
  let poolModels = {};
  let poolDraft = [];
  let poolDirty = false;
  const brainProvider = byId("brain-provider");
  const brainModel = byId("brain-model");
  const customModel = byId("brain-custom");
  const poolProvider = byId("pool-provider");
  const poolModel = byId("pool-model");

  function brainChoice() {
    return brainSettings?.providers.find((entry) => entry.provider === brainProvider.value);
  }

  function brainDraft() {
    return {
      provider: brainProvider.value,
      model: brainChoice() ? brainModel.value || customModel.value.trim() : "",
      ...(poolDirty ? { pool: poolDraft } : {}),
    };
  }

  function setBrainControls() {
    const choice = brainChoice();
    const locked = !brainSettings || brainBusy || isBusy();
    const usable = !choice || (choice.available && choice.supported);
    const custom = !!choice && !brainModel.value;
    const needsModel = !!choice && !brainDraft().model;
    brainProvider.disabled = locked;
    byId("brain-workers").disabled = locked;
    brainModel.disabled = locked || !usable || !!modelRequest;
    customModel.disabled = brainModel.disabled;
    byId("brain-custom-field").hidden = !custom;
    byId("brain-test").disabled = byId("brain-save").disabled = locked || !usable || !!modelRequest || needsModel;
    byId("routing-test").disabled = byId("brain-save").disabled;
    byId("brain-pool").disabled = locked;
    poolModel.disabled = !!poolRequest || !poolProvider.value;
    byId("pool-add").disabled = poolModel.disabled || !poolModel.value || poolDraft.length >= 32;
  }

  function routedModel(model) {
    if (!model) return "—";
    return model.provider === "huggingface" && model.model ? shortModel(model)
      : `${model.name} · ${model.model || "Automatic model"}`;
  }

  function renderRoutingPreview(plans) {
    render(plans.map((plan) => html`
      <tr><th scope="row">${plan.label}</th><td title=${plan.reason}>${routedModel(plan.order[0])}</td></tr>
    `), byId("routing-preview"));
  }

  async function previewRouting(prompt) {
    routingRequest?.abort();
    const result = byId("routing-result");
    result.hidden = true;
    if (byId("brain-save").disabled) return;
    const status = byId("routing-preview-status");
    const controller = routingRequest = new AbortController();
    status.textContent = "Updating routing preview…";
    try {
      const { preview, test } = await api("/api/brain/route", {
        ...brainDraft(), ...(prompt === undefined ? {} : { prompt }),
      }, controller.signal);
      if (routingRequest !== controller) return;
      renderRoutingPreview(preview);
      status.textContent = "";
      if (test) {
        render(html`
          <strong>${test.label}</strong><p class="meta">${test.reason}</p>
          <ol>${test.order.map((model) => html`<li>${routedModel(model)}</li>`)}</ol>
        `, result);
        result.hidden = false;
      }
    } catch (error) {
      if (routingRequest === controller) status.textContent = error.message;
    } finally {
      if (routingRequest === controller) routingRequest = undefined;
    }
  }

  function updatePoolOptions() {
    const available = Object.keys(poolModels).filter((model) =>
      !poolDraft.some((entry) => entry.provider === poolProvider.value && entry.model === model));
    poolModel.replaceChildren(new Option(available.length ? "Choose a model…" : "No models to add", ""),
      ...available.map((model) => new Option(model, model)));
    setBrainControls();
  }

  async function loadPoolModels() {
    poolRequest?.abort();
    poolModels = {};
    const status = byId("pool-status");
    const provider = poolProvider.value;
    const controller = poolRequest = new AbortController();
    updatePoolOptions();
    if (provider) showLoading(status, "Loading live chat models…");
    else status.textContent = "Connect a chat provider to add models.";
    try {
      if (provider) {
        const { tags, detail } = await api(`/api/brain/models?provider=${encodeURIComponent(provider)}`,
          undefined, controller.signal);
        if (poolRequest !== controller) return;
        poolModels = tags || {};
        status.textContent = tags && Object.keys(tags).length ? "" : detail;
      }
    } catch (error) {
      if (poolRequest === controller) status.textContent = error.message;
    } finally {
      if (poolRequest === controller) {
        poolRequest = undefined;
        updatePoolOptions();
      }
    }
  }

  function poolChanged() {
    poolDirty = true;
    clearBrainTest();
    previewRouting();
  }

  function renderPool() {
    render(poolDraft.length ? poolDraft.map((entry, index) => {
      const provider = brainSettings.providers.find((row) => row.provider === entry.provider);
      const name = provider?.name || modelNames[entry.provider] || entry.provider;
      const model = `${entry.provider}:${entry.model}`;
      return html`
        <${PoolEntry} key=${model} model=${model} entry=${entry}
          summary=${routedModel({ ...entry, name }) + (provider?.available ? "" : " (disconnected)")}
          stats=${brainSettings.stats[model]} date=${date} onChange=${poolChanged}
          onRemove=${() => {
            poolDraft.splice(index, 1);
            renderPool();
            updatePoolOptions();
            poolProvider.focus();
            poolChanged();
          }} />
      `;
    }) : html`<p class="meta">An empty pool uses connected provider defaults.</p>`, byId("brain-pool-rows"));
  }

  function brainFeedback(message = "") {
    byId("brain-feedback").hidden = !message;
    byId("brain-feedback").textContent = message;
  }

  async function loadBrainModels() {
    modelRequest?.abort();
    modelRequest = undefined;
    const choice = brainChoice();
    const detail = byId("brain-provider-detail");
    const modelDetail = byId("brain-model-detail");
    byId("brain-model-fields").hidden = !choice;
    byId("brain-pool").hidden = brainProvider.value !== "smart";
    if (!byId("brain-pool").hidden && !poolRequest && !poolProvider.options.length) {
      const providers = brainSettings.providers.filter((entry) => entry.available && entry.supported);
      poolProvider.replaceChildren(...providers.map((entry) => new Option(entry.name, entry.provider)));
      loadPoolModels();
    }
    if (!choice) {
      detail.textContent = {
        priority: "Try connected providers in a fixed order, beginning with Muse Spark when available.",
        smart: "Rank the pool for each turn using model tags and recent performance.",
        mock: "Use Hearth’s offline demo model.",
      }[brainProvider.value];
      setBrainControls();
      return;
    }
    detail.textContent = choice.available ? "Connected through Fly Sprites." : "This saved provider is disconnected.";
    const saved = brainSettings.selection;
    const selected = saved.provider === choice.provider ? saved.model : choice.default_model;
    brainModel.replaceChildren(new Option("Enter a model ID…", ""));
    customModel.value = selected;
    if (choice.available && choice.supported) showLoading(modelDetail, "Loading chat models…");
    else modelDetail.textContent = choice.available ? "Loading chat models…" : "Refresh Settings → Connections after authorizing this provider.";
    if (!choice.available || !choice.supported) {
      setBrainControls();
      return;
    }
    const controller = modelRequest = new AbortController();
    setBrainControls();
    try {
      const { models, detail } = await api(`/api/brain/models?provider=${encodeURIComponent(choice.provider)}`,
        undefined, controller.signal);
      if (modelRequest !== controller) return;
      brainModel.prepend(...models.map((model) => new Option(model, model)));
      brainModel.value = models.includes(selected) ? selected : selected ? "" : models[0] || "";
      modelDetail.textContent = detail || `${models.length} chat models available.`;
    } catch (error) {
      if (modelRequest === controller) modelDetail.textContent = error.message;
    } finally {
      if (modelRequest === controller) {
        modelRequest = undefined;
        setBrainControls();
      }
    }
  }

  async function openBrainSettings() {
    if (brainBusy) return;
    routingRequest?.abort();
    routingRequest = undefined;
    poolRequest?.abort();
    poolRequest = undefined;
    poolProvider.replaceChildren();
    byId("brain-pool").hidden = true;
    byId("routing-result").hidden = true;
    renderRoutingPreview([]);
    showLoading(byId("routing-preview-status"), "Loading routing preview…");
    brainSettings = undefined;
    setBrainControls();
    brainFeedback();
    byId("brain-test-result").hidden = true;
    try {
      await updateConnections("rescan");
      if (!isActive()) return;
      brainSettings = await api("/api/brain");
      byId("brain-workers").value = brainSettings.parallel_workers;
      const providers = brainSettings.providers.map((entry) => {
        const suffix = !entry.available ? " (disconnected)" : !entry.supported ? " (chat unavailable)" : "";
        const option = new Option(entry.name + suffix, entry.provider);
        option.disabled = !entry.supported;
        return option;
      });
      brainProvider.replaceChildren(new Option("Auto (priority)", "priority"), new Option("Smart routing", "smart"),
        ...providers, new Option("Mock", "mock"));
      brainProvider.value = brainSettings.mode;
      poolDraft = structuredClone(brainSettings.pool.length ? brainSettings.pool : brainSettings.default_pool);
      poolDirty = false;
      renderPool();
      renderRoutingPreview(brainSettings.preview);
      byId("routing-preview-status").textContent = "";
      renderBrain(brainSettings);
      brainFeedback(brainSettings.scan_error || "");
      await loadBrainModels();
    } catch (error) {
      byId("routing-preview-status").textContent = "";
      brainFeedback(error.message);
    }
  }

  function clearBrainTest() {
    brainFeedback();
    byId("brain-test-result").hidden = true;
  }

  async function updateBrain(operation) {
    if (brainBusy || isBusy() || modelRequest) return;
    const draft = brainDraft();
    if (operation === "settings") draft.parallel_workers = Number(byId("brain-workers").value);
    routingRequest?.abort();
    routingRequest = undefined;
    byId("routing-preview-status").textContent = "";
    brainBusy = true;
    setBrainControls();
    if (operation === "test") byId("brain-test-result").hidden = true;
    brainFeedback(operation === "test" ? "Testing the selected model…" : "Saving brain settings…");
    try {
      const result = await api(`/api/brain/${operation}`, draft);
      if (operation === "test") {
        byId("brain-test-latency").textContent = `Test reply · ${result.latency_ms.toLocaleString()} ms`;
        byId("brain-test-reply").textContent = result.reply;
        byId("brain-test-result").hidden = false;
        brainFeedback();
      } else {
        brainSettings = result;
        poolDraft = structuredClone(result.pool.length ? result.pool : result.default_pool);
        poolDirty = false;
        renderPool();
        updatePoolOptions();
        renderRoutingPreview(result.preview);
        renderBrain(result);
        brainFeedback("Brain settings saved.");
      }
    } catch (error) {
      brainFeedback(error.message);
    } finally {
      brainBusy = false;
      setBrainControls();
    }
  }

  brainProvider.addEventListener("change", async () => {
    clearBrainTest();
    await loadBrainModels();
    previewRouting();
  });
  brainModel.addEventListener("change", () => {
    clearBrainTest();
    setBrainControls();
    if (!brainModel.value) customModel.focus();
    previewRouting();
  });
  customModel.addEventListener("input", () => {
    clearBrainTest();
    setBrainControls();
  });
  customModel.addEventListener("change", () => previewRouting());
  poolProvider.addEventListener("change", loadPoolModels);
  poolModel.addEventListener("change", setBrainControls);
  byId("pool-add").addEventListener("click", () => {
    const model = poolModel.value;
    const key = `${poolProvider.value}:${model}`;
    poolDraft.push({ provider: poolProvider.value, model, tags: { ...poolModels[model] } });
    renderPool();
    updatePoolOptions();
    const summary = [...byId("brain-pool-rows").children].find((item) => item.dataset.model === key);
    summary?.querySelector("summary")?.focus();
    poolChanged();
  });
  byId("routing-test-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const prompt = byId("routing-prompt").value.trim();
    if (prompt) previewRouting(prompt);
  });
  byId("brain-test").addEventListener("click", () => updateBrain("test"));
  byId("brain-form").addEventListener("submit", (event) => {
    event.preventDefault();
    updateBrain("settings");
  });

  return { open: openBrainSettings, updateControls: setBrainControls };
}
