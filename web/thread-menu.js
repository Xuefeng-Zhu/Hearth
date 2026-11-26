import { anchorOrigin, fixedBounds, freezeAnchor } from "./motion.js";

export function threadMenuPosition(anchor, menu, viewport, gap, inset) {
  const below = anchor.bottom + gap;
  const above = anchor.top - gap - menu.height;
  const aligned = anchor.right - menu.width;
  const leftEdge = viewport.left + inset;
  const rightEdge = viewport.right - inset - menu.width;
  const topEdge = viewport.top + inset;
  const bottomEdge = viewport.bottom - inset - menu.height;
  const left = aligned < leftEdge ? anchor.left : aligned;
  const top = below > bottomEdge && above >= topEdge ? above : below;
  return {
    left: Math.max(leftEdge, Math.min(left, rightEdge)),
    top: Math.max(topEdge, Math.min(top, bottomEdge)),
  };
}

export function threadMenuIndex(key, current, count) {
  if (!count) return -1;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  if (key === "ArrowDown") return (current + 1) % count;
  if (key === "ArrowUp") return current <= 0 ? count - 1 : current - 1;
  return -1;
}

export function createThreadMenu(menu) {
  const native = typeof menu.showPopover === "function";
  if (!native) menu.removeAttribute("popover");
  const anchors = native && CSS.supports("position-area", "block-end span-inline-start")
    && CSS.supports("position-try-fallbacks", "flip-block, flip-inline");
  const viewport = window.visualViewport;
  const items = () => [...menu.querySelectorAll('[role="menuitem"]:enabled:not([hidden])')];
  let trigger;

  function focusItem(item) {
    if (!item) return;
    item.focus({ preventScroll: true });
    const bounds = menu.getBoundingClientRect();
    const row = item.getBoundingClientRect();
    if (row.top < bounds.top) menu.scrollTop -= bounds.top - row.top;
    else if (row.bottom > bounds.bottom) menu.scrollTop += row.bottom - bounds.bottom;
  }

  function position() {
    const left = viewport?.offsetLeft ?? 0;
    const top = viewport?.offsetTop ?? 0;
    const width = viewport?.width ?? document.documentElement.clientWidth;
    const height = viewport?.height ?? document.documentElement.clientHeight;
    const screen = { left, top, right: left + width, bottom: top + height };
    const styles = getComputedStyle(menu);
    const gap = parseFloat(styles.getPropertyValue("--thread-menu-gap"));
    const inset = parseFloat(styles.getPropertyValue("--thread-menu-inset"));
    menu.style.maxWidth = `${width - 2 * inset}px`;
    menu.style.maxHeight = `${height - 2 * inset}px`;
    menu.style.removeProperty("left");
    menu.style.removeProperty("top");
    menu.toggleAttribute("data-anchor", anchors);
    const bounds = fixedBounds(menu);
    const anchor = trigger.getBoundingClientRect();
    if (!anchors || bounds.left < screen.left + inset || bounds.right > screen.right - inset
        || bounds.top < screen.top + inset || bounds.bottom > screen.bottom - inset) {
      menu.removeAttribute("data-anchor");
      const coords = threadMenuPosition(anchor, bounds, screen, gap, inset);
      menu.style.left = `${coords.left}px`;
      menu.style.top = `${coords.top}px`;
    }

    anchorOrigin(menu, anchor);
  }

  function setTrigger(button) {
    trigger?.setAttribute("aria-expanded", "false");
    trigger = button;
    trigger.setAttribute("aria-expanded", "true");
  }

  function close({ restoreFocus = true } = {}) {
    if (!trigger) return false;
    const button = trigger;
    trigger = undefined;
    freezeAnchor(menu);
    if (native) menu.hidePopover();
    menu.hidden = true;
    menu.inert = true;
    button.setAttribute("aria-expanded", "false");
    if (restoreFocus) button.focus({ preventScroll: true });
    return true;
  }

  function open(button, { last = false } = {}) {
    if (trigger === button) {
      close();
      return;
    }
    close({ restoreFocus: false });
    setTrigger(button);
    menu.hidden = false;
    menu.inert = false;
    if (native) menu.showPopover();
    position();
    menu.scrollTop = 0;
    focusItem(items().at(last ? -1 : 0));
  }

  function refresh(button) {
    setTrigger(button);
    position();
    const enabled = items();
    if (!enabled.includes(document.activeElement)) focusItem(enabled[0]);
  }

  document.addEventListener("click", (event) => {
    if (trigger && !menu.contains(event.target) && !trigger.contains(event.target)) close();
  });
  document.addEventListener("keydown", (event) => {
    if (!trigger || event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    close();
  }, true);
  menu.addEventListener("keydown", (event) => {
    if (event.key === "Tab") {
      close();
      return;
    }
    const enabled = items();
    const next = threadMenuIndex(event.key, enabled.indexOf(document.activeElement), enabled.length);
    if (next < 0) return;
    event.preventDefault();
    focusItem(enabled[next]);
  });
  window.addEventListener("scroll", (event) => {
    if (trigger && (!(event.target instanceof Node) || !menu.contains(event.target))) close();
  }, true);
  window.addEventListener("resize", () => close());
  viewport?.addEventListener("resize", () => close());
  viewport?.addEventListener("scroll", () => close());

  return { open, close, refresh };
}
