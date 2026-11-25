import { icon } from "./icons.js";
import { setTimeZone, timeFormatter } from "./time.js";

const dateFormat = timeFormatter({ dateStyle: "medium", timeStyle: "short" });
const devices = { phone: 390, desktop: 1440 };

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function control(label, onClick, glyph) {
  const button = element("button", "page-control");
  button.type = "button";
  if (glyph) button.append(icon(glyph, 16));
  button.append(label);
  button.addEventListener("click", onClick);
  return button;
}

function link(label, href, glyph, download = false) {
  const anchor = element("a", "page-control");
  anchor.href = href;
  if (download) anchor.download = "";
  else {
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
  }
  anchor.append(icon(glyph, 16), label);
  return anchor;
}

function time(value) {
  const stamp = element("time", "page-time", dateFormat.format(new Date(value)));
  stamp.dateTime = value;
  return stamp;
}

export function createPages({ api, openChat }) {
  const get = (name) => document.getElementById(name);
  const dialog = get("page-dialog");
  const title = get("page-dialog-title");
  const work = get("page-workspace");
  const feedback = get("page-feedback");
  const actions = get("page-actions");
  const approval = get("page-approval");
  const stage = get("page-preview-stage");
  const fit = get("page-preview-fit");
  let frame;
  let detail;
  let opener;
  let selected;
  let device;
  let requestId = 0;
  let busy = false;

  function fitPreview() {
    if (!frame || !stage.clientWidth) return;
    const width = devices[device];
    const scale = Math.min(1, stage.clientWidth / width);
    const height = device === "phone" ? 720 : 850;
    fit.style.width = `${width * scale}px`;
    fit.style.height = `${height * scale}px`;
    frame.style.width = `${width}px`;
    frame.style.height = `${height}px`;
    frame.style.transform = `scale(${scale})`;
  }

  function chooseDevice(value) {
    device = value;
    work.dataset.device = value;
    for (const label of Object.keys(devices)) {
      get(`page-${label}`).setAttribute("aria-pressed", String(label === device));
    }
    get("page-size").textContent = `${devices[value]} px`;
    fitPreview();
  }

  async function show() {
    const status = get("pages-status");
    try {
      const result = await api("/api/pages");
      setTimeZone(result.timezone);
      status.textContent = `${result.pages.length} saved ${result.pages.length === 1 ? "page" : "pages"}`;
      get("pages-empty").hidden = result.pages.length > 0;
      get("pages-grid").replaceChildren(...result.pages.map(pageTile));
    } catch (error) {
      status.textContent = error.message;
    }
  }

  function pageTile(page) {
    const tile = control("", (event) => open(page.id, event.currentTarget));
    tile.className = "page-tile";
    tile.dataset.pageId = page.id;
    tile.setAttribute("aria-haspopup", "dialog");
    const artwork = element("span", "page-tile-art");
    artwork.setAttribute("aria-hidden", "true");
    const mockWindow = element("span", "page-tile-window");
    mockWindow.append(element("i"), element("i"), element("i"), element("i"));
    artwork.append(mockWindow, icon("page", 24));
    const information = element("span", "page-tile-information");
    const meta = element("span", "page-tile-meta");
    meta.append(time(page.updated_at), element("span", "page-version-pill", `v${page.version}`));
    information.append(element("strong", "", page.title), meta);
    tile.append(artwork, information);
    return tile;
  }

  function chatCards(rows) {
    const group = element("div", "page-chat-cards");
    for (const row of rows) {
      const card = control("", (event) => open(row.id, event.currentTarget, row.version));
      card.className = "page-chat-card";
      card.dataset.pageId = row.id;
      card.setAttribute("aria-haspopup", "dialog");
      const iconWrap = element("span", "page-chat-icon");
      iconWrap.append(icon("page", 22));
      const copy = element("span", "page-chat-copy");
      copy.append(element("strong", "", row.title), element("span", "", `Web page · v${row.version}`));
      card.append(iconWrap, copy, icon("external", 17));
      group.append(card);
    }
    return group;
  }

  async function open(id, trigger, version) {
    const request = ++requestId;
    opener = trigger;
    detail = undefined;
    frame = undefined;
    busy = false;
    selected = version;
    title.textContent = "Page preview";
    get("page-dialog-version").textContent = "";
    approval.hidden = true;
    feedback.textContent = "Loading page…";
    actions.replaceChildren();
    fit.replaceChildren();
    work.hidden = true;
    if (!dialog.open) dialog.showModal();
    get("page-close").focus();
    chooseDevice(matchMedia("(max-width: 700px)").matches ? "phone" : "desktop");
    try {
      const data = await api(`/api/pages/detail?id=${encodeURIComponent(id)}`);
      if (request !== requestId || !dialog.open) return;
      detail = data;
      if (!data.versions.some((row) => row.version === selected)) selected = data.version;
      feedback.textContent = "";
      render();
    } catch (error) {
      if (request === requestId) feedback.textContent = error.message;
    }
  }

  function render() {
    title.textContent = detail.title;
    get("page-dialog-version").textContent = `Version ${selected}${selected === detail.version ? " · Current" : ""}`;
    work.hidden = false;
    renderActions();
    renderApproval();
    renderVersions();
    const url = versionUrl();
    if (frame?.getAttribute("src") !== url) {
      frame = element("iframe", "page-frame");
      frame.title = `${detail.title} · version ${selected}`;
      frame.setAttribute("sandbox", "");
      frame.setAttribute("referrerpolicy", "no-referrer");
      frame.src = url;
      fit.replaceChildren(frame);
      fitPreview();
    }
  }

  function versionUrl() {
    return `/pages/${encodeURIComponent(detail.id)}/v/${selected}`;
  }

  function renderActions() {
    const box = detail.box_files[String(selected)];
    actions.replaceChildren(
      link("Open in new tab", versionUrl(), "external"),
      link("Download .html", `${versionUrl()}?download=1`, "download", true),
      box ? link("Open in Box", box.url, "box") : control("Save HTML to Box", () => mutate("box"), "box"),
      control(detail.share ? "Manage share link" : "Share link", () => {
        if (detail.share || detail.approval) approval.querySelector("button, a")?.focus();
        else mutate("share");
      }, "share"),
    );
  }

  function renderApproval() {
    approval.replaceChildren();
    approval.hidden = !detail.share && !detail.approval;
    if (detail.share?.url) {
      approval.append(
        element("strong", "", `Version ${detail.share.version} is shared`),
        element("p", "", "Anyone with the link can view this version."),
        link("Open public link", detail.share.url, "external"),
        control("Copy link", async () => {
          try {
            await navigator.clipboard.writeText(new URL(detail.share.url, location.origin).href);
            feedback.textContent = "Public link copied.";
          } catch {
            feedback.textContent = "Open the public link to copy its address.";
          }
        }, "copy"),
        control("Revoke link", () => mutate("revoke")),
      );
    } else if (detail.approval) {
      approval.append(
        element("strong", "", `Share version ${detail.approval.version}?`),
        element("p", "", "Anyone with the link will be able to view this version, including its images."),
        control("Approve share link", () => mutate("approve")),
        control("Cancel", () => mutate("revoke")),
      );
    }
  }

  function renderVersions() {
    get("page-versions").replaceChildren(...[...detail.versions].reverse().map((row) => {
      const item = element("li", "page-history-row");
      const pick = control(`v${row.version}`, () => {
        selected = row.version;
        feedback.textContent = "";
        render();
        get(`page-select-${row.version}`).focus();
      });
      pick.id = `page-select-${row.version}`;
      pick.setAttribute("aria-pressed", String(row.version === selected));
      pick.setAttribute("aria-label", `Preview version ${row.version}${row.version === detail.version ? ", current" : ""}`);
      const note = element("div", "page-history-note");
      note.append(element("p", "", row.note), time(row.at));
      item.append(pick, note);
      if (row.version === selected && selected !== detail.version) {
        const revert = control(`Restore v${row.version}`, () => mutate("revert"), "history");
        revert.classList.add("page-version-restore");
        item.append(revert);
      }
      return item;
    }));
  }

  async function mutate(operation) {
    if (busy) return;
    const request = requestId;
    const id = detail.id;
    const wasShared = !!detail.share?.url;
    busy = true;
    for (const button of dialog.querySelectorAll(".page-control:is(button)")) button.disabled = true;
    try {
      const result = operation === "approve" ? await api("/api/approve", { id: detail.approval.id })
        : await api(`/api/pages/${operation}`, { id, version: selected, current: detail.version });
      const updated = await api(`/api/pages/detail?id=${encodeURIComponent(id)}`);
      if (request !== requestId || !dialog.open) return;
      detail = updated;
      if (operation === "revert") selected = detail.version;
      render();
      const status = {
        share: "", approve: "Public link is ready.", revoke: wasShared ? "Share link revoked." : "Sharing canceled.",
        box: "HTML saved to Box.", revert: `Restored as version ${updated.version}.`,
      };
      feedback.textContent = status[operation];
      if (operation === "share") approval.querySelector("button")?.focus();
      else if (operation === "approve") approval.querySelector("a")?.focus();
      else if (operation === "revert") {
        get(`page-select-${selected}`).focus();
        if (!get("pages-view").hidden) void show();
      } else {
        actions.querySelector(operation === "box" && result.url ? 'a[href*="app.box.com"]' : "button:last-child")?.focus();
      }
    } catch (error) {
      if (request === requestId) feedback.textContent = error.message;
    } finally {
      if (request === requestId) {
        busy = false;
        for (const button of dialog.querySelectorAll(".page-control:is(button)")) button.disabled = false;
      }
    }
  }

  new ResizeObserver(fitPreview).observe(stage);
  for (const value of Object.keys(devices)) get(`page-${value}`).addEventListener("click", () => chooseDevice(value));
  get("page-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => {
    ++requestId;
    fit.replaceChildren();
    frame = undefined;
    const replacement = [...document.querySelectorAll("[data-page-id]")].find((item) =>
      item.dataset.pageId === detail?.id && item.getClientRects().length
    );
    const fallback = get("pages-view").hidden ? get("message") : get("pages-chat");
    (opener?.isConnected ? opener : replacement || fallback)?.focus();
  });
  get("pages-chat").addEventListener("click", openChat);

  return { show, chatCards };
}
