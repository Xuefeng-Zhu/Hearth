import { icon } from "./icons.js";
import { anchorOrigin } from "./motion.js";

const isPicker = (select) => !select.multiple && select.size <= 1
  && (select.hasAttribute("data-searchable") || select.options.length > 8);
const normalized = (value) => value.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();

export function filterOptions(options, query) {
  const term = normalized(query.trim());
  return options.filter(({ label, value }) => normalized(label).includes(term) || normalized(value).includes(term));
}

const optionDisabled = (option) => option.disabled || option.parentElement?.disabled;
const optionHidden = (option) => option.hidden || option.parentElement?.hidden;

export function commitOption(select, index) {
  const option = select.options[index];
  if (!option || optionDisabled(option) || optionHidden(option) || select.matches(":disabled")) return false;
  const previous = select.value;
  select.selectedIndex = index;
  if (select.value === previous) return false;
  select.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
  select.dispatchEvent(new Event("change", { bubbles: true }));
  return true;
}

export function selectPlacement(select) {
  const parent = select.parentElement;
  return parent?.classList.contains("combobox-field") ? parent : select;
}

function element(tag, className, attributes = {}) {
  const node = document.createElement(tag);
  node.className = className;
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}

function fieldLabel(select) {
  function text(node) {
    if (node.nodeType === Node.TEXT_NODE) return node.textContent;
    if (node.matches?.("select, .combobox-field")) return "";
    return [...node.childNodes].map(text).join("");
  }
  const ids = select.getAttribute("aria-labelledby")?.trim().split(/\s+/) || [];
  const references = ids.map((id) => document.getElementById(id)).filter(Boolean).map(text);
  const labels = [...select.labels].map(text);
  return references.join(" ").trim() || select.getAttribute("aria-label") || labels.join(" ").trim() || "Options";
}

function positionPopup(popup, trigger, mobile) {
  const viewport = window.visualViewport;
  const left = viewport?.offsetLeft ?? 0;
  const top = viewport?.offsetTop ?? 0;
  const width = viewport?.width ?? document.documentElement.clientWidth;
  const height = viewport?.height ?? document.documentElement.clientHeight;
  if (mobile) {
    popup.style.width = `${width}px`;
    popup.style.setProperty("--combobox-available-height", `${height}px`);
    popup.style.left = `${left}px`;
    popup.style.top = `${top + height - popup.offsetHeight}px`;
    return;
  }
  const bounds = trigger.getBoundingClientRect();
  const styles = getComputedStyle(popup);
  const inset = parseFloat(styles.getPropertyValue("--combobox-inset"));
  const gap = parseFloat(styles.getPropertyValue("--combobox-gap"));
  const availableWidth = width - 2 * inset;
  const minimumWidth = parseFloat(styles.getPropertyValue("--combobox-width"));
  const popupWidth = Math.min(Math.max(bounds.width, minimumWidth), availableWidth);
  const below = top + height - inset - bounds.bottom - gap;
  const above = bounds.top - gap - top - inset;
  popup.style.width = `${popupWidth}px`;
  popup.style.setProperty("--combobox-available-height", `${height - 2 * inset}px`);
  const flip = popup.offsetHeight > below && above > below;
  popup.style.setProperty("--combobox-available-height", `${Math.max(0, flip ? above : below)}px`);
  const x = styles.direction === "rtl" ? bounds.right - popupWidth : bounds.left;
  popup.style.left = `${Math.max(left + inset, Math.min(x, left + width - inset - popupWidth))}px`;
  popup.style.top = `${flip ? bounds.top - gap - popup.offsetHeight : bounds.bottom + gap}px`;
  anchorOrigin(popup, bounds);
}

function createPopup() {
  const popup = element("div", "combobox-popup", { popover: "manual" });
  const native = typeof popup.showPopover === "function";
  if (!native) popup.removeAttribute("popover");
  const search = element("input", "combobox-search", {
    type: "text", role: "combobox", "aria-controls": "combobox-options", "aria-autocomplete": "list",
    "aria-expanded": "false", placeholder: "Search options…", autocomplete: "off", tabindex: "-1",
  });
  const searchRow = element("div", "combobox-search-row");
  searchRow.append(icon("search", 17), search);
  const list = element("div", "combobox-list", { id: "combobox-options", role: "listbox" });
  const empty = element("div", "combobox-empty", { role: "status" });
  const mobile = matchMedia("(max-width: 760px)");
  popup.append(searchRow, list, empty);
  popup.hidden = true;
  document.body.append(popup);
  let active;
  let highlighted;
  let enabled = [];
  const sourceOptions = new WeakMap();

  function position() {
    if (!active) return;
    if (!active.trigger.getClientRects().length) close(false);
    else positionPopup(popup, active.trigger, mobile.matches);
  }

  function highlight(item) {
    highlighted?.removeAttribute("data-active");
    highlighted = item;
    if (!item) {
      search.removeAttribute("aria-activedescendant");
      return;
    }
    item.setAttribute("data-active", "");
    search.setAttribute("aria-activedescendant", item.id);
    const bounds = list.getBoundingClientRect();
    const row = item.getBoundingClientRect();
    if (row.top < bounds.top) list.scrollTop -= bounds.top - row.top;
    if (row.bottom > bounds.bottom) list.scrollTop += row.bottom - bounds.bottom;
  }

  function render(edge) {
    if (!active) return;
    const { select, label } = active;
    const previous = sourceOptions.get(highlighted);
    search.setAttribute("aria-label", `Search ${label.toLowerCase()}`);
    list.setAttribute("aria-label", label);
    const options = [...select.options].map((option, index) => ({
      option, index, label: option.label, value: option.value,
    })).filter(({ option }) => !optionHidden(option));
    const matches = filterOptions(options, search.value);
    const content = document.createDocumentFragment();
    const groups = new Map();
    enabled = [];
    let selected;
    for (const { option, index, label } of matches) {
      const group = option.closest("optgroup");
      if (group && !groups.has(group)) {
        const wrapper = element("div", "combobox-group", { role: "group", "aria-label": group.label });
        const header = element("div", "combobox-group-label", { "aria-hidden": "true" });
        header.textContent = group.label;
        wrapper.append(header);
        content.append(wrapper);
        groups.set(group, wrapper);
      }
      const item = element("div", "combobox-option", {
        id: `combobox-option-${index}`, role: "option", "aria-selected": option.selected,
      });
      sourceOptions.set(item, option);
      const text = element("span", "combobox-option-label");
      text.textContent = label;
      item.append(text);
      if (option.selected) item.append(icon("check", 17));
      if (optionDisabled(option)) item.setAttribute("aria-disabled", "true");
      else {
        enabled.push(item);
        if (option.selected) selected = item;
      }
      (groups.get(group) || content).append(item);
    }
    list.replaceChildren(content);
    list.hidden = !matches.length;
    empty.textContent = matches.length ? "" : "No matches";
    position();
    const first = enabled[0];
    highlight(edge === "last" ? enabled.at(-1) : edge === "first" ? first
      : enabled.find((item) => sourceOptions.get(item) === previous) || selected || first);
  }

  function close(restoreFocus = true) {
    if (!active) return;
    const { trigger } = active;
    active = undefined;
    highlight(undefined);
    if (native && popup.matches(":popover-open")) popup.hidePopover();
    popup.hidden = true;
    popup.inert = true;
    trigger.setAttribute("aria-expanded", "false");
    search.setAttribute("aria-expanded", "false");
    if (restoreFocus) trigger.focus({ preventScroll: true });
  }

  function open(control, { query = "", edge } = {}) {
    if (active === control) return close();
    close(false);
    if (control.select.matches(":disabled") || !control.trigger.getClientRects().length) return;
    active = control;
    const parent = control.trigger.closest("dialog") || document.body;
    if (popup.parentElement !== parent) parent.append(popup);
    popup.dir = getComputedStyle(control.trigger).direction;
    search.value = query;
    popup.hidden = false;
    popup.inert = false;
    if (native) popup.showPopover();
    control.trigger.setAttribute("aria-expanded", "true");
    search.setAttribute("aria-expanded", "true");
    list.scrollTop = 0;
    render(edge || (query ? "first" : undefined));
    search.focus({ preventScroll: true });
  }

  function choose(item) {
    if (!active || !item || item.hasAttribute("aria-disabled")) return;
    const { select } = active;
    const option = sourceOptions.get(item);
    if (select.options[option.index] !== option) return;
    close();
    commitOption(select, option.index);
  }

  search.addEventListener("input", () => render("first"));
  search.addEventListener("keydown", (event) => {
    if (!active || event.isComposing || event.ctrlKey || event.altKey || event.metaKey || event.keyCode === 229) return;
    const key = event.key;
    if (key === "Tab") return close();
    if (key === "Escape") close();
    else if (key === "Enter") choose(highlighted);
    else if (key === "Home" || key === "End") highlight(enabled.at(key === "End" ? -1 : 0));
    else if (key === "ArrowDown" || key === "ArrowUp") {
      const step = key === "ArrowDown" ? 1 : -1;
      const current = enabled.indexOf(highlighted);
      highlight(enabled[Math.min(Math.max(0, current + step), enabled.length - 1)]);
    } else return;
    event.preventDefault();
    event.stopPropagation();
  });
  // Keep virtual option focus on the search field for mouse and touch selection.
  list.addEventListener("mousedown", (event) => event.preventDefault());
  list.addEventListener("click", (event) => choose(event.target.closest(".combobox-option")));
  document.addEventListener("pointerdown", (event) => {
    if (active && !popup.contains(event.target) && !active.trigger.contains(event.target)) close();
  }, true);
  document.addEventListener("focusin", (event) => {
    if (active && !popup.contains(event.target) && !active.trigger.contains(event.target)) close(false);
  });
  document.addEventListener("close", (event) => {
    if (active && event.target.contains(popup)) close(false);
  }, true);
  document.addEventListener("scroll", (event) => {
    if (active && !popup.contains(event.target)) position();
  }, true);
  window.addEventListener("resize", position);
  window.visualViewport?.addEventListener("resize", position);
  window.visualViewport?.addEventListener("scroll", position);
  return { open, close, render, isOpen: (control) => active === control };
}

function createControl(select, popup) {
  const wrapper = element("span", "combobox-field");
  const trigger = element("button", "combobox-trigger", {
    type: "button", "aria-haspopup": "listbox", "aria-controls": "combobox-options", "aria-expanded": "false",
  });
  const name = element("span", "visually-hidden");
  const value = element("span", "combobox-value");
  trigger.append(name, value, icon("chevron", 14));
  const hadFocus = select === document.activeElement;
  select.before(wrapper);
  wrapper.append(select, trigger);
  const control = { select, trigger, label: "" };
  const listeners = new AbortController();
  const { signal } = listeners;

  function sync(refresh = false) {
    control.label = fieldLabel(select);
    if (name.textContent !== control.label) name.textContent = control.label;
    const selected = select.selectedOptions[0]?.label ?? "Select an option";
    if (value.textContent !== selected) value.textContent = selected;
    trigger.className = `${select.className} combobox-trigger`.trim();
    trigger.disabled = select.matches(":disabled");
    trigger.hidden = select.hidden;
    trigger.tabIndex = select.tabIndex;
    const description = select.getAttribute("aria-describedby");
    if (description) trigger.setAttribute("aria-describedby", description);
    else trigger.removeAttribute("aria-describedby");
    if (select.validity.valid) trigger.removeAttribute("aria-invalid");
    if (popup.isOpen(control)) {
      if (trigger.disabled || !trigger.getClientRects().length) popup.close(false);
      else if (refresh) popup.render();
    }
  }

  function open(options) {
    sync();
    popup.open(control, options);
  }

  // Assigning these properties updates native selection without a DOM mutation or event.
  const selectionProperties = ["value", "selectedIndex"];
  for (const property of selectionProperties) {
    const descriptor = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, property);
    Object.defineProperty(select, property, {
      configurable: true, get: descriptor.get,
      set(next) {
        descriptor.set.call(this, next);
        sync(true);
      },
    });
  }

  select.addEventListener("input", () => sync(true), { signal });
  select.addEventListener("change", () => sync(true), { signal });
  select.addEventListener("click", () => open(), { signal });
  select.addEventListener("invalid", (event) => {
    if (!trigger.getClientRects().length) return;
    event.preventDefault();
    trigger.setAttribute("aria-invalid", "true");
    trigger.focus();
  }, { signal });
  trigger.addEventListener("click", () => open());
  trigger.addEventListener("keydown", (event) => {
    if (event.isComposing || event.ctrlKey || event.metaKey || event.altKey) return;
    const key = event.key;
    if (["ArrowDown", "Home", "ArrowUp", "End"].includes(key)) {
      open({ edge: key === "ArrowUp" || key === "End" ? "last" : "first" });
    } else if (Array.from(key).length === 1 && key !== " ") open({ query: key });
    else return;
    event.preventDefault();
  });

  select.setAttribute("data-combobox-native", "");
  sync();
  if (hadFocus) trigger.focus({ preventScroll: true });
  return {
    wrapper,
    sync,
    remove() {
      const restoreFocus = popup.isOpen(control) || trigger === document.activeElement;
      if (popup.isOpen(control)) popup.close(false);
      listeners.abort();
      for (const property of selectionProperties) delete select[property];
      select.removeAttribute("data-combobox-native");
      if (select.parentElement === wrapper) wrapper.replaceWith(select);
      else wrapper.remove();
      if (restoreFocus) select.focus({ preventScroll: true });
    },
  };
}

export function setupSearchableSelects() {
  const popup = createPopup();
  const controls = new WeakMap();
  function sync(select) {
    let control = controls.get(select);
    if (control && select.parentElement !== control.wrapper) {
      control.remove();
      controls.delete(select);
      control = undefined;
    }
    if (isPicker(select)) {
      if (control) control.sync(true);
      else controls.set(select, createControl(select, popup));
    } else if (control) {
      control.remove();
      controls.delete(select);
    }
  }

  function collect(element, selects) {
    if (element.matches("select")) selects.add(element);
    for (const select of element.querySelectorAll("select")) selects.add(select);
  }

  const observer = new MutationObserver((mutations) => {
    const selects = new Set();
    for (const { target, type, attributeName, addedNodes, removedNodes } of mutations) {
      const parent = target.nodeType === Node.ELEMENT_NODE ? target : target.parentElement;
      const containing = parent?.closest("select");
      if (containing) selects.add(containing);
      if (type === "attributes" && (attributeName === "hidden" || attributeName === "disabled") && !containing) {
        collect(parent, selects);
      }
      for (const node of [...addedNodes, ...removedNodes]) if (node.nodeType === Node.ELEMENT_NODE) collect(node, selects);
    }
    for (const select of selects) {
      if (select.isConnected) sync(select);
      else if (controls.has(select)) {
        controls.get(select).remove();
        controls.delete(select);
      }
    }
  });
  for (const select of document.querySelectorAll("select")) sync(select);
  observer.observe(document.body, {
    childList: true, subtree: true, characterData: true, attributes: true,
    attributeFilter: ["disabled", "hidden", "label", "value", "selected", "multiple", "size", "data-searchable",
      "class", "tabindex", "aria-label", "aria-labelledby", "aria-describedby"],
  });
  document.addEventListener("reset", (event) => {
    queueMicrotask(() => {
      for (const control of event.target.elements) controls.get(control)?.sync(true);
    });
  }, true);
}
