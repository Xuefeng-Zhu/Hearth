import { render as paint } from "preact";
import { html, Icon } from "../chat/view.js";
import { node as element } from "../dom.js";
import { csvRows, filterParts, formatFilters, isKindFilter, kinds, markdown } from "./format.js";
import { fileGlyph, uploadURL } from "../attachments.js";
import { icon, iconButton } from "../icons.js";
import { showLoading } from "../motion.js";
import { createPageDetail } from "../pages.js";
import { createFileQuestions } from "../file-questions.js";
import { setTimeZone, timeFormatter } from "../time.js";

const get = (id) => document.getElementById(id);
const fileTypes = {
  docx: ["DOCX", "file-text"], pdf: ["PDF", "files"], xlsx: ["XLSX", "sheet"], pptx: ["PPTX", "slides"],
};
const legacyTypes = { md: "MD", txt: "TXT", csv: "CSV", json: "JSON" };
const sizeFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });
const statuses = { synced: "Synced to Box", saving: "Saving…", local: "Local only", error: "Sync error" };
const updated = timeFormatter({ month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const updatedDay = timeFormatter({ month: "short", day: "numeric" });

function control(label, action, className = "artifact-control") {
  const button = element("button", className, label);
  button.type = "button";
  button.addEventListener("click", action);
  return button;
}

function fileURL(item, inline = false) {
  if (item.download_url) return inline ? item.inline_url : item.download_url;
  return `/api/artifacts/file?id=${encodeURIComponent(item.id)}${inline ? "&inline=1" : ""}`;
}

function fileIcon(item) {
  const type = fileTypes[item.format];
  const glyph = element("span", `artifact-kind-icon ${type || item.kind === "page" ? `is-${item.format}` : ""}`);
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

function fileLink(item, box = false, compactClass) {
  const label = box ? "Open in Box" : "Download";
  const link = element("a", compactClass || (box ? "artifact-control artifact-box-link" : "artifact-control"));
  link.title = label;
  link.setAttribute("aria-label", label);
  if (!compactClass) link.append(label, " ");
  link.append(icon(box ? "external" : "download", compactClass ? 18 : 15));
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

function Clock({ at, dateOnly = false }) {
  const timestamp = Date.parse(at);
  const valid = Number.isFinite(timestamp);
  const full = valid ? updated.format(timestamp) : "Date unavailable";
  return html`<time title=${full} datetime=${valid ? at : undefined} aria-label=${dateOnly ? full : undefined}>
    ${dateOnly ? (valid ? updatedDay.format(timestamp) : "—") : full}
  </time>`;
}

function KindIcon({ item }) {
  const type = fileTypes[item.format];
  return html`<span class=${`artifact-kind-icon ${type || item.kind === "page" ? `is-${item.format}` : ""}`} aria-hidden="true">
    <${Icon} name=${item.mime ? fileGlyph(item) : type?.[1] || kinds[item.kind]?.[1] || "file"} size=${21} />
  </span>`;
}

function Badge({ text, style = "" }) {
  return html`<span class=${`artifact-badge ${style}`}>${text}</span>`;
}

function Chips({ item }) {
  if (item.kind === "page") return html`<${Badge} text="HTML / Page" style="is-page" /><${Badge} text=${`v${item.version_number}`} />`;
  const type = fileTypes[item.format];
  return html`
    <${Badge} text=${type?.[0] || legacyTypes[item.format] || item.format?.toUpperCase() || "File"}
      style=${type ? `is-${item.format}` : ""} />
    <${Badge} text=${kinds[item.kind]?.[0] || "File"} style=${`is-${item.kind}`} />
    ${item.version_number ? html`<${Badge} text=${`v${item.version_number}`} />` : null}
    ${item.legacy ? html`<${Badge} text="Legacy text" />` : null}
  `;
}

function Sync({ item, saving, role }) {
  const state = saving ? "saving" : item.sync;
  const text = item.kind === "page" && state === "synced" ? "Saved to Box" : statuses[state];
  return html`<span class=${`artifact-sync is-${state}`} role=${role}
    title=${item.sync_message ? `${text} · ${item.sync_message}` : text ?? ""}>
    <span class="artifact-sync-label">${text}</span>
  </span>`;
}

function FileLink({ item, box = false, compact = false }) {
  const label = box ? "Open in Box" : "Download";
  const className = compact ? "artifact-row-action" : box ? "artifact-control artifact-box-link" : "artifact-control";
  return html`<a class=${className} title=${label} aria-label=${label} href=${box ? item.box_url : fileURL(item)}
    target=${box ? "_blank" : undefined} rel=${box ? "noopener noreferrer" : undefined}
    download=${box ? undefined : item.filename}>
    ${compact ? null : label + " "}<${Icon} name=${box ? "external" : "download"} size=${compact ? 18 : 15} />
  </a>`;
}

function ArtifactCard({ item, list, saving, connected, open, retry }) {
  const page = item.kind === "page";
  const role = list ? "cell" : undefined;
  const foot = html`
    <${Sync} ...${{ item, saving, role }} />
    <div class="artifact-modified" role=${role}>
      <${Clock} at=${item.updated_at} dateOnly=${!list} />
      ${list && html`<${Clock} at=${item.updated_at} dateOnly />`}
    </div>
    <div class="artifact-card-links" role=${role}>
      ${item.box_url && html`<${FileLink} item=${item} box compact />`}
      ${!page && item.sync === "error" && connected && !saving && html`
        <button type="button" class="artifact-row-action" aria-label="Retry sync" title="Retry sync" onClick=${() => retry(item)}>
          <${Icon} name="retry" size=${18} />
        </button>`}
      ${(page || fileTypes[item.format] || item.format === "file" || item.legacy) && html`<${FileLink} item=${item} compact />`}
    </div>`;
  const openCard = (event) => {
    if (!event.target.closest("button, a")) event.currentTarget.querySelector(".artifact-card-title").click();
  };
  return html`
    <article class="artifact-card" data-kind=${item.kind} data-id=${item.id} role=${list ? "row" : undefined}
      onClick=${page ? openCard : undefined}>
      <div class="artifact-card-icon" role=${role}><${KindIcon} item=${item} /></div>
      <div class="artifact-card-header" role=${role}>
        <h3><button type="button" class="artifact-card-title" title=${item.title} data-artifact-id=${item.id} aria-haspopup="dialog"
          onClick=${(event) => open(item.id, event.currentTarget, { kind: item.kind })}><span>${item.title}</span></button></h3>
        <div class="artifact-card-meta"><${Chips} item=${item} />${item.size != null && html`
          <span class="artifact-card-size">${fileSize(item.size)}</span>`}</div>
      </div>
      ${list ? foot : html`<div class="artifact-card-foot">${foot}</div>`}
    </article>`;
}

function TablePreview({ rows, label, warning }) {
  const [headers, ...body] = rows;
  return html`<div class="artifact-table" tabindex=${label ? 0 : undefined} role=${label ? "region" : undefined} aria-label=${label}>
    <table>
      ${headers && html`<thead><tr>${headers.map((value) => html`<th scope="col">${value ?? ""}</th>`)}</tr></thead>`}
      ${body.length ? html`<tbody>${body.map((row) => html`<tr>${row.map((value) => html`<td>${value ?? ""}</td>`)}</tr>`)}</tbody>` : null}
    </table>
    ${warning && html`<p class="meta">${warning}</p>`}
  </div>`;
}

function DocumentPreview({ blocks }) {
  const groups = [];
  for (const block of blocks) {
    if (block.type === "bullet" && Array.isArray(groups.at(-1))) groups.at(-1).push(block.text);
    else groups.push(block.type === "bullet" ? [block.text] : block);
  }
  return html`<div class="artifact-document">${groups.map((block) => {
    if (Array.isArray(block)) return html`<ul>${block.map((text) => html`<li>${text}</li>`)}</ul>`;
    if (block.type === "table") return html`<${TablePreview} rows=${block.rows} />`;
    return block.type === "heading" ? html`<h4>${block.text}</h4>` : html`<p>${block.text}</p>`;
  })}</div>`;
}

function Preview({ item }) {
  if (item.image_url) return html`<img class="attachment-preview" alt=${item.filename} src=${item.image_url} />`;
  if (item.audio_url) return html`<audio class="attachment-audio" src=${item.audio_url} controls preload="metadata"></audio>`;
  if (item.inline_pdf) return html`<iframe class="artifact-pdf" title=${`${item.title} PDF preview`}
    src=${fileURL(item, true) + "#toolbar=0&view=FitH"}></iframe>`;
  const data = item.preview;
  if (item.format === "xlsx" && data) return html`<div class="artifact-sheet">
    <h4>${data.sheet}</h4><${TablePreview} rows=${data.rows} label=${data.sheet + " spreadsheet"} />
    ${data.truncated && html`<p class="meta">Preview shows up to 200 rows and 50 columns.</p>`}
  </div>`;
  if (item.format === "pptx" && data) return html`<ol class="artifact-slides">${data.slides.map((slide) => html`<li>
    ${slide.title && html`<h4>${slide.title}</h4>`}
    ${slide.bullets.length ? html`<ul>${slide.bullets.map((line) => html`<li>${line}</li>`)}</ul>` : null}
  </li>`)}</ol>`;
  if (item.format === "docx" && data) return html`<${DocumentPreview} blocks=${data.blocks} />`;
  if (item.format === "md" && Object.hasOwn(item, "content")) return html`<div class="artifact-markdown"
    ref=${(node) => node?.replaceChildren(...markdown(item.content).childNodes)}></div>`;
  if (item.format === "csv" && Object.hasOwn(item, "content")) {
    const rows = csvRows(item.content);
    const truncated = rows.length > 201 || rows.some((row) => row.length > 60);
    return html`<${TablePreview} rows=${rows.slice(0, 201).map((row) => row.slice(0, 60))}
      warning=${truncated ? "Preview shows up to 200 rows and 60 columns." : undefined} />`;
  }
  if (Object.hasOwn(item, "content")) return html`<pre class="artifact-plain">${item.content}</pre>`;
  return html`<p class="artifact-no-preview">${item.download_available
    ? "Download this file to view it." : "Open this file in Box to view it."}</p>`;
}

function Paper({ item, editHint }) {
  return html`<section class="artifact-paper"><h3 class="artifact-section-label">Preview</h3><${Preview} item=${item} />
    ${editHint && html`<p class="artifact-edit-hint meta">Ask Hearth to edit this file and save a new version.</p>`}
  </section>`;
}

function VersionHistory({ item }) {
  const hearth = item.version_source === "hearth";
  return html`<section class="artifact-versions">
    <h3>${hearth ? "Hearth version history" : "Version history"}</h3>
    ${item.versions?.length ? html`<ol>${item.versions.map((version) => html`<li>
      <strong>${version.number ? `Version ${version.number}` : "Box version"}</strong>
      ${version.current && html`<${Badge} text="Current" style="is-box" />`}
      ${version.at && html`<${Clock} at=${version.at} />`}
    </li>`)}</ol>` : !item.warnings?.length && html`<p class="meta">${hearth
      ? "Hearth has no saved versions for this file." : "Box will show the available version history."}</p>`}
    ${item.warnings?.map((warning) => html`<p class="meta">${warning}</p>`)}
  </section>`;
}

export function createArtifacts({ api, openThread, showNotice, refreshChat, onFilter }) {
  const collection = get("artifact-collection");
  const drawer = get("artifact-drawer");
  const detailBody = get("artifact-detail-body");
  const detailStatus = get("artifact-detail-status");
  const search = get("artifact-search");
  const filters = [...get("artifact-filters").querySelectorAll("button")];
  const sort = get("artifact-sort");
  const settingsForm = get("artifact-settings-form");
  const settingsStatus = get("artifact-settings-status");
  const pending = new Set();
  const pageDetail = createPageDetail({ api, onChange: () => {
    if (!get("artifacts-view").hidden) void show();
  } });
  let layout = localStorage.getItem("hearth-artifact-layout") === "list" ? "list" : "grid";
  let activeFilter = "all";
  let snapshot, selected, request, refreshTimer, detailRequest, opener, liveBrowse, confirming = false;
  const questions = createFileQuestions(api);
  function connection(info) {
    const { connected, box_error: error, box_status: freshness, settings } = info;
    const status = get("artifact-box-status");
    status.textContent = !connected ? "Box disconnected" : freshness === "refreshing" ? "Refreshing Box…"
      : error ? "Box needs attention"
      : settings.auto_save ? "Box connected" : "Box auto-save off";
    status.dataset.connected = String(connected && !error);
    get("artifact-connection").hidden = connected && !error;
    get("artifact-connection-copy").textContent = error || "Connect Box to sync the artifacts you save here.";
  }

  function render() {
    const [format, kind] = filterParts(activeFilter);
    collection.dataset.layout = layout;
    get("artifact-grid").setAttribute("aria-pressed", String(layout === "grid"));
    get("artifact-list").setAttribute("aria-pressed", String(layout === "list"));
    for (const button of filters) {
      const value = button.dataset.formatFilter;
      button.setAttribute("aria-pressed", String(value === activeFilter || (value !== "all" && (value === format || value === kind))));
    }
    if (!snapshot) return;
    connection(snapshot);
    const query = search.value.trim().toLocaleLowerCase();
    const all = snapshot.artifacts;
    const matchesType = (item) => (!kind || item.kind === kind) && (format === "all"
      || (format === "pages" ? item.kind === "page" : formatFilters[format].includes(item.format)));
    const rows = all.filter((item) => matchesType(item)
      && [item.title, item.filename, item.thread_title, kinds[item.kind]?.[0], item.source].filter(Boolean)
        .join(" ").toLocaleLowerCase().includes(query));
    const byName = (a, b) => a.title.localeCompare(b.title);
    rows.sort(sort.value === "name" ? byName : (a, b) => ((Date.parse(b.updated_at) || 0)
      - (Date.parse(a.updated_at) || 0)) || byName(a, b));
    get("artifact-count").textContent = `${rows.length}${rows.length !== all.length ? " of " + all.length : ""}
      ${all.length === 1 ? "artifact" : "artifacts"}`.replace(/\s+/g, " ");
    const active = document.activeElement;
    const focusedCard = active.closest(".artifact-card");
    const focusedId = collection.contains(focusedCard) && focusedCard.dataset.id;
    const list = layout === "list" && rows.length;
    if (list) {
      collection.setAttribute("role", "table");
      collection.setAttribute("aria-label", "Artifacts");
    } else {
      collection.removeAttribute("role");
      collection.removeAttribute("aria-label");
    }
    paint(html`
      ${list ? html`<div class="artifact-list-head" role="row">
        ${["", "Name", "Status", "Modified", "Actions"].map((label) => html`
          <span role="columnheader" class=${!label || label === "Actions" ? "visually-hidden" : undefined}>${label}</span>`)}
      </div>` : null}
      ${rows.map((item) => html`<${ArtifactCard} key=${item.id} ...${{
        item, list: layout === "list", saving: pending.has(item.id), connected: snapshot.connected, open, retry,
      }} />`)}
    `, collection);
    if (focusedId) {
      const replacement = [...collection.querySelectorAll("button[data-artifact-id]")]
        .find((button) => button.dataset.artifactId === focusedId);
      const action = active.getAttribute("aria-label");
      const sameAction = action && [...(replacement?.closest(".artifact-card").querySelectorAll(".artifact-row-action") || [])]
        .find((control) => control.getAttribute("aria-label") === action);
      (sameAction || replacement || search).focus({ preventScroll: true });
    }
    get("artifact-empty").hidden = !!rows.length;
    const hasType = all.some(matchesType);
    get("artifact-empty-title").textContent = hasType ? "No matches"
      : format === "pages" ? "No pages yet" : all.length ? "No artifacts of this type" : "No artifacts yet";
    get("artifact-empty-hint").textContent = hasType ? "Try a different search or kind."
      : format === "pages" ? "Ask Hearth in Chat to build a page."
      : all.length ? "Choose another type to see more artifacts."
      : "Ask Hearth to create a document, PDF, spreadsheet, slide deck, or page.";
    get("artifact-clear-filters").hidden = !query && activeFilter === "all";
  }

  function selectFormat(value) {
    activeFilter = value;
    render();
  }

  function chooseFilter(value) {
    const [format, kind] = filterParts(activeFilter);
    if (value === "all" || value === "pages") return onFilter(value);
    if (isKindFilter(value)) {
      if (kind === value) return onFilter(format);
      return onFilter(format === "all" || format === "pages" ? value : `${format}/${value}`);
    }
    onFilter(kind ? `${value}/${kind}` : value);
  }

  async function show({ fromRetry = false, force = false } = {}) {
    if (request) return request;
    clearTimeout(refreshTimer);
    const retry = get("artifact-try-again");
    const problem = get("artifact-load-error");
    retry.disabled = get("artifact-refresh").disabled = true;
    problem.hidden = true;
    if (!snapshot) showLoading(get("artifact-count"), "Loading artifacts…");
    request = api(force ? "/api/artifacts?refresh=1" : "/api/artifacts").then((data) => {
      snapshot = data;
      if (snapshot.timezone) setTimeZone(snapshot.timezone);
      render();
      if (data.box_status === "refreshing") {
        refreshTimer = setTimeout(() => {
          if (!get("artifacts-view").hidden) void show();
        }, 500);
      }
    }).catch((error) => {
      if (!snapshot) get("artifact-count").textContent = "";
      problem.hidden = false;
      get("artifact-error-message").textContent = error.message;
    }).finally(() => {
      request = undefined;
      retry.disabled = get("artifact-refresh").disabled = false;
      if (fromRetry && get("artifacts-view").checkVisibility()) {
        (problem.hidden ? get("artifact-refresh") : retry).focus();
      }
    });
    return request;
  }

  const detailMeta = get("artifact-detail-meta");
  const actions = get("artifact-actions");

  function clearDrawer() {
    for (const host of [detailMeta, actions, detailBody]) {
      paint(null, host);
      host.replaceChildren();
    }
  }

  function renderMeta(item) {
    paint(html`<${KindIcon} item=${item} /><${Chips} item=${item} /><${Sync} item=${item} saving=${pending.has(item.id)} />`, detailMeta);
  }

  function renderDetail(item) {
    if (item.timezone) setTimeZone(item.timezone);
    const toggleConfirm = () => {
      confirming = !confirming;
      renderDetail(item);
      (confirming ? get("artifact-confirm-delete") : actions.lastElementChild).focus();
    };
    const visitThread = (event) => {
      event.preventDefault();
      if (drawer.open) drawer.close();
      openThread(item.thread_id, item.message_id);
    };
    get("artifact-drawer-title").textContent = item.title;
    get("artifact-filename").textContent = [item.filename, fileSize(item.size)].filter(Boolean).join(" · ");
    detailStatus.textContent = item.sync_message || "";
    renderMeta(item);
    paint(html`
      ${(item.download_available || Object.hasOwn(item, "content")) && html`<${FileLink} item=${item} />`}
      ${item.box_url && html`<${FileLink} item=${item} box />`}
      ${item.box_connected && !pending.has(item.id) && ["error", "local"].includes(item.sync) && html`
        <button type="button" class="artifact-control" onClick=${() => retry(item)}>${item.sync === "error" ? "Retry sync" : "Save to Box"}</button>`}
      <button type="button" class="artifact-control artifact-danger" aria-expanded=${String(confirming)}
        onClick=${toggleConfirm}>Move to Trash</button>
    `, actions);
    paint(html`
      ${confirming && html`<div class="artifact-delete">
        <p>${item.box_url
          ? "Move this artifact to Hearth Trash? The file stays in Box. Restore it from Timeline."
          : "Move this artifact to Hearth Trash? Restore it from Timeline."}</p>
        <div class="action-row">
          <button type="button" class="artifact-control" onClick=${toggleConfirm}>Cancel</button>
          <button type="button" class="artifact-control artifact-danger" id="artifact-confirm-delete"
            onClick=${() => mutate("delete", item, { revision: item.revision })}>Move to Hearth Trash</button>
        </div>
      </div>`}
      ${item.thread_id && html`<p class="artifact-detail-source"><span>From </span><a class="artifact-thread" href="#chat"
        onClick=${visitThread}><${Icon} name="external" size=${14} />${" "}${item.thread_title || "Source chat"}</a></p>`}
      <${Paper} item=${item} editHint=${!!fileTypes[item.format] && item.source === "Hearth"} />
      <${VersionHistory} item=${item} />
    `, detailBody);
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
    clearDrawer();
    get("artifact-filename").textContent = "";
    showLoading(detailStatus, "Loading artifact…");
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
    const boxLinkStyle = compact ? "icon-button" : undefined;
    if (item.box_url) return fileLink(item, true, boxLinkStyle);
    const label = "Save to Box";
    const save = compact ? iconButton("box", label, send) : control(label, send);
    async function send(event) {
      const target = event.currentTarget;
      target.disabled = true;
      try {
        const result = await api("/api/uploads/box", { id: item.id, thread_id: item.thread_id });
        target.replaceWith(fileLink(result, true, boxLinkStyle));
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
    clearDrawer();
    paint(html`<${KindIcon} item=${item} /><${Badge} text=${item.format.toUpperCase()} />`, detailMeta);
    showLoading(detailStatus, "Loading attachment…");
    try {
      const attachment = await api(uploadURL(item, "/detail"));
      if (detailRequest !== token || !drawer.open) return;
      actions.append(fileLink(attachment), saveAttachment(attachment, false, () => {
        if (detailRequest === token) detailStatus.textContent = "Attachment saved to Box.";
      }));
      detailStatus.textContent = attachment.warnings?.join(" ") || "";
      paint(html`<${Paper} item=${attachment} />`, detailBody);
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
    clearDrawer();
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
      renderMeta(item);
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
        renderMeta(item);
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
      const save = artifact.box_url ? fileLink(artifact, true, "icon-button") : iconButton("box", "Save to Box", async (event) => {
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

  get("artifact-close").addEventListener("click", () => drawer.close());
  drawer.addEventListener("click", (event) => { if (event.target === drawer) drawer.close(); });
  drawer.addEventListener("close", () => {
    const replacement = [...document.querySelectorAll("button[data-artifact-id]")]
      .find((button) => button.dataset.artifactId === selected && button.getClientRects().length);
    const target = opener?.isConnected ? opener : replacement || (get("artifacts-view").hidden ? get("message") : search);
    selected = detailRequest = liveBrowse = undefined;
    clearDrawer();
    opener = undefined;
    if (!get("page-dialog").open) target?.focus();
  });
  get("artifact-try-again").addEventListener("click", () => show({ fromRetry: true, force: true }));
  get("file-question-open").addEventListener("click", async () => {
    if (!snapshot) await show();
    questions.open(snapshot);
  });
  get("artifact-refresh").addEventListener("click", () => show({ force: true }));
  get("artifact-clear-filters").addEventListener("click", () => {
    search.value = "";
    onFilter("all");
    search.focus();
  });
  search.addEventListener("input", render);
  sort.addEventListener("change", render);
  for (const button of filters) button.addEventListener("click", () => chooseFilter(button.dataset.formatFilter));
  for (const mode of ["grid", "list"]) {
    get(`artifact-${mode}`).addEventListener("click", () => {
      layout = mode;
      localStorage.setItem("hearth-artifact-layout", mode);
      render();
    });
  }

  return { show, selectFormat, settings, chatActions, attachmentCards, open, openAttachment, openBrowse, endBrowse };
}
