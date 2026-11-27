import { render } from "preact";
import { useLayoutEffect } from "preact/hooks";
import { useAppState, mountStore } from "../store.js";
import { html, Icon } from "../ui.js";

function ThreadRow({ thread, active, onSelect, openMenu, menuId }) {
  const { id, title, status } = thread;
  function showTruncatedTitle({ currentTarget: button }) {
    const label = button.firstElementChild;
    if (id !== "main" && title !== "Main" && label.scrollWidth > label.clientWidth) button.title = title;
  }
  function menuKeys(event) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    openMenu(thread, event.currentTarget, { last: event.key === "ArrowUp" });
  }
  return html`
    <div class="thread-row" data-motion-key=${id}>
      <button type="button" class="thread-link" data-thread=${id} aria-current=${active ? "true" : null}
        onClick=${() => onSelect(id)} onPointerEnter=${showTruncatedTitle}
        onPointerLeave=${({ currentTarget }) => currentTarget.removeAttribute("title")}>
        <span class="thread-label">${title}</span>
        ${status && html`
          <span class="thread-dot" data-status=${status === "Unread reply" ? "unread" : "working"} aria-hidden="true"></span>
          <span class="visually-hidden">${` · ${status}`}</span>
        `}
      </button>
      <button type="button" class="thread-overflow" data-thread=${id} aria-label=${`Actions for ${title}`}
        aria-haspopup="menu" aria-expanded="false" aria-controls=${menuId}
        onClick=${({ currentTarget }) => openMenu(thread, currentTarget)} onKeyDown=${menuKeys}>
        <${Icon} name="more" size=${18} />
      </button>
    </div>
  `;
}

function ThreadList({ onSelect, openMenu, menuId }) {
  const { threadEntries, currentThread } = useAppState();
  return threadEntries.map((thread) => html`
    <${ThreadRow} key=${thread.id} thread=${thread} active=${thread.id === currentThread}
      onSelect=${onSelect} openMenu=${openMenu} menuId=${menuId} />
  `);
}

function ThreadOptions({ select }) {
  const { threadEntries, currentThread } = useAppState();
  useLayoutEffect(() => { select.value = currentThread; }, [threadEntries, currentThread]);
  return threadEntries.map(({ id, title, status }) =>
    html`<option key=${id} value=${id}>${status ? `${title} · ${status}` : title}</option>`);
}

function AvatarOptions({ select, onChange }) {
  const { avatarMode } = useAppState();
  useLayoutEffect(() => { select.value = avatarMode; }, [avatarMode]);
  useLayoutEffect(() => {
    const change = (event) => onChange(event.target.value);
    select.addEventListener("change", change);
    return () => select.removeEventListener("change", change);
  }, [select, onChange]);
  return html`
    <option value="off">Off</option>
    <option value="beside">Beside chat</option>
    <option value="face">Full screen</option>
  `;
}

export const mainThread = { id: "main", title: "Main", busy: false };

export function mountThreadList({ store, list, onSelect, openMenu, menuId }) {
  mountStore(list, store, ThreadList, { onSelect, openMenu, menuId }, ["threadEntries", "currentThread"]);
}

export function mountThreadControls({ store, select, avatarSelect, onAvatarChange }) {
  mountStore(select, store, ThreadOptions, { select }, ["threadEntries", "currentThread"]);
  mountStore(avatarSelect, store, AvatarOptions, { select: avatarSelect, onChange: onAvatarChange }, ["avatarMode"]);
}

function ThreadMenuItems({ thread, pinned, busy }) {
  return html`
    <div id="thread-menu-title" aria-hidden="true">${thread?.title || ""}</div>
    <button type="button" role="menuitem" tabindex="-1" value="summary" disabled=${!thread}>
      <${Icon} name="book" size=${18} />${" Summary"}
    </button>
    <button type="button" role="menuitem" tabindex="-1" value="rename" hidden=${pinned} disabled=${busy || !thread}>
      <${Icon} name="edit" size=${18} />${" Rename"}
    </button>
    <button type="button" role="menuitem" tabindex="-1" value="delete" hidden=${pinned} disabled=${busy || !thread || !!thread.busy}>
      <${Icon} name="trash" size=${18} />${" Delete"}
    </button>
  `;
}

export function renderThreadMenu(host, thread, pinned, busy) {
  render(html`<${ThreadMenuItems} thread=${thread} pinned=${pinned} busy=${busy} />`, host);
}
