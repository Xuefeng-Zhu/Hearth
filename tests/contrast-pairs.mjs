// Sample WCAG AA text, icons, essential control boundaries and visible focus.
export function contrastPairs({ dark, allControls = false, changedControls = false }) {
  const modal = [...document.querySelectorAll("dialog:modal")].at(-1);
  const scope = modal || document.body;
  const pairs = [];
  const colors = new Map();
  const styles = new WeakMap();
  const backgrounds = new WeakMap();
  const read = (el) => {
    if (!styles.has(el)) styles.set(el, getComputedStyle(el));
    return styles.get(el);
  };
  const canvas = document.createElement("canvas").getContext("2d");
  function color(value) {
    if (!colors.has(value)) {
      canvas.fillStyle = "#000";
      canvas.fillStyle = value;
      const hex = canvas.fillStyle;
      const components = hex.startsWith("#") ? hex.slice(1).match(/../g).map((part) => parseInt(part, 16))
        : hex.match(/[\d.]+/g).map(Number);
      colors.set(value, [...components.slice(0, 3), components[3] ?? 1]);
    }
    return colors.get(value);
  }
  const transparent = [0, 0, 0, 0];
  function over(fg, bg) {
    const alpha = fg[3] + bg[3] * (1 - fg[3]);
    return alpha ? [...fg.slice(0, 3).map((value, i) => (value * fg[3] + bg[i] * bg[3] * (1 - fg[3])) / alpha), alpha]
      : transparent;
  }
  const opacity = (value, amount) => [...value.slice(0, 3), value[3] * amount];
  function luminance(value) {
    return value.slice(0, 3).map((channel) => channel / 255)
      .map((channel) => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4)
      .reduce((sum, channel, i) => sum + channel * [0.2126, 0.7152, 0.0722][i], 0);
  }
  function visible(el) {
    if (!el?.checkVisibility({ opacityProperty: true, visibilityProperty: true }) || !el.getClientRects().length
        || el.closest(".visually-hidden, [inert]")) return false;
    for (let ancestor = el; ancestor; ancestor = ancestor.parentElement) {
      if (ancestor.parentElement?.matches("details:not([open])") && ancestor.tagName !== "SUMMARY") return false;
    }
    return true;
  }
  const format = (value) => value.slice(0, 3).map((channel) => Math.round(channel)).join(",");
  function surfaces(el) {
    if (backgrounds.has(el)) return backgrounds.get(el);
    const style = read(el);
    const base = color(style.backgroundColor);
    // Solid CSS colors and the extrema of the app's single-layer gradients.
    const stops = style.backgroundImage.match(/rgba?\([^)]+\)/g) || [];
    const values = [base, ...stops.map((stop) => over(color(stop), base))];
    backgrounds.set(el, values);
    return values;
  }
  function measure(el, value, threshold, sample, outside = false) {
    const path = [];
    for (let parent = outside ? el.parentElement : el; parent; parent = parent.parentElement) path.push(parent);
    let combinations = [[color(value), transparent]];
    for (const layer of path) {
      const alpha = Number(read(layer).opacity);
      combinations = combinations.flatMap(([ink, bg]) => surfaces(layer).map((surface) => [
        opacity(over(ink, surface), alpha), opacity(over(bg, surface), alpha),
      ]));
    }
    const base = color(dark ? "rgb(0,0,0)" : "rgb(255,255,255)");
    const scored = combinations.map(([ink, bg]) => {
      const foreground = over(ink, base), background = over(bg, base);
      const a = luminance(foreground), b = luminance(background);
      return { ratio: (Math.max(a, b) + .05) / (Math.min(a, b) + .05),
        colors: `${format(foreground)} / ${format(background)}` };
    }).sort((a, b) => a.ratio - b.ratio)[0];
    pairs.push({ ...scored, threshold, sample: sample.trim().replace(/\s+/g, " ").slice(0, 80),
      element: el.id ? `#${el.id}` : el.tagName.toLowerCase() + (el.getAttribute("class") ? "." + el.getAttribute("class").split(" ")[0] : "") });
  }
  function text(el, value, style = read(el), multiplier = 1) {
    if (!value?.trim() || el.closest(":disabled, [aria-disabled=true]")) return;
    const size = parseFloat(style.fontSize);
    const threshold = size >= 24 || (size >= 18.667 && Number(style.fontWeight) >= 700) ? 3 : 4.5;
    const rgba = opacity(color(style.color), multiplier);
    measure(el, `rgba(${rgba.join(",")})`, threshold, value);
  }
  const walk = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
  while (walk.nextNode()) {
    const { parentElement: el, textContent } = walk.currentNode;
    if (!textContent.trim() || !visible(el) || el.closest("script, style, select, textarea, svg")) continue;
    const range = document.createRange();
    range.selectNodeContents(walk.currentNode);
    if (!range.getClientRects().length) continue;
    text(el, textContent);
  }
  for (const el of scope.querySelectorAll("input, textarea, select")) {
    if (!visible(el) || el.matches("[type=checkbox], [type=radio], [type=range], [type=color], [type=file]")) continue;
    if (el.matches("select")) text(el, el.selectedOptions[0]?.label);
    else if (el.value) text(el, el.value);
    else if (el.placeholder) {
      const style = getComputedStyle(el, "::placeholder");
      text(el, el.placeholder, style, Number(style.opacity));
    } else if (el.type === "datetime-local") text(el, "Date/time fields");
  }
  if (dark || changedControls || allControls) {
    for (const el of scope.querySelectorAll("svg path, svg circle, svg rect, .dot, .thread-dot, .voice-dot, .artifact-kind-icon, .timeline-chevron, .typing-dots i")) {
      if (!dark && !allControls && !el.closest("#settings-view svg, #skill-editor svg, #workspace-drawer nav svg, .skill-chip svg")) continue;
      if ((el instanceof SVGElement ? !visible(el.ownerSVGElement) : !visible(el))
          || el.closest(".mascot, [hidden], :disabled, [aria-disabled=true]") || read(el).display === "none") continue;
      const style = read(el);
      if (el instanceof SVGElement) {
        const value = style.stroke !== "none" ? style.stroke : style.fill;
        if (value !== "none") measure(el, value, 3, "SVG icon");
      } else {
        const value = el.matches(".artifact-kind-icon") ? style.color
          : el.matches(".timeline-chevron") ? style.borderRightColor : style.backgroundColor;
        measure(el, value, 3, "icon", !el.matches(".artifact-kind-icon"));
      }
    }
    for (const el of scope.querySelectorAll("input, select, textarea, button, .composer, .artifact-control")) {
      if (!visible(el)) continue;
      const style = read(el);
      const sides = ["Top", "Right", "Bottom", "Left"].filter((side) =>
        parseFloat(style[`border${side}Width`]) > 0 && color(style[`border${side}Color`])[3] > 0);
      const essentialEdge = el.matches(".settings-disclosure, .connection-tabs [aria-selected=true], "
        + ".connection-filters :is(input, select), .connector-controls input, .settings-button, .skill-primary, #skill-versions, #skill-markdown");
      const field = el.matches("input:not([type=checkbox], [type=radio], [type=color], [type=range]), textarea:not(.composer textarea), select, .composer");
      const usesFill = el.matches(".card button.primary-setting, .settings-button.primary-setting, .skill-primary, #send");
      if (sides.length && (dark || essentialEdge || (allControls && field)) &&
          !el.closest(":disabled, [aria-disabled=true]") && (dark || !usesFill)) {
        measure(el, style[`border${sides[0]}Color`], 3, "control border", true);
      }
      if (el.matches(":focus-visible") && parseFloat(style.outlineWidth) && style.outlineStyle !== "none") {
        measure(el, style.outlineColor, 3, "focus indicator", parseFloat(style.outlineOffset) >= 0);
      }
    }
    for (const el of scope.querySelectorAll("a:focus-visible, summary:focus-visible, [tabindex]:focus-visible")) {
      if (!visible(el)) continue;
      const style = read(el);
      if (parseFloat(style.outlineWidth) && style.outlineStyle !== "none") {
        measure(el, style.outlineColor, 3, "focus indicator", parseFloat(style.outlineOffset) >= 0);
      }
    }
  }
  return pairs;
}
