const paths = {
  message: "M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8z",
  clock: "M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0ZM12 6v6l4 2",
  files: "M14.5 2H8a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7.5ZM14 2v6h6M4 6v14a2 2 0 0 0 2 2h12",
  file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8ZM14 2v6h6",
  "file-text": "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8ZM14 2v6h6M8 13h8m-8 4h8",
  sheet: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8ZM14 2v6h6M8 12h8m-8 4h8m-8 4h8m-5-8v8",
  slides: "M3 4h18M5 4v12h14V4m-7 12v4m-4 2 4-2 4 2M8 12l3-3 2 2 3-3",
  bell: "M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21a2 2 0 0 0 4 0",
  mail: "M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Zm18 3-9 6a2 2 0 0 1-2 0L2 7",
  inbox: "M22 12h-6l-2 3h-4l-2-3H2m3-8h14l3 8v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z",
  plug: "m9 3 4 4m3-4 4 4M8 6l10 10m-9-9-3 3a4 4 0 0 0 0 6l2 2a4 4 0 0 0 6 0l3-3M7 17l-4 4",
  book: "M12 7v14m0-14C9 4 6 3 2 4v15c4-1 7 0 10 2 3-2 6-3 10-2V4c-4-1-7 0-10 3Z",
  settings: "M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7ZM10 3h4l.6 2.6 1.6.9 2.6-.8 2 3.4-1.9 1.8v2.2l1.9 1.8-2 3.4-2.6-.8-1.6.9L14 21h-4l-.6-2.6-1.6-.9-2.6.8-2-3.4 1.9-1.8v-2.2L3.2 9.1l2-3.4 2.6.8 1.6-.9Z",
  menu: "M4 6h16M4 12h16M4 18h16",
  x: "m18 6-12 12M6 6l12 12",
  plus: "M12 5v14M5 12h14",
  send: "M12 19V5M5 12l7-7 7 7",
  phone: "M7 3H4a1 1 0 0 0-1 1c0 9.4 7.6 17 17 17a1 1 0 0 0 1-1v-3l-5-2-1.5 2a14 14 0 0 1-7.5-7.5L9 8 7 3Z",
  mic: "M9 6a3 3 0 1 1 6 0v6a3 3 0 1 1-6 0ZM5 10v2a7 7 0 1 0 14 0v-2m-7 9v3",
  stop: "M7 6h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1Z",
  paperclip: "m21.4 11.6-8.5 8.5a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5",
  copy: "M8 10a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H10a2 2 0 0 1-2-2ZM4 16H3a1 1 0 0 1-1-1V4a2 2 0 0 1 2-2h11a1 1 0 0 1 1 1v1",
  retry: "M3 12a9 9 0 1 1 2 5.7M3 12V5m0 7h7",
  refresh: "M20 7a9 9 0 0 0-15-1L3 9m0-5v5h5m-4 8a9 9 0 0 0 15 1l2-3m0 5v-5h-5",
  "thumbs-up": "M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3m0 11V11l5-9a3 3 0 0 1 3 3l-1 5h5a2 2 0 0 1 2 2.4l-1.5 7A3 3 0 0 1 16.6 22Z",
  share: "M12 15V3m-5 5 5-5 5 5M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7",
  box: "M21 8v13H3V8m-1-5h20v5H2zm8 9h4",
  search: "M17.5 10.5a7 7 0 1 1-14 0 7 7 0 0 1 14 0Zm-2 5L21 21",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  grid: "M3 3h7v7H3Zm11 0h7v7h-7ZM3 14h7v7H3Zm11 0h7v7h-7Z",
  image: "M3 5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Zm6 2a2 2 0 1 0 0 4 2 2 0 0 0 0-4Zm12 10-5-5-9 9",
  download: "M12 3v12m-5-5 5 5 5-5M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3",
  external: "M13 3h8v8m0-8-9 9m7 1v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h6",
  sparkle: "M12 2l2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5z",
  history: "M3 12a9 9 0 1 1 2.6 6.4M3 12V6m0 6h6m3-5v5l3 2",
  check: "m5 12 4 4L19 6",
  "arrow-up": "m7 10 5-5 5 5m-5-5v14",
  "arrow-down": "m7 14 5 5 5-5m-5 5V5",
  chevron: "m6 9 6 6 6-6",
  monitor: "M4 4h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Zm8 14v4m-4 0h8",
  route: "M6 3v12m12-6v12M3 6l3-3 3 3m6 12 3 3 3-3M6 15a3 3 0 0 0 3 3h2m7-9a3 3 0 0 0-3-3h-2",
  wrench: "M14 4a5 5 0 0 0-6 6L3 15a3 3 0 0 0 4 4l5-5a5 5 0 0 0 6-6l-3 3-3-3z",
  home: "m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-6v-7h-4v7H4a1 1 0 0 1-1-1Z",
};

export function icon(name, size = 20) {
  const namespace = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(namespace, "svg");
  const path = document.createElementNS(namespace, "path");
  for (const [key, value] of Object.entries({
    viewBox: "0 0 24 24", width: size, height: size, fill: "none", stroke: "currentColor",
    "stroke-width": "1.75", "stroke-linecap": "round", "stroke-linejoin": "round",
    "aria-hidden": "true", focusable: "false", class: "line-icon",
  })) svg.setAttribute(key, value);
  path.setAttribute("d", paths[name === "thumbs-down" ? "thumbs-up" : name] || paths.file);
  if (name === "thumbs-down") path.setAttribute("transform", "translate(0 24) scale(1 -1)");
  svg.append(path);
  return svg;
}

export function iconButton(name, label, handler, className = "icon-button") {
  const control = document.createElement("button");
  control.type = "button";
  control.className = className;
  control.setAttribute("aria-label", label);
  control.title = label;
  control.append(icon(name, 18));
  control.addEventListener("click", handler);
  return control;
}

export function mountIcons(root = document) {
  for (const element of root.querySelectorAll("[data-icon]")) {
    element.replaceWith(icon(element.dataset.icon, Number(element.dataset.iconSize) || 20));
  }
}
