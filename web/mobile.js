const mobile = matchMedia("(max-width: 760px), (max-width: 950px) and (max-height: 500px) and (pointer: coarse)");

export function setupMobile({ nearBottom, scrollDown }) {
  const get = (id) => document.getElementById(id);
  const drawer = get("workspace-drawer");
  const toggle = get("open-menu");
  const threadPanel = get("thread-panel");
  const threadControls = get("thread-controls");
  const avatarLabel = document.querySelector('label[for="avatar-view"]');
  const avatarSelect = get("avatar-view");
  const threadHeader = get("thread-title").closest("header");
  const avatarOptions = get("mobile-avatar-options");
  const startCall = get("start-call");

  function closeDrawer() {
    if (!drawer.open) return;
    toggle.setAttribute("aria-expanded", "false");
    drawer.close();
  }

  toggle.addEventListener("click", () => {
    if (drawer.open) return;
    drawer.showModal();
    toggle.setAttribute("aria-expanded", "true");
  });
  drawer.addEventListener("close", () => {
    if (drawer.open) return;
    toggle.setAttribute("aria-expanded", "false");
    const notice = get("drawer-notice");
    notice.hidden = true;
    notice.textContent = "";
    if (mobile.matches) toggle.focus({ preventScroll: true });
  });
  drawer.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeDrawer();
  });
  drawer.querySelector("form").addEventListener("submit", (event) => {
    event.preventDefault();
    closeDrawer();
  });
  drawer.addEventListener("click", (event) => {
    if (event.target !== drawer) return;
    const bounds = drawer.getBoundingClientRect();
    if (event.clientX > bounds.right || event.clientX < bounds.left) closeDrawer();
  });
  drawer.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const items = [...drawer.querySelectorAll("button:enabled, select:enabled, a[href]")]
      .filter((item) => item.getClientRects().length);
    const first = items.at(0), last = items.at(-1);
    if (document.activeElement === (event.shiftKey ? first : last)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    }
  });
  let touchStart;
  drawer.addEventListener("touchstart", ({ touches }) => {
    touchStart = touches.length === 1 ? touches[0] : undefined;
  }, { passive: true });
  drawer.addEventListener("touchend", ({ changedTouches }) => {
    if (!touchStart) return;
    const { clientX, clientY } = changedTouches[0];
    const distance = touchStart.clientX - clientX;
    if (distance > 55 && distance > Math.abs(clientY - touchStart.clientY) * 1.5) closeDrawer();
    touchStart = undefined;
  }, { passive: true });
  drawer.addEventListener("touchcancel", () => { touchStart = undefined; });

  // Safari keeps the layout viewport full-height when the keyboard takes up the visual viewport.
  const viewport = window.visualViewport;
  const root = document.documentElement;
  let frame = 0;
  function fitViewport() {
    frame = 0;
    const keyboard = mobile.matches && viewport?.scale === 1 && root.clientHeight - viewport.height > 100;
    const follow = nearBottom();
    root.toggleAttribute("data-keyboard", keyboard);
    if (keyboard) {
      root.style.setProperty("--keyboard-height", `${viewport.height}px`);
      root.style.setProperty("--keyboard-top", `${viewport.offsetTop}px`);
    } else {
      root.style.removeProperty("--keyboard-height");
      root.style.removeProperty("--keyboard-top");
    }
    if (follow) scrollDown();
  }

  function scheduleFit() {
    if (!frame) frame = requestAnimationFrame(fitViewport);
  }

  function placeAvatarControl() {
    const inline = !mobile.matches || get("chat-view").classList.contains("face-view");
    const host = inline ? threadHeader : avatarOptions;
    if (avatarSelect.parentElement === host) return;
    if (inline) threadHeader.append(avatarLabel, avatarSelect);
    else avatarOptions.append(avatarLabel, avatarSelect);
  }

  function placeControls() {
    get("new-thread-label").textContent = mobile.matches ? "New chat" : "New side chat";
    if (mobile.matches) {
      get("mobile-thread-panel").append(threadPanel);
      get("mobile-thread-controls").append(threadControls);
      get("send").before(startCall);
    } else {
      closeDrawer();
      get("chat-view").prepend(threadPanel);
      get("thread-activity").after(threadControls);
      threadHeader.append(startCall);
    }
    placeAvatarControl();
    if (!mobile.matches) threadHeader.append(startCall);
    scheduleFit();
  }

  mobile.addEventListener("change", placeControls);
  viewport?.addEventListener("resize", scheduleFit);
  viewport?.addEventListener("scroll", scheduleFit);
  placeControls();
  return {
    isMobile: () => mobile.matches,
    closeDrawer,
    placeAvatarControl,
  };
}
