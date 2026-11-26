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

const reduced = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)");
const active = new Set();
let viewTransition;

reduced?.addEventListener?.("change", () => {
  if (!reduced.matches) return;
  viewTransition?.skipTransition();
  for (const animation of active) animation.cancel();
});

function timings() {
  const styles = getComputedStyle(document.documentElement);
  const token = (name) => styles.getPropertyValue(`--motion-${name}`).trim();
  return {
    fast: parseFloat(token("fast")),
    base: parseFloat(token("base")),
    slow: parseFloat(token("slow")),
    stagger: parseFloat(token("stagger")),
    standard: token("standard"),
    enter: token("emphasized-decelerate"),
    exit: token("emphasized-accelerate"),
  };
}

function animate(element, frames, options, done = () => {}) {
  const animation = element.animate(frames, options);
  active.add(animation);
  const cleanup = () => {
    active.delete(animation);
    done();
  };
  animation.finished.then(cleanup, cleanup);
  return animation;
}

export function transitionView(update, enabled) {
  if (!enabled || reduced.matches || !document.startViewTransition || document.hidden) {
    update();
    return;
  }
  viewTransition?.skipTransition();
  const transition = document.startViewTransition(update);
  viewTransition = transition;
  transition.finished.then(clear, clear);
  function clear() {
    if (viewTransition === transition) viewTransition = undefined;
  }
  return transition.updateCallbackDone;
}

export function moveNavHighlight(items, view) {
  if (reduced.matches || !Element.prototype.animate) return;
  const navGroup = ".sidebar, .workspace-drawer";
  for (const to of items.filter((item) => item.dataset.view === view)) {
    const group = to.closest(navGroup);
    const from = items.find((item) => item.closest(navGroup) === group && item.hasAttribute("aria-current"));
    if (!from || from === to || !to.getClientRects().length) continue;
    const oldHighlight = from.querySelector(".nav-motion-highlight");
    const start = (oldHighlight || from).getBoundingClientRect();
    const end = to.getBoundingClientRect();
    oldHighlight?.getAnimations().forEach((animation) => animation.cancel());
    const highlight = document.createElement("span");
    highlight.className = "nav-motion-highlight";
    highlight.setAttribute("aria-hidden", "true");
    to.append(highlight);
    const { base, standard } = timings();
    animate(highlight, [
      { translate: `${start.left - end.left}px ${start.top - end.top}px` },
      { translate: "0 0" },
    ], { duration: base, easing: standard }, () => highlight.remove());
  }
}

const listAnimations = new WeakMap();
const listSelector = "[data-motion-key]";
const heightStates = [{ opacity: 0, scale: "1 .8" }, { opacity: 1, scale: "1 1" }];
const noop = () => {};

export function prepareListMotion(container, keys, { stagger = false } = {}) {
  if (reduced.matches || !Element.prototype.animate || !container.getClientRects().length) return noop;
  const previous = [...container.querySelectorAll(listSelector)];
  if (keys.length === previous.length && keys.every((key, index) => key === previous[index].dataset.motionKey)) return noop;
  const before = new Map(previous.map((element) => [element.dataset.motionKey, {
    element, bounds: element.getBoundingClientRect(),
  }]));
  const removed = new Set(before.keys());
  for (const key of keys) removed.delete(key);
  const clip = removed.size && (container.closest(".threads, .view, dialog") || container).getBoundingClientRect();

  return () => {
    const rows = [...container.querySelectorAll(listSelector)];
    for (const { element } of before.values()) listAnimations.get(element)?.cancel();
    const after = rows.map((element) => [element, element.getBoundingClientRect()]);
    const { fast, base, slow, stagger: step, standard, enter, exit } = timings();
    for (const [index, [element, bounds]] of after.entries()) {
      const prior = before.get(element.dataset.motionKey)?.bounds;
      if (!prior?.width && bounds.width && (!stagger || index < 6)) {
        const frames = stagger ? [{ opacity: 0, translate: "0 6px" }, { opacity: 1, translate: "none" }] : heightStates;
        listAnimations.set(element, animate(element, frames, {
          duration: base, delay: stagger ? index * step : 0, easing: enter, fill: "backwards",
        }));
      } else if (prior?.width && bounds.width) {
        const x = prior.left - bounds.left, y = prior.top - bounds.top;
        if (Math.abs(x) < 1 && Math.abs(y) < 1) continue;
        listAnimations.set(element, animate(element, [
          { translate: `${x}px ${y}px` }, { translate: "none" },
        ], { duration: slow, easing: standard }));
      }
    }

    for (const key of removed) {
      const { element, bounds } = before.get(key);
      if (!bounds.width || bounds.bottom <= clip.top || bounds.top >= clip.bottom) continue;
      const ghost = element.cloneNode(true);
      ghost.removeAttribute("id");
      for (const descendant of ghost.querySelectorAll("[id]")) descendant.removeAttribute("id");
      ghost.classList.add("motion-list-exit");
      ghost.setAttribute("aria-hidden", "true");
      ghost.inert = true;
      Object.assign(ghost.style, {
        left: `${bounds.left}px`, top: `${bounds.top}px`, width: `${bounds.width}px`, height: `${bounds.height}px`,
        clipPath: `inset(${Math.max(0, clip.top - bounds.top)}px 0 ${Math.max(0, bounds.bottom - clip.bottom)}px)`,
      });
      (container.closest("dialog") || document.body).append(ghost);
      animate(ghost, [...heightStates].reverse(), { duration: fast, easing: exit, fill: "forwards" }, () => ghost.remove());
    }
  };
}

export function arrive(elements) {
  if (!elements.length || reduced.matches || !Element.prototype.animate) return;
  const { base, enter } = timings();
  for (const element of elements) {
    animate(element, [{ opacity: 0, translate: "0 6px" }, { opacity: 1, translate: "none" }],
      { duration: base, easing: enter });
  }
}

export function confirmControl(element) {
  if (reduced.matches || !element?.animate) return;
  const { fast, standard } = timings();
  animate(element, [{ scale: .92 }, { scale: 1 }], { duration: fast, easing: standard });
}

export function showLoading(status, message) {
  const skeleton = document.createElement("span");
  skeleton.className = "loading-skeleton";
  skeleton.setAttribute("aria-hidden", "true");
  status.replaceChildren(message, skeleton);
  return status;
}
