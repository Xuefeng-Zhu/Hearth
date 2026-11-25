const get = (id) => document.getElementById(id);
const kinds = {
  plan: ["Plan", "◫"], list: ["List", "☷"], note: ["Note", "▤"],
  transcript: ["Transcript", "◉"], export: ["Export", "⇩"],
};
const formats = { md: "Markdown", txt: "Plain text", csv: "CSV", json: "JSON" };
const mimeTypes = { md: "text/markdown", txt: "text/plain", csv: "text/csv", json: "application/json" };
const statuses = { synced: "Synced to Box", saving: "Saving…", local: "Local only", error: "Sync error" };
const updated = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

function element(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}

function control(label, action, className = "artifact-control") {
  const button = element("button", className, label);
  button.type = "button";
  button.addEventListener("click", action);
  return button;
}

function badge(text, style) {
  return element("span", `artifact-badge ${style || ""}`, text);
}

function clock(at) {
  const timestamp = Date.parse(at);
  const time = element("time", "", Number.isFinite(timestamp) ? updated.format(timestamp) : "Date unavailable");
  if (Number.isFinite(timestamp)) time.dateTime = at;
  return time;
}

export function csvRows(text) {
  const rows = [];
  let row = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < text.length; index++) {
    const char = text[index];
    if (char === '"') {
      if (quoted && text[index + 1] === '"') {
        value += '"';
        index++;
      } else if (quoted || !value) {
        quoted = !quoted;
      } else {
        value += char;
      }
    } else if (!quoted && (char === "," || char === "\n" || char === "\r")) {
      row.push(value);
      value = "";
      if (char === ",") continue;
      if (char === "\r" && text[index + 1] === "\n") index++;
      rows.push(row);
      row = [];
    } else {
      value += char;
    }
  }
  if (value || row.length || /"$/.test(text)) rows.push([...row, value]);
  return rows;
}

function inlineMarkdown(target, text) {
  const tokens = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\))/g;
  let end = 0;
  for (const match of text.matchAll(tokens)) {
    target.append(text.slice(end, match.index));
    const token = match[0];
    if (token.startsWith("[")) {
      const split = token.indexOf("](");
      const link = element("a", "", token.slice(1, split));
      link.href = token.slice(split + 2, -1);
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      target.append(link);
    } else if (token.startsWith("**")) {
      target.append(element("strong", "", token.slice(2, -2)));
    } else {
      target.append(element(token.startsWith("`") ? "code" : "em", "", token.slice(1, -1)));
    }
    end = match.index + token.length;
  }
  target.append(text.slice(end));
}

export function markdown(text, className = "artifact-markdown") {
  const content = element("div", className);
  let block, code;
  for (const line of text.split(/\r?\n/)) {
    if (line.startsWith("```")) {
      if (!code) {
        code = element("pre");
        content.append(code);
      } else {
        code = undefined;
      }
      block = undefined;
    } else if (code) {
      code.append(line + "\n");
    } else if (!line.trim()) {
      block = undefined;
    } else if (/^#{1,6} /.test(line)) {
      const level = line.indexOf(" ");
      const heading = element(`h${Math.min(level + 2, 6)}`);
      inlineMarkdown(heading, line.slice(level + 1));
      content.append(heading);
      block = undefined;
    } else {
      const item = /^(?:[-*+] |\d+\. )/.exec(line);
      const quote = line.startsWith("> ");
      const tag = item ? (/^\d/.test(line) ? "OL" : "UL") : quote ? "BLOCKQUOTE" : "P";
      if (block?.tagName !== tag) {
        block = element(tag.toLowerCase());
        content.append(block);
      }
      if (item) {
        const bullet = element("li");
        inlineMarkdown(bullet, line.slice(item[0].length));
        block.append(bullet);
      } else {
        if (block.childNodes.length) block.append(" ");
        inlineMarkdown(block, quote ? line.slice(2) : line);
      }
    }
  }
  return content;
}

function preview(artifact) {
  if (!Object.hasOwn(artifact, "content")) {
    const text = artifact.size > 128 * 1024 ? "This file is too large to preview in Hearth." : "Open this file in Box to view it.";
    return element("p", "artifact-no-preview", text);
  }
  if (artifact.format === "md") return markdown(artifact.content);
  if (artifact.format === "csv") {
    const wrap = element("div", "artifact-table");
    const table = element("table");
    const rows = csvRows(artifact.content);
    for (const [index, row] of rows.slice(0, 201).entries()) {
      const tr = table.insertRow();
      for (const value of row.slice(0, 60)) {
        const cell = element(index ? "td" : "th", "", value);
        if (!index) cell.scope = "col";
        tr.append(cell);
      }
    }
    wrap.append(table);
    if (rows.length > 201 || rows.some((row) => row.length > 60)) {
      wrap.append(element("p", "meta", "Preview shows up to 200 rows and 60 columns. Download for the full CSV."));
    }
    return wrap;
  }
  return element("pre", "artifact-plain", artifact.content);
}

function download(item) {
  const url = URL.createObjectURL(new Blob([item.content], { type: mimeTypes[item.format] || "text/plain" }));
  const link = element("a");
  link.href = url;
  link.download = item.filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function createArtifacts({ api, openThread, openConnections, showNotice, saveActivity, refreshChat }) {
  const collection = get("artifact-collection");
  const drawer = get("artifact-drawer");
  const detailBody = get("artifact-detail-body");
  const detailStatus = get("artifact-detail-status");
  const search = get("artifact-search");
  const kind = get("artifact-kind");
  const sort = get("artifact-sort");
  const settingsForm = get("artifact-settings-form");
  const settingsStatus = get("artifact-settings-status");
  const pending = new Set();
  const savingMessages = new Set();
  let layout = localStorage.getItem("hearth-artifact-layout") === "list" ? "list" : "grid";
  let snapshot, selected, request, detailRequest, opener, editMode = false, confirming = false;

  function connection(info) {
    const { connected, box_error: error, settings } = info;
    const status = get("artifact-box-status");
    status.textContent = !connected ? "Box disconnected" : error ? "Box needs attention"
      : settings.auto_save ? "Box connected" : "Box auto-save off";
    status.dataset.connected = String(connected && !error);
    get("artifact-connection").hidden = connected && !error;
    get("artifact-connection-copy").textContent = error || "Connect Box to sync the artifacts you save here.";
  }

  function syncLabel(item) {
    const state = pending.has(item.id) ? "saving" : item.sync;
    const label = element("span", `artifact-sync is-${state}`, statuses[state]);
    label.title = item.sync_message || statuses[state];
    return label;
  }

  function chips(item) {
    return [badge(kinds[item.kind][0], `is-${item.kind}`), badge(item.source, item.source === "Box" ? "is-box" : ""),
      badge(formats[item.format] || item.format?.toUpperCase() || "File")];
  }

  function threadLink(item) {
    const link = element("a", "artifact-thread", `↗ ${item.thread_title || "Source chat"}`);
    link.href = "#chat";
    link.addEventListener("click", (event) => {
      event.preventDefault();
      if (drawer.open) drawer.close();
      openThread(item.thread_id, item.message_id);
    });
    return link;
  }

  function card(item) {
    const panel = element("article", "artifact-card");
    panel.dataset.kind = item.kind;
    const icon = element("span", "artifact-kind-icon", kinds[item.kind][1]);
    icon.setAttribute("aria-hidden", "true");
    const header = element("div", "artifact-card-header");
    const badges = element("div", "artifact-badges");
    const heading = element("h3");
    const title = control(item.title, (event) => open(item.id, event.currentTarget), "artifact-card-title");
    title.dataset.artifactId = item.id;
    title.setAttribute("aria-haspopup", "dialog");
    heading.append(title);
    badges.append(...chips(item));
    header.append(heading, badges);
    const foot = element("div", "artifact-card-foot");
    const timestamp = clock(item.updated_at);
    timestamp.title = `Updated ${timestamp.textContent}`;
    const sync = syncLabel(item);
    if (item.sync_message && !pending.has(item.id)) {
      sync.append(element("small", "artifact-sync-message", item.sync_message));
    }
    foot.append(sync, timestamp);
    const sources = element("div", "artifact-card-links");
    if (item.thread_id) sources.append(threadLink(item));
    if ((item.sync !== "synced" && snapshot.connected) && !pending.has(item.id)) {
      sources.append(control("Retry sync", () => retry(item), "artifact-text-button"));
    }
    panel.append(icon, header, foot);
    if (sources.childElementCount) panel.append(sources);
    return panel;
  }

  function render() {
    collection.dataset.layout = layout;
    get("artifact-grid").setAttribute("aria-pressed", String(layout === "grid"));
    get("artifact-list").setAttribute("aria-pressed", String(layout === "list"));
    if (!snapshot) return;
    connection(snapshot);
    const query = search.value.trim().toLocaleLowerCase();
    const all = snapshot.artifacts;
    const rows = all.filter((item) => (!kind.value || item.kind === kind.value)
      && [item.title, item.filename, item.thread_title, kinds[item.kind][0], item.source].filter(Boolean)
        .join(" ").toLocaleLowerCase().includes(query));
    const byName = (a, b) => a.title.localeCompare(b.title);
    rows.sort(sort.value === "name" ? byName : (a, b) => ((Date.parse(b.updated_at) || 0)
      - (Date.parse(a.updated_at) || 0)) || byName(a, b));
    get("artifact-count").textContent = `${rows.length}${rows.length !== all.length ? " of " + all.length : ""}
      ${all.length === 1 ? "artifact" : "artifacts"}`.replace(/\s+/g, " ");
    const active = document.activeElement;
    const focusedId = collection.contains(active) && active.dataset.artifactId;
    collection.replaceChildren(...rows.map(card));
    if (focusedId) {
      const replacement = [...collection.querySelectorAll("button[data-artifact-id]")]
        .find((button) => button.dataset.artifactId === focusedId);
      (replacement || search).focus({ preventScroll: true });
    }
    get("artifact-empty").hidden = !!rows.length;
    get("artifact-empty-title").textContent = all.length ? "No matches" : "No artifacts yet";
    get("artifact-empty-hint").textContent = all.length ? "Try a different search or kind."
      : "Ask Hearth to make a file, or save any reply as an artifact.";
  }

  async function show() {
    if (request) return request;
    get("artifact-refresh").disabled = true;
    request = api("/api/artifacts").then((data) => {
      snapshot = data;
      render();
    }).catch((error) => {
      get("artifact-count").textContent = error.message;
    }).finally(() => {
      request = undefined;
      get("artifact-refresh").disabled = false;
    });
    return request;
  }

  function renderDetail(item) {
    get("artifact-drawer-title").textContent = item.title;
    get("artifact-filename").textContent = [item.filename, Number.isInteger(item.size) ? `${item.size.toLocaleString()} bytes` : ""]
      .filter(Boolean).join(" · ");
    get("artifact-detail-meta").replaceChildren(...chips(item), syncLabel(item));
    const actions = get("artifact-actions");
    actions.replaceChildren();
    detailStatus.textContent = item.sync_message || "";
    const haveText = Object.hasOwn(item, "content");
    if (haveText) {
      const edit = control("Edit", () => {
        editMode = true;
        confirming = false;
        renderDetail(item);
        get("artifact-editor").focus();
      });
      edit.disabled = editMode;
      actions.append(edit, control("Download", () => download(item)), control("Copy", async () => {
        try {
          await navigator.clipboard.writeText(item.content);
          detailStatus.textContent = "Copied to clipboard.";
        } catch {
          detailStatus.textContent = "Clipboard unavailable. Use Download to keep a copy.";
        }
      }));
    }
    if (item.box_url) {
      const link = element("a", "artifact-control artifact-box-link", "Open in Box ↗");
      link.href = item.box_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      actions.append(link);
    }
    if (item.sync !== "synced" && item.box_connected && !pending.has(item.id)) {
      actions.append(control("Retry sync", () => retry(item)));
    }
    const deletion = control("Move to Trash", () => {
      confirming = !confirming;
      renderDetail(item);
      if (confirming) get("artifact-confirm-delete").focus();
    }, "artifact-control artifact-danger");
    deletion.setAttribute("aria-expanded", String(confirming));
    deletion.disabled = editMode;
    actions.append(deletion);
    detailBody.replaceChildren();
    if (confirming) {
      const confirm = element("div", "artifact-delete");
      confirm.append(element("p", "", item.box_url
        ? "Move this artifact to Hearth Trash? The file stays in Box. Restore it from Timeline."
        : "Move this artifact to Hearth Trash? Restore it from Timeline."));
      const yes = control("Move to Hearth Trash",
        () => mutate("delete", item, { revision: item.revision }), "artifact-control artifact-danger");
      yes.id = "artifact-confirm-delete";
      confirm.append(yes, control("Cancel", () => {
        confirming = false;
        renderDetail(item);
        get("artifact-actions").lastElementChild.focus();
      }));
      detailBody.append(confirm);
    }
    if (item.thread_id) {
      const source = element("p", "artifact-detail-source");
      source.append(element("span", "", "From "), threadLink(item));
      detailBody.append(source);
    }
    const paper = element("section", "artifact-paper");
    paper.append(element("h3", "artifact-section-label", editMode ? "Edit file" : "Preview"));
    if (editMode) {
      const form = element("form", "artifact-edit");
      const label = element("label", "visually-hidden", `${formats[item.format] || "Text"} content`);
      label.htmlFor = "artifact-editor";
      const field = element("textarea");
      field.id = "artifact-editor";
      field.maxLength = 128 * 1024;
      field.value = item.content;
      const save = element("button", "artifact-control artifact-box-link", "Save");
      save.type = "submit";
      form.append(label, field, save, control("Cancel", () => {
        editMode = false;
        renderDetail(item);
        actions.firstElementChild?.focus();
      }));
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        mutate("update", item, { revision: item.revision, content: field.value });
      });
      paper.append(form);
    } else {
      paper.append(preview(item));
    }
    detailBody.append(paper);
    const versions = element("section", "artifact-versions");
    versions.append(element("h3", "", item.version_source === "hearth" ? "Hearth version history" : "Version history"));
    if (item.versions?.length) {
      const list = element("ol");
      for (const version of item.versions) {
        const row = element("li");
        row.append(element("strong", "", version.number ? `Version ${version.number}` : "Box version"));
        if (version.current) row.append(badge("Current", "is-box"));
        if (version.at) row.append(clock(version.at));
        list.append(row);
      }
      versions.append(list);
    } else if (!item.warnings?.length) {
      versions.append(element("p", "meta", item.version_source === "hearth"
        ? "Hearth has no saved versions for this file." : "Box versions will appear after this file syncs."));
    }
    for (const warning of item.warnings || []) versions.append(element("p", "meta", warning));
    detailBody.append(versions);
  }

  async function open(id, trigger) {
    if (!drawer.open) {
      opener = trigger || document.activeElement;
      drawer.showModal();
      get("artifact-close").focus();
    }
    const token = Symbol();
    detailRequest = token;
    selected = id;
    editMode = confirming = false;
    const row = snapshot?.artifacts.find((item) => item.id === id);
    get("artifact-drawer-title").textContent = row?.title || "Artifact";
    get("artifact-detail-meta").replaceChildren();
    get("artifact-actions").replaceChildren();
    get("artifact-filename").textContent = "";
    detailStatus.textContent = "Loading artifact…";
    detailBody.replaceChildren();
    try {
      const item = await api(`/api/artifacts/detail?id=${encodeURIComponent(id)}`);
      if (detailRequest === token && drawer.open) renderDetail(item);
    } catch (error) {
      if (detailRequest === token && drawer.open) detailStatus.textContent = error.message;
    }
  }

  async function mutate(operation, item, fields) {
    if (pending.has(item.id)) return;
    pending.add(item.id);
    const inDrawer = selected === item.id && drawer.open;
    if (inDrawer) detailStatus.textContent = operation === "delete" ? "Deleting…" : "Saving…";
    if (inDrawer) {
      get("artifact-detail-meta").querySelector(".artifact-sync")?.replaceWith(syncLabel(item));
      for (const button of drawer.querySelectorAll("button:not(#artifact-close)")) button.disabled = true;
    }
    render();
    try {
      const saved = await api(`/api/artifacts/${operation}`, { id: item.id, ...fields });
      pending.delete(item.id);
      if (inDrawer && drawer.open && selected === item.id) {
        if (operation === "delete") {
          opener = selected = undefined;
          drawer.close();
        } else await open(item.id);
      }
      if (operation === "delete") showNotice(saved.sync_message);
      else if (saved.sync_message && !inDrawer) showNotice(saved.sync_message);
      refreshChat().catch(() => {});
    } catch (error) {
      if (inDrawer && drawer.open && selected === item.id) {
        pending.delete(item.id);
        get("artifact-detail-meta").querySelector(".artifact-sync")?.replaceWith(syncLabel(item));
        detailStatus.textContent = error.message;
      } else showNotice(error.message);
    } finally {
      pending.delete(item.id);
      if (inDrawer && drawer.open && selected === item.id && editMode) {
        for (const button of detailBody.querySelectorAll("button")) button.disabled = false;
        for (const button of get("artifact-actions").querySelectorAll("button")) {
          button.disabled = ["Edit", "Move to Trash"].includes(button.textContent);
        }
      } else if (inDrawer && drawer.open && selected === item.id) {
        for (const button of drawer.querySelectorAll("button:not(#artifact-close)")) button.disabled = false;
      }
      await show();
    }
  }

  function retry(item) {
    return mutate("retry", item, {});
  }

  function worthSaving(item) {
    const text = String(item?.content || "").trim();
    if (text.length >= 600) return true;
    return /^(#{1,6} |\|.*\||```|\s*(?:[-*] |\d+\. ).*\n\s*(?:[-*] |\d+\. ))/m.test(text);
  }

  function chatActions(item, threadId, linked = [], { allowSave = true } = {}) {
    const actions = element("div", "artifact-chat-actions");
    for (const artifact of linked) {
      const verb = artifact.sync === "synced" ? "to Box" : "locally";
      const chip = control(`Saved “${artifact.title}” ${verb} ▸`, (event) => open(artifact.id, event.currentTarget),
        "artifact-chat-chip");
      chip.dataset.artifactId = artifact.id;
      chip.setAttribute("aria-haspopup", "dialog");
      chip.title = artifact.sync_message || "";
      actions.append(chip);
    }
    if (!linked.some((artifact) => artifact.from_message) && allowSave && worthSaving(item)) {
      const active = savingMessages.has(item.id);
      const save = control(active ? "Saving…" : "Save as artifact", async () => {
        if (savingMessages.has(item.id)) return;
        savingMessages.add(item.id);
        save.textContent = "Saving…";
        save.disabled = true;
        saveActivity(threadId, true);
        try {
          const result = await api("/api/artifacts/save-message", { thread_id: threadId, message_id: item.id });
          if (result.sync_message) showNotice(result.sync_message);
        } catch (error) {
          showNotice(error.message);
        } finally {
          savingMessages.delete(item.id);
          saveActivity(threadId, false);
          save.textContent = "Save as artifact";
          save.disabled = false;
          await refreshChat().catch(() => {});
        }
      }, "artifact-text-button");
      save.disabled = active;
      actions.append(save);
    }
    return actions;
  }

  function renderSettings(info) {
    get("artifact-auto-save").checked = info.settings.auto_save;
    get("artifact-format").value = info.settings.format;
    get("artifact-folder").value = info.settings.folder_name;
    get("artifact-settings-connection").textContent = info.connected ? "Box connected." : "Box is disconnected. Files can still be saved locally.";
  }

  async function settings() {
    settingsStatus.textContent = "";
    try {
      renderSettings(await api("/api/artifacts/settings"));
    } catch (error) {
      settingsStatus.textContent = error.message;
    }
  }

  settingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const save = settingsForm.querySelector("[type=submit]");
    save.disabled = true;
    settingsStatus.textContent = "Saving settings…";
    try {
      renderSettings(await api("/api/artifacts/settings", { auto_save: get("artifact-auto-save").checked,
        format: get("artifact-format").value, folder_name: get("artifact-folder").value }));
      settingsStatus.textContent = "Artifact settings saved.";
    } catch (error) {
      settingsStatus.textContent = error.message;
    } finally {
      save.disabled = false;
    }
  });

  get("artifact-connect").addEventListener("click", (event) => {
    event.preventDefault();
    openConnections();
  });
  get("artifact-close").addEventListener("click", () => drawer.close());
  drawer.addEventListener("click", (event) => { if (event.target === drawer) drawer.close(); });
  drawer.addEventListener("close", () => {
    const replacement = [...document.querySelectorAll("button[data-artifact-id]")]
      .find((button) => button.dataset.artifactId === selected && button.getClientRects().length);
    const target = opener?.isConnected ? opener : replacement || (get("artifacts-view").hidden ? get("message") : search);
    selected = detailRequest = undefined;
    opener = undefined;
    target.focus();
  });
  get("artifact-refresh").addEventListener("click", show);
  search.addEventListener("input", render);
  kind.addEventListener("change", render);
  sort.addEventListener("change", render);
  for (const mode of ["grid", "list"]) {
    get(`artifact-${mode}`).addEventListener("click", () => {
      layout = mode;
      localStorage.setItem("hearth-artifact-layout", mode);
      render();
    });
  }

  return { show, settings, chatActions, open };
}
