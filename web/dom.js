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
