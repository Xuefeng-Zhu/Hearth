// Use untransformed geometry so a surface can be positioned during its entrance.
export function fixedBounds(element) {
  const { offsetLeft: left, offsetTop: top, offsetWidth: width, offsetHeight: height } = element;
  return { left, top, width, height, right: left + width, bottom: top + height };
}

export function anchorOrigin(surface, anchor, bounds = fixedBounds(surface)) {
  const x = Math.max(0, Math.min(bounds.width, anchor.left + anchor.width / 2 - bounds.left));
  const y = bounds.bottom <= anchor.top ? "bottom" : "top";
  surface.style.setProperty("--motion-origin", `${x}px ${y}`);
}

export function freezeAnchor(surface) {
  if (!surface.hasAttribute("data-anchor")) return;
  const { left, top } = fixedBounds(surface);
  surface.style.left = `${left}px`;
  surface.style.top = `${top}px`;
  surface.removeAttribute("data-anchor");
}
