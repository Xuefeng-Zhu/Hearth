import { h } from "preact";
import htm from "htm";
import { iconAttributes, iconPath } from "./icons.js";

export const html = htm.bind(h);

export function Icon({ name, size = 20 }) {
  return html`<svg ...${iconAttributes(size)}><path ...${iconPath(name)} /></svg>`;
}
