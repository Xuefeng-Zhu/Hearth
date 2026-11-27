import { html } from "./ui.js";

export function highlighted(parts, fallback = "") {
  return parts ? parts.map(({ text, match }) => match ? html`<mark>${text}</mark>` : text) : fallback;
}

export function ListSearchExcerpt({ matches }) {
  return matches?.excerpt ? html`<p class="list-search-excerpt">${highlighted(matches.excerpt)}</p>` : null;
}
