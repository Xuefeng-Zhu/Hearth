export function reconcileChildren(parent, children) {
  const retained = new Set(children);
  for (const child of [...parent.children]) {
    if (!retained.has(child)) child.remove();
  }
  let current = parent.firstElementChild;
  for (const child of children) {
    if (child === current) current = current.nextElementSibling;
    else parent.insertBefore(child, current);
  }
}

export function slashSearchShortcut(event) {
  return event.key === "/" && !event.defaultPrevented && !event.repeat && !event.isComposing
    && !event.altKey && !event.shiftKey && !event.metaKey && !event.ctrlKey
    && !event.target?.isContentEditable && !event.target?.closest?.("input, textarea, select, [role=textbox]");
}

export function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}

export function button(label, action) {
  const item = node("button", "", label);
  item.type = "button";
  item.addEventListener("click", action);
  return item;
}

export function updateText(element, text) {
  if (element.textContent !== text) element.textContent = text;
}
