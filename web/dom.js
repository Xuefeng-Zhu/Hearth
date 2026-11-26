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

export function appendHighlighted(target, parts, fallback = "") {
  if (!parts) {
    target.append(fallback);
    return target;
  }
  for (const { text, match } of parts) {
    if (match) {
      const mark = document.createElement("mark");
      mark.textContent = text;
      target.append(mark);
    } else target.append(text);
  }
  return target;
}

export function slashSearchShortcut(event) {
  return event.key === "/" && !event.defaultPrevented && !event.repeat && !event.isComposing
    && !event.altKey && !event.shiftKey && !event.metaKey && !event.ctrlKey
    && !event.target?.isContentEditable && !event.target?.closest?.("input, textarea, select, [role=textbox]");
}
