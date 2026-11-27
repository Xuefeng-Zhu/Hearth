import { render } from "preact";
import { useLayoutEffect, useMemo, useRef, useState } from "preact/hooks";
import { markdown } from "../artifacts/format.js";
import { mascot, setLook, setPose } from "../avatar.js";
import { reconcileChildren } from "../dom.js";
import { arrive, confirmControl } from "../motion.js";
import { callDuration } from "../time.js";
import { html, Icon } from "../ui.js";

function MessageAction({ icon, label, onClick, ...attributes }) {
  return html`
    <button type="button" class="icon-button" aria-label=${label} title=${label} onClick=${onClick} ...${attributes}>
      <${Icon} name=${icon} size=${18} />
    </button>
  `;
}

function Toolbar({ message, content, prompt, actions }) {
  const [vote, setVote] = useState(() => actions.votes.get(message.id));
  function choose(key, button) {
    const next = vote === key ? undefined : key;
    if (next) actions.votes.set(message.id, next);
    else actions.votes.delete(message.id);
    setVote(next);
    confirmControl(button);
  }
  return html`
    <div class="message-toolbar">
      <div class="message-inline-actions">
        ${content && html`<${MessageAction} icon="copy" label="Copy" onClick=${() => actions.copy(content)} />`}
        ${(prompt?.text || prompt?.attachments.length) &&
          html`<${MessageAction} icon="retry" label="Retry" onClick=${() => actions.restore(prompt)} />`}
        ${[["up", "Helpful"], ["down", "Unhelpful"]].map(([key, label]) => html`
          <${MessageAction} key=${key} icon=${`thumbs-${key}`} label=${label} data-vote=${key}
            aria-pressed=${String(vote === key)} onClick=${({ currentTarget }) => choose(key, currentTarget)} />
        `)}
      </div>
      <div class="message-route">
        ${message.at && html`<time datetime=${message.at} title=${actions.date(message.at)}>${actions.time(message.at)}</time>`}
      </div>
    </div>
  `;
}

function CallMessage({ row }) {
  const { message } = row;
  return html`
    <article class="card call-card" data-message-id=${message.id} ref=${row.bindItem}>
      <div class="card-header">
        <h4>${message.content}</h4>
        <time class="call-card-duration">${callDuration(message.duration)}</time>
      </div>
      ${message.lines.length ? html`
        <details><summary>Call transcript</summary>
          <ol class="call-captions">
            ${message.lines.map(({ role, text }) => html`<li><strong>${role === "user" ? "You" : "Hearth"}</strong><span>${text}</span></li>`)}
          </ol>
        </details>
      ` : html`<p class="meta">No transcript saved.</p>`}
    </article>
  `;
}

function Message({ row, actions }) {
  const { role, message, content, status, prompt, streaming, working, finished, skill, extras, warnings, error, errorInNotice, searchHit } = row;
  const assistant = role === "assistant";
  const saved = !!message?.id;
  const expandable = assistant && saved && !!content;
  const formatted = assistant && saved && !message.file_answer;
  const rendered = useMemo(() => {
    if (!formatted) return null;
    const blocks = markdown(content);
    const paragraph = blocks.childNodes.length === 1 && blocks.firstChild.nodeName === "P"
      ? blocks.firstChild : null;
    const plain = !!paragraph && !paragraph.childElementCount;
    return { host: plain ? paragraph : blocks, plain };
  }, [formatted, content]);
  const [expanded, setExpanded] = useState(false);
  const [partial, setPartial] = useState(null);
  const stream = partial?.row === row ? partial : null;
  const wasWorking = useRef(working);
  const wasExpanded = useRef(expanded);
  const avatar = useRef(null);
  const body = useRef(null), text = useRef(null), notices = useRef(null), toggle = useRef(null);
  const visibleText = stream?.content ?? content;
  const thinking = stream?.working ?? working;
  row.setStream = (update) => setPartial({ ...update, row });

  useLayoutEffect(() => {
    if (!assistant) return;
    if (avatar.current) {
      setLook(avatar.current, row.avatarLook, row.avatarColor);
    } else {
      avatar.current = mascot(row.avatarLook, row.avatarColor);
      row.item.prepend(avatar.current);
    }
  }, [row.avatarLook, row.avatarColor]);

  useLayoutEffect(() => {
    if (!avatar.current) return;
    avatar.current.toggleAttribute("data-still", !working);
    if (saved || finished) setPose(avatar.current, { pose: "idle" });
  }, [working, saved, finished]);

  // The skill and attachment widgets supply DOM nodes directly.
  useLayoutEffect(() => {
    row.avatar = avatar.current;
    if (skill) body.current.prepend(skill);
    body.current.append(...extras);
    return () => {
      skill?.remove();
      for (const extra of extras) extra.remove();
    };
  }, [row]);

  useLayoutEffect(() => {
    if (rendered && !rendered.plain) text.current.replaceChildren(...rendered.host.childNodes);
  }, [rendered]);

  useLayoutEffect(() => {
    if (error) actions.showError(errorInNotice ? notices.current.lastElementChild : text.current, error);
  }, [error, errorInNotice]);

  useLayoutEffect(() => {
    if (saved) return actions.bindMenu(row.item, message, content);
  }, [message?.id, message?.at, content]);

  useLayoutEffect(() => {
    reconcileChildren(row.cardsElement, row.cards);
  }, [row.cards]);

  useLayoutEffect(() => {
    if (stream && wasWorking.current && !thinking && actions.isVisible()) arrive([text.current]);
    wasWorking.current = thinking;
    if (stream?.follow) actions.scrollDown();
  }, [thinking, stream]);

  useLayoutEffect(() => {
    if (wasExpanded.current === expanded || !toggle.current) return;
    wasExpanded.current = expanded;
    if (expanded) toggle.current.scrollIntoView({ block: "nearest" });
    actions.checkCollapsed(toggle.current);
  }, [expanded]);

  const textClass = formatted ? "chat-markdown" : message?.file_answer ? "file-answer-text" : "";
  const TextTag = rendered?.host.localName || "p";
  const textKey = rendered && !rendered.plain ? "markdown" : error && !errorInNotice ? "error" : "text";
  const textContent = rendered?.plain ? rendered.host.textContent : !rendered && textKey !== "error" ? visibleText : null;
  return html`
    <article class=${`message ${role}${searchHit ? " chat-search-hit" : ""}`}
      data-message-id=${message?.id} ref=${row.bindItem} tabIndex=${saved ? 0 : null}
      aria-haspopup=${saved ? "dialog" : null} aria-keyshortcuts=${saved ? "Enter Space Shift+F10" : null}>
      <div class=${thinking ? "message-body message-working" : "message-body"} ref=${body}>
        <div role="status" ref=${notices}>
          ${status && html`<p class="queued-label">${status}</p>`}
          ${warnings.map((warning) => html`<p class="model-warning">${warning}</p>`)}
          ${error && errorInNotice && html`<p class="model-warning"></p>`}
        </div>
        <${TextTag} key=${textKey} ref=${text} hidden=${!visibleText} role=${working ? "status" : null}
          class=${[textClass, expandable && !expanded && "message-clamped"].filter(Boolean).join(" ") || null}>
          ${textContent}
        </${TextTag}>
        ${streaming && html`<span class="typing-dots" aria-hidden="true"><i></i><i></i><i></i></span>`}
        ${expandable && html`
          <button type="button" class="message-expand" hidden aria-expanded=${String(expanded)}
            ref=${toggle} onClick=${() => setExpanded(!expanded)}>${expanded ? "Show less" : "Show more"}</button>
        `}
        <div class="cards" ref=${row.bindCards}></div>
      </div>
      ${assistant && saved && html`<${Toolbar} message=${message} content=${content} prompt=${prompt} actions=${actions} />`}
    </article>
  `;
}

export function renderConversation(host, rows, actions) {
  render(rows.map((row) => row.message?.role === "call"
    ? html`<${CallMessage} key=${row.key} row=${row} />`
    : html`<${Message} key=${row.key} row=${row} actions=${actions} />`), host);
}
