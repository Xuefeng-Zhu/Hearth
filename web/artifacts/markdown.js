import { useLayoutEffect, useRef } from "preact/hooks";
import { markdown } from "./format.js";
import { html } from "../ui.js";

export function Markdown({ text, className = "artifact-markdown" }) {
  const host = useRef(null);
  useLayoutEffect(() => {
    host.current.replaceChildren(...markdown(text).childNodes);
  }, [text]);
  return html`<div class=${className} ref=${host}></div>`;
}
