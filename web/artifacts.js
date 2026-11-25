import { fileGlyph, uploadURL } from "./attachments.js";
import { icon, iconButton } from "./icons.js";
import { createPageDetail, pageThumbnail } from "./pages.js";
import { setTimeZone, timeFormatter } from "./time.js";

const get = (id) => document.getElementById(id);
const kinds = {
  plan: ["Plan", "file-text"], list: ["List", "list"], note: ["Note", "file-text"],
  transcript: ["Transcript", "mic"], export: ["Export", "download"],
  page: ["Page", "page"],
};
const fileTypes = {
  docx: ["DOCX", "file-text"], pdf: ["PDF", "files"], xlsx: ["XLSX", "sheet"], pptx: ["PPTX", "slides"],
};
const legacyTypes = { md: "MD", txt: "TXT", csv: "CSV", json: "JSON" };
const formatFilters = { documents: ["docx", "md", "txt"], pdfs: ["pdf"], sheets: ["xlsx", "csv"], slides: ["pptx"] };

export function artifactFilterFromHash(hash) {
  if (hash === "#artifacts") return "all";
  if (hash === "#pages") return "pages";
  const filter = hash.match(/^#artifacts\/([a-z]+)$/)?.[1];
  if (filter === "pages" || Object.hasOwn(formatFilters, filter)) return filter;
}

const sizeFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });
const statuses = { synced: "Synced to Box", saving: "Saving…", local: "Local only", error: "Sync error" };
const updated = timeFormatter({ month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

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
  const tokens = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\)|https?:\/\/[^\s<>]+[^\s<>.,!?;:)\]])/g;
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
    } else if (token.startsWith("http")) {
      const link = element("a", "", token);
      link.href = token;
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
  const lines = text.split(/\r?\n/);
  const cells = (line) => line.trim().replace(/^\||\|$/g, "").split("|").map((value) => value.trim());
  let block, code;
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index];
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
    } else if (line.includes("|") && lines[index + 1]?.includes("|")
               && cells(lines[index + 1]).every((cell) => /^:?-{3,}:?$/.test(cell))) {
      const wrap = element("div", "artifact-table");
      const table = element("table");
      const head = table.createTHead().insertRow();
      const headers = cells(line);
      for (const label of headers) {
        const cell = element("th");
        cell.scope = "col";
        inlineMarkdown(cell, label);
        head.append(cell);
      }
      const body = table.createTBody();
      index += 2;
      while (lines[index]?.includes("|")) {
        const values = cells(lines[index++]);
        const row = body.insertRow();
        headers.forEach((_, column) => inlineMarkdown(row.insertCell(), values[column] || ""));
      }
      index--;
      wrap.append(table);
      content.append(wrap);
      block = undefined;
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

function fileURL(item, inline = false) {
  if (item.download_url) return inline ? item.inline_url : item.download_url;
  return `/api/artifacts/file?id=${encodeURIComponent(item.id)}${inline ? "&inline=1" : ""}`;
}

function fileIcon(item) {
  const type = fileTypes[item.format];
  const glyph = element("span", `artifact-kind-icon ${type ? `is-${item.format}` : ""}`);
  glyph.setAttribute("aria-hidden", "true");
  glyph.append(icon(item.mime ? fileGlyph(item) : type?.[1] || kinds[item.kind]?.[1] || "file", 21));
  return glyph;
}

function fileSize(size) {
  if (!Number.isInteger(size)) return "";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${sizeFormat.format(size / 1024)} KiB`;
  return `${sizeFormat.format(size / (1024 * 1024))} MiB`;
}

function fileLink(item, box = false, compact = false) {
  const label = box ? "Open in Box" : "Download";
  const link = element("a", compact ? "icon-button" : box ? "artifact-control artifact-box-link" : "artifact-control");
  link.title = label;
  link.setAttribute("aria-label", label);
  if (!compact) link.append(label, " ");
  link.append(icon(box ? "external" : "download", compact ? 18 : 15));
  if (box) {
    link.href = item.box_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  } else {
    link.href = fileURL(item);
    link.download = item.filename;
  }
  return link;
}

function tablePreview(rows) {
  const wrap = element("div", "artifact-table");
  const table = element("table");
  for (const [index, row] of rows.entries()) {
    const section = index ? (table.tBodies[0] || table.createTBody()) : table.createTHead();
    const tr = section.insertRow();
    for (const value of row) {
      const cell = element(index ? "td" : "th", "", value ?? "");
      if (!index) cell.scope = "col";
      tr.append(cell);
    }
  }
  wrap.append(table);
  return wrap;
}

function bullets(lines) {
  const list = element("ul");
  list.append(...lines.map((line) => element("li", "", line)));
  return list;
}

function preview(artifact) {
  if (artifact.image_url) {
    const image = element("img", "attachment-preview");
    image.alt = artifact.filename;
    image.src = artifact.image_url;
    return image;
  }
  if (artifact.audio_url) {
    const audio = element("audio", "attachment-audio");
    audio.src = artifact.audio_url;
    audio.controls = true;
    audio.preload = "metadata";
    return audio;
  }
  if (artifact.inline_pdf) {
    const frame = element("iframe", "artifact-pdf");
    frame.title = `${artifact.title} PDF preview`;
    frame.src = fileURL(artifact, true) + "#toolbar=0&view=FitH";
    return frame;
  }
  const data = artifact.preview;
  if (artifact.format === "xlsx" && data) {
    const sheet = element("div", "artifact-sheet");
    const grid = tablePreview(data.rows);
    grid.tabIndex = 0;
    grid.setAttribute("role", "region");
    grid.setAttribute("aria-label", data.sheet + " spreadsheet");
    sheet.append(element("h4", "", data.sheet), grid);
    if (data.truncated) sheet.append(element("p", "meta", "Preview shows up to 200 rows and 50 columns."));
    return sheet;
  }
  if (artifact.format === "pptx" && data) {
    const deck = element("ol", "artifact-slides");
    for (const slide of data.slides) {
      const page = element("li");
      if (slide.title) page.append(element("h4", "", slide.title));
      if (slide.bullets.length) page.append(bullets(slide.bullets));
      deck.append(page);
    }
    return deck;
  }
  if (artifact.format === "docx" && data) {
    const doc = element("div", "artifact-document");
    let list;
    for (const block of data.blocks) {
      if (block.type === "bullet") {
        if (!list) {
          list = element("ul");
          doc.append(list);
        }
        list.append(element("li", "", block.text));
      } else {
        list = undefined;
        doc.append(block.type === "table" ? tablePreview(block.rows)
          : element(block.type === "heading" ? "h4" : "p", "", block.text));
      }
    }
    return doc;
  }
  if (artifact.format === "md" && Object.hasOwn(artifact, "content")) return markdown(artifact.content);
  if (artifact.format === "csv" && Object.hasOwn(artifact, "content")) {
    const rows = csvRows(artifact.content);
    const wrap = tablePreview(rows.slice(0, 201).map((row) => row.slice(0, 60)));
    if (rows.length > 201 || rows.some((row) => row.length > 60)) {
      wrap.append(element("p", "meta", "Preview shows up to 200 rows and 60 columns."));
    }
    return wrap;
  }
  if (Object.hasOwn(artifact, "content")) return element("pre", "artifact-plain", artifact.content);
  return element("p", "artifact-no-preview", artifact.download_available
    ? "Download this file to view it." : "Open this file in Box to view it.");
}

export function createArtifacts({ api, openThread, openConnections, showNotice, refreshChat, onFilter }) {
  const collection = get("artifact-collection");
  const drawer = get("artifact-drawer");
  const detailBody = get("artifact-detail-body");
  const detailStatus = get("artifact-detail-status");
  const search = get("artifact-search");
  const kind = get("artifact-kind");
  const filters = [...get("artifact-filters").querySelectorAll("button")];
  const sort = get("artifact-sort");
  const settingsForm = get("artifact-settings-form");
  const settingsStatus = get("artifact-settings-status");
  const pending = new Set();
  const pageDetail = createPageDetail({ api, onChange: () => {
    if (!get("artifacts-view").hidden) void show();
  } });
  let layout = localStorage.getItem("hearth-artifact-layout") === "list" ? "list" : "grid";
  let formatFilter = "all";
  let snapshot, selected, request, detailRequest, opener, liveBrowse, confirming = false;

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
    const text = item.kind === "page" && state === "synced" ? "Saved to Box" : statuses[state];
    const label = element("span", `artifact-sync is-${state}`, text);
    label.title = item.sync_message || text;
    return label;
  }

  function chips(item) {
    if (item.kind === "page") return [badge("HTML / Page", "is-page"), badge(`v${item.version_number}`)];
    const format = fileTypes[item.format]?.[0] || legacyTypes[item.format] || item.format?.toUpperCase() || "File";
    const labels = [badge(format, fileTypes[item.format] ? `is-${item.format}` : ""),
      badge(kinds[item.kind]?.[0] || "File", `is-${item.kind}`)];
    if (item.version_number) labels.push(badge(`v${item.version_number}`));
    if (item.legacy) labels.push(badge("Legacy text"));
    return labels;
  }

  function threadLink(item) {
    const link = element("a", "artifact-thread");
    link.append(icon("external", 14), " ", item.thread_title || "Source chat");
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
    const page = item.kind === "page";
    const thumbnail = page ? pageThumbnail() : fileIcon(item);
    const header = element("div", "artifact-card-header");
    const badges = element("div", "artifact-badges");
    const heading = element("h3");
    const title = control(item.title, (event) => open(item.id, event.currentTarget, { kind: item.kind }), "artifact-card-title");
    title.dataset.artifactId = item.id;
    title.setAttribute("aria-haspopup", "dialog");
    if (page) panel.addEventListener("click", (event) => {
      if (!event.target.closest("button, a")) title.click();
    });
    heading.append(title);
    badges.append(...chips(item));
    header.append(heading, badges);
    if (item.size != null) header.append(element("p", "artifact-card-size meta", fileSize(item.size)));
    const foot = element("div", "artifact-card-foot");
    const timestamp = clock(item.updated_at);
    timestamp.title = `Updated ${timestamp.textContent}`;
    const sync = syncLabel(item);
    if (item.sync_message && !pending.has(item.id)) {
      sync.append(element("small", "artifact-sync-message", item.sync_message));
    }
    foot.append(sync, timestamp);
    const sources = element("div", "artifact-card-links");
    if (page || fileTypes[item.format] || item.legacy) sources.append(fileLink(item));
    if (item.box_url) sources.append(fileLink(item, true));
    if (!page && item.sync !== "synced" && snapshot.connected && !pending.has(item.id)) {
      sources.append(control("Retry sync", () => retry(item), "artifact-text-button"));
    }
    panel.append(thumbnail, header, foot);
    if (sources.childElementCount) panel.append(sources);
    return panel;
  }

  function render() {
    collection.dataset.layout = layout;
    get("artifact-grid").setAttribute("aria-pressed", String(layout === "grid"));
    get("artifact-list").setAttribute("aria-pressed", String(layout === "list"));
    for (const button of filters) button.setAttribute("aria-pressed", String(button.dataset.formatFilter === formatFilter));
    if (!snapshot) return;
    connection(snapshot);
    const query = search.value.trim().toLocaleLowerCase();
    const all = snapshot.artifacts;
    const matchesFormat = (item) => formatFilter === "all" || (formatFilter === "pages" ? item.kind === "page"
      : formatFilters[formatFilter].includes(item.format));
    const rows = all.filter((item) => matchesFormat(item) && (!kind.value || item.kind === kind.value)
      && [item.title, item.filename, item.thread_title, kinds[item.kind]?.[0], item.source].filter(Boolean)
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
    const hasType = all.some(matchesFormat);
    get("artifact-empty-title").textContent = hasType ? "No matches"
      : formatFilter === "pages" ? "No pages yet" : all.length ? "No artifacts of this type" : "No artifacts yet";
    get("artifact-empty-hint").textContent = hasType ? "Try a different search or kind."
      : formatFilter === "pages" ? "Ask Hearth in Chat to build a page."
      : all.length ? "Choose another type to see more artifacts."
      : "Ask Hearth to create a document, PDF, spreadsheet, slide deck, or page.";
  }

  function selectFormat(value) {
    if (formatFilter !== value && value === "pages") kind.value = "";
    formatFilter = value;
    render();
  }

  async function show() {
    if (request) return request;
    get("artifact-refresh").disabled = true;
    request = api("/api/artifacts").then((data) => {
      snapshot = data;
      if (snapshot.timezone) setTimeZone(snapshot.timezone);
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
    if (item.timezone) setTimeZone(item.timezone);
    get("artifact-drawer-title").textContent = item.title;
    get("artifact-filename").textContent = [item.filename, fileSize(item.size)]
      .filter(Boolean).join(" · ");
    get("artifact-detail-meta").replaceChildren(fileIcon(item), ...chips(item), syncLabel(item));
    const actions = get("artifact-actions");
    actions.replaceChildren();
    detailStatus.textContent = item.sync_message || "";
    if (item.download_available || Object.hasOwn(item, "content")) actions.append(fileLink(item));
    if (item.box_url) actions.append(fileLink(item, true));
    if (item.sync !== "synced" && item.box_connected && !pending.has(item.id)) {
      actions.append(control("Retry sync", () => retry(item)));
    }
    const deletion = control("Move to Trash", () => {
      confirming = !confirming;
      renderDetail(item);
      if (confirming) get("artifact-confirm-delete").focus();
    }, "artifact-control artifact-danger");
    deletion.setAttribute("aria-expanded", String(confirming));
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
    paper.append(element("h3", "artifact-section-label", "Preview"), preview(item));
    if (fileTypes[item.format] && item.source === "Hearth") {
      paper.append(element("p", "artifact-edit-hint meta", "Ask Hearth to edit this file and save a new version."));
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
        ? "Hearth has no saved versions for this file." : "Box will show the available version history."));
    }
    for (const warning of item.warnings || []) versions.append(element("p", "meta", warning));
    detailBody.append(versions);
  }

  async function open(id, trigger, { kind, version_number: version } = {}) {
    const row = snapshot?.artifacts.find((item) => item.id === id);
    if ((kind || row?.kind) === "page") return pageDetail.open(id, trigger || document.activeElement, version);
    liveBrowse = undefined;
    if (!drawer.open) {
      opener = trigger || document.activeElement;
      drawer.showModal();
      get("artifact-close").focus();
    }
    const token = Symbol();
    detailRequest = token;
    selected = id;
    confirming = false;
    get("artifact-drawer-title").textContent = row?.title || "Artifact";
    get("artifact-detail-meta").replaceChildren();
    get("artifact-actions").replaceChildren();
    get("artifact-filename").textContent = "";
    detailStatus.textContent = "Loading artifact…";
    detailBody.replaceChildren();
    try {
      const item = await api(`/api/artifacts/detail?id=${encodeURIComponent(id)}`);
      if (detailRequest !== token || !drawer.open) return;
      if (item.kind === "page") {
        const source = opener;
        drawer.close();
        return pageDetail.open(id, source, version, item);
      }
      renderDetail(item);
    } catch (error) {
      if (detailRequest === token && drawer.open) detailStatus.textContent = error.message;
    }
  }

  function saveAttachment(item, compact = false, onSaved) {
    if (item.box_url) return fileLink(item, true, compact);
    const label = "Save to Box";
    const save = compact ? iconButton("box", label, send) : control(label, send);
    async function send(event) {
      const target = event.currentTarget;
      target.disabled = true;
      try {
        const result = await api("/api/uploads/box", { id: item.id, thread_id: item.thread_id });
        target.replaceWith(fileLink(result, true, compact));
        onSaved?.(result);
        refreshChat().catch(() => {});
        if (!drawer.open) showNotice("Attachment saved to Box.");
      } catch (error) {
        if (drawer.open) detailStatus.textContent = error.message;
        else showNotice(error.message);
      } finally {
        target.disabled = false;
      }
    }
    return save;
  }

  async function openAttachment(item, trigger) {
    liveBrowse = undefined;
    if (!drawer.open) {
      opener = trigger || document.activeElement;
      drawer.showModal();
      get("artifact-close").focus();
    }
    const token = Symbol();
    detailRequest = token;
    selected = item.id;
    get("artifact-drawer-title").textContent = item.filename;
    get("artifact-filename").textContent = fileSize(item.size);
    get("artifact-detail-meta").replaceChildren(fileIcon(item), badge(item.format.toUpperCase()));
    const actions = get("artifact-actions");
    actions.replaceChildren();
    detailBody.replaceChildren();
    detailStatus.textContent = "Loading attachment…";
    try {
      const attachment = await api(uploadURL(item, "/detail"));
      if (detailRequest !== token || !drawer.open) return;
      actions.append(fileLink(attachment), saveAttachment(attachment, false, () => {
        if (detailRequest === token) detailStatus.textContent = "Attachment saved to Box.";
      }));
      detailStatus.textContent = attachment.warnings?.join(" ") || "";
      const paper = element("section", "artifact-paper");
      paper.append(element("h3", "artifact-section-label", "Preview"), preview(attachment));
      detailBody.append(paper);
    } catch (error) {
      if (detailRequest === token && drawer.open) detailStatus.textContent = error.message;
    }
  }

  function attachmentCards(items) {
    const list = element("div", "attachment-cards");
    for (const item of items) {
      const image = item.mime.startsWith("image/");
      const card = element("article", `attachment-card${image ? " attachment-image-card" : ""}`);
      const openFile = control("", (event) => openAttachment(item, event.currentTarget), "attachment-open");
      openFile.setAttribute("aria-haspopup", "dialog");
      openFile.setAttribute("aria-label", `Open ${item.filename}`);
      openFile.dataset.artifactId = item.id;
      if (image) {
        const thumbnail = element("img", "attachment-thumbnail");
        thumbnail.alt = "";
        thumbnail.loading = "lazy";
        thumbnail.src = uploadURL(item, "/file", { thumbnail: "1" });
        openFile.append(thumbnail);
      } else openFile.append(fileIcon(item));
      const name = element("span", "attachment-name");
      name.append(element("strong", "", item.filename), element("small", "", fileSize(item.size)));
      openFile.append(name);
      const actions = element("div", "attachment-card-actions");
      actions.append(saveAttachment(item, true));
      card.append(openFile, actions);
      list.append(card);
    }
    return list;
  }

  function openBrowse({ id, domain, live_url: liveUrl, mock, name }, trigger) {
    detailRequest = selected = undefined;
    liveBrowse = name ? undefined : id;
    opener = trigger;
    get("artifact-drawer-title").textContent = name ? "Browser screenshot" : "Live browser";
    get("artifact-filename").textContent = domain;
    get("artifact-detail-meta").replaceChildren();
    const actions = get("artifact-actions");
    actions.replaceChildren();
    detailStatus.textContent = mock ? "Mock browser preview" : "";
    if (name || mock) {
      const src = name ? `/api/browse/screenshots/${name}`
        : `/api/browse/screenshots/demo.png?domain=${encodeURIComponent(domain)}`;
      const image = element("img", "browse-preview");
      image.src = src;
      image.alt = `Screenshot of ${domain}`;
      detailBody.replaceChildren(image);
      if (name) {
        const download = element("a", "artifact-control", "Download PNG");
        download.href = src;
        download.download = "browser-screenshot.png";
        actions.append(download);
      }
    } else {
      const frame = element("iframe", "artifact-pdf browse-live-frame");
      frame.title = `Live view of ${domain}`;
      frame.setAttribute("sandbox", "allow-same-origin allow-scripts");
      frame.referrerPolicy = "no-referrer";
      frame.tabIndex = -1;
      frame.src = liveUrl;
      detailBody.replaceChildren(frame);
    }
    if (!drawer.open) drawer.showModal();
    get("artifact-close").focus();
  }

  function endBrowse(id) {
    if (!id || liveBrowse !== id) return;
    liveBrowse = undefined;
    detailBody.replaceChildren();
    detailStatus.textContent = "This browser session has ended.";
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
      if (inDrawer && drawer.open && selected === item.id) {
        for (const button of drawer.querySelectorAll("button:not(#artifact-close)")) button.disabled = false;
      }
      await show();
    }
  }

  function retry(item) {
    return mutate("retry", item, {});
  }

  function chatActions(linked) {
    const actions = element("div", "artifact-chat-actions");
    for (const artifact of linked) {
      if (artifact.kind === "page") {
        const card = control("", (event) => open(artifact.id, event.currentTarget, artifact), "card chat-file chat-page-file");
        card.dataset.artifactId = artifact.id;
        card.setAttribute("aria-haspopup", "dialog");
        const name = element("span", "chat-file-name");
        name.append(element("strong", "", artifact.title), element("span", "meta", `Page · v${artifact.version_number}`));
        card.append(fileIcon(artifact), name, icon("external", 17));
        actions.append(card);
        continue;
      }
      if (!fileTypes[artifact.format]) continue;
      const card = element("article", "card chat-file");
      const name = element("div", "chat-file-name");
      name.append(element("h3", "", artifact.title), element("p", "meta",
        [fileTypes[artifact.format][0], fileSize(artifact.size)].filter(Boolean).join(" · ")));
      const openFile = iconButton("external", "Open", (event) => open(artifact.id, event.currentTarget));
      openFile.dataset.artifactId = artifact.id;
      openFile.setAttribute("aria-haspopup", "dialog");
      const save = artifact.box_url ? fileLink(artifact, true, true) : iconButton("box", "Save to Box", async (event) => {
        const target = event.currentTarget;
        target.disabled = true;
        try {
          await retry(artifact);
        } finally {
          target.disabled = false;
        }
      });
      const controls = element("div", "chat-file-controls");
      controls.append(openFile, save);
      card.append(fileIcon(artifact), name, controls);
      actions.append(card);
    }
    return actions;
  }

  function renderSettings(info) {
    get("artifact-auto-save").checked = info.settings.auto_save;
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
        folder_name: get("artifact-folder").value }));
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
    selected = detailRequest = liveBrowse = undefined;
    detailBody.replaceChildren();
    opener = undefined;
    if (!get("page-dialog").open) target?.focus();
  });
  get("artifact-refresh").addEventListener("click", show);
  search.addEventListener("input", render);
  kind.addEventListener("change", render);
  sort.addEventListener("change", render);
  for (const button of filters) button.addEventListener("click", () => onFilter(button.dataset.formatFilter));
  for (const mode of ["grid", "list"]) {
    get(`artifact-${mode}`).addEventListener("click", () => {
      layout = mode;
      localStorage.setItem("hearth-artifact-layout", mode);
      render();
    });
  }

  return { show, selectFormat, settings, chatActions, attachmentCards, open, openAttachment, openBrowse, endBrowse };
}
