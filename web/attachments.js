import { icon, iconButton } from "./icons.js";
import { reconcileChildren } from "./dom.js";

const MAX_SIZE = 20 * 1024 * 1024;
const MAX_FILES = 10;
const bytes = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });
const get = (id) => document.getElementById(id);

export function fileSize(size) {
  if (!Number.isInteger(size)) return "";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${bytes.format(size / 1024)} KB`;
  return `${bytes.format(size / 1024 / 1024)} MB`;
}

export function fileGlyph(item) {
  if (item.mime?.startsWith("image/")) return "image";
  if (item.mime?.startsWith("audio/")) return "mic";
  return ({ xlsx: "sheet", csv: "sheet", pptx: "slides", pdf: "files",
    docx: "file-text", txt: "file-text", md: "file-text" })[item.format] || "file";
}

export function uploadURL(attachment, route = "", extra = {}) {
  return "/api/uploads" + route + "?" + new URLSearchParams({
    thread: attachment.thread_id, ...(attachment.id ? { id: attachment.id } : {}), ...extra,
  });
}

export function createAttachments({ thread, isChat, isBusy, onChange }) {
  const form = get("composer");
  const pane = form.closest(".chat-pane");
  const picker = get("attachment-files");
  const chips = get("composer-attachments");
  const feedback = get("attachment-status");
  const drafts = new Map();
  let dragDepth = 0;

  function state(threadId = thread()) {
    if (!drafts.has(threadId)) drafts.set(threadId, { entries: [], status: "" });
    return drafts.get(threadId);
  }

  function render() {
    const { entries, status } = state();
    reconcileChildren(chips, entries.map((entry) => entry.chip));
    chips.hidden = !entries.length;
    feedback.textContent = status;
    feedback.hidden = !status;
    onChange(entries.some((entry) => entry.request));
  }

  function resetEntry(entry) {
    entry.request?.abort();
    if (entry.objectURL) URL.revokeObjectURL(entry.objectURL);
  }

  function remove(entry, threadId) {
    const draft = state(threadId);
    draft.entries = draft.entries.filter((item) => item !== entry);
    draft.status = "";
    resetEntry(entry);
    if (threadId === thread()) {
      if (entry.chip.contains(document.activeElement)) get("attach").focus();
      render();
    }
  }

  function thumbnail(visual, src) {
    const image = document.createElement("img");
    image.alt = "";
    image.addEventListener("error", () => visual.replaceChildren(icon("image", 18)), { once: true });
    image.src = src;
    visual.replaceChildren(image);
  }

  function upload(entry, threadId) {
    const { file, chip, progress, info, visual } = entry;
    const request = new XMLHttpRequest();
    entry.request = request;
    chip.dataset.status = "uploading";
    progress.value = 0;
    progress.hidden = false;
    info.textContent = fileSize(file.size) + " · Uploading";
    chip.querySelector(".attachment-retry")?.remove();

    function finish(result, error) {
      entry.request = undefined;
      progress.hidden = true;
      if (result) {
        entry.item = result;
        chip.dataset.status = "ready";
        info.textContent = fileSize(result.size);
        visual.replaceChildren(icon(fileGlyph(result), 19));
        if (result.mime.startsWith("image/")) thumbnail(visual, uploadURL(result, "/file", { thumbnail: "1" }));
        if (entry.objectURL) {
          URL.revokeObjectURL(entry.objectURL);
          entry.objectURL = undefined;
        }
      } else {
        chip.dataset.status = "error";
        info.textContent = error;
        info.title = error;
        const retry = iconButton("retry", `Retry upload of ${file.name}`, () => upload(entry, threadId),
          "icon-button attachment-retry");
        chip.lastElementChild.before(retry);
      }
      if (threadId === thread()) render();
    }

    request.open("POST", uploadURL({ thread_id: threadId }));
    request.responseType = "json";
    request.timeout = 180_000;
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        progress.value = event.loaded / event.total;
        info.textContent = fileSize(file.size) + " · " + Math.round(progress.value * 100) + "%";
      }
    });
    request.addEventListener("load", () => {
      if (request.status === 201 && request.response?.id) finish(request.response);
      else finish(null, request.response?.error || "Upload failed. Try again.");
    });
    request.addEventListener("error", () => finish(null, "Upload failed. Try again."));
    request.addEventListener("timeout", () => finish(null, "Upload timed out. Try again."));
    const body = new FormData();
    body.append("file", file, file.name);
    request.send(body);
    if (threadId === thread()) render();
  }

  function add(files) {
    if (!isChat() || isBusy() || !files.length) return;
    const threadId = thread();
    const draft = state(threadId);
    draft.status = "";
    for (const file of files) {
      if (file.size > MAX_SIZE || file.size === 0) {
        draft.status = file.size ? `${file.name} exceeds 20 MB.` : `${file.name} is empty.`;
        continue;
      }
      if (draft.entries.length >= MAX_FILES) {
        draft.status = `You can attach up to ${MAX_FILES} files per message.`;
        break;
      }
      const chip = document.createElement("div");
      chip.className = "attachment-chip";
      const visual = document.createElement("span");
      visual.className = "attachment-chip-icon";
      const format = file.name.toLowerCase().split(".").at(-1);
      visual.append(icon(fileGlyph({ mime: file.type, format }), 19));
      const labels = document.createElement("span");
      labels.className = "attachment-chip-label";
      const name = document.createElement("strong");
      name.textContent = file.name;
      name.title = file.name;
      const info = document.createElement("small");
      const progress = document.createElement("progress");
      progress.max = 1;
      progress.setAttribute("aria-label", `Uploading ${file.name}`);
      labels.append(name, info, progress);
      const entry = { file, chip, progress, info, visual };
      if (file.type.startsWith("image/") && !/heic|heif/.test(file.type)) {
        entry.objectURL = URL.createObjectURL(file);
        thumbnail(visual, entry.objectURL);
      }
      chip.append(visual, labels, iconButton("x", `Remove ${file.name}`, () => remove(entry, threadId)));
      draft.entries.push(entry);
      upload(entry, threadId);
    }
    render();
  }

  get("attach").addEventListener("click", () => picker.click());
  picker.addEventListener("change", () => { add(picker.files); picker.value = ""; });
  pane.addEventListener("paste", (event) => {
    const files = event.clipboardData?.files;
    if (files?.length) {
      event.preventDefault();
      add(files);
    }
  });
  const includesFiles = (event) => event.dataTransfer?.types.includes("Files");
  pane.addEventListener("dragenter", (event) => {
    if (!includesFiles(event)) return;
    event.preventDefault();
    dragDepth++;
    if (!isBusy()) pane.dataset.dragging = "";
  });
  pane.addEventListener("dragover", (event) => {
    if (includesFiles(event)) {
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    }
  });
  pane.addEventListener("dragleave", () => {
    if (dragDepth && !--dragDepth) delete pane.dataset.dragging;
  });
  pane.addEventListener("drop", (event) => {
    if (!includesFiles(event)) return;
    event.preventDefault();
    dragDepth = 0;
    delete pane.dataset.dragging;
    add(event.dataTransfer.files);
  });

  function selected() {
    const draft = state();
    if (draft.entries.some((entry) => !entry.item)) {
      draft.status = "Wait for the uploads or remove files that could not upload.";
      render();
      return null;
    }
    return draft.entries.map((entry) => entry.item);
  }

  function discard(threadId) {
    drafts.get(threadId)?.entries.forEach(resetEntry);
    drafts.delete(threadId);
    if (threadId === thread()) render();
  }

  function restore(threadId, items) {
    if (drafts.get(threadId)?.entries.length || !items.length) return;
    const draft = state(threadId);
    for (const item of items) {
      const chip = document.createElement("div");
      chip.className = "attachment-chip";
      chip.dataset.status = "ready";
      const visual = document.createElement("span");
      visual.className = "attachment-chip-icon";
      visual.append(icon(fileGlyph(item), 19));
      if (item.mime.startsWith("image/")) thumbnail(visual, uploadURL(item, "/file", { thumbnail: "1" }));
      const labels = document.createElement("span");
      labels.className = "attachment-chip-label";
      const name = document.createElement("strong");
      name.textContent = item.filename;
      const info = document.createElement("small");
      info.textContent = fileSize(item.size);
      labels.append(name, info);
      const entry = { chip, item };
      chip.append(visual, labels, iconButton("x", `Remove ${item.filename}`, () => remove(entry, threadId)));
      draft.entries.push(entry);
    }
    if (threadId === thread()) render();
  }

  return { render, selected, discard, restore, hasDraft: () => state().entries.length > 0 };
}
