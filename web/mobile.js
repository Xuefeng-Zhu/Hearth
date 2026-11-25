const mobile = matchMedia("(max-width: 680px), (max-width: 950px) and (max-height: 500px) and (pointer: coarse)");

export function setupMobile({ nearBottom, scrollDown }) {
  const get = (id) => document.getElementById(id);
  const threads = get("thread-sheet");
  const more = get("more-sheet");
  const threadPanel = get("thread-panel");
  const threadControls = get("thread-controls");
  const avatarLabel = document.querySelector('label[for="avatar-view"]');
  const avatarSelect = get("avatar-view");
  const threadPicker = get("open-threads");
  const threadHeader = threadPicker.parentElement;
  const avatarOptions = get("mobile-avatar-options");
  const startCall = get("start-call");

  function show(sheet) {
    if (!sheet.open) sheet.showModal();
  }

  threadPicker.addEventListener("click", () => show(threads));
  get("open-more").addEventListener("click", () => show(more));
  threads.addEventListener("close", () => {
    const notice = get("thread-sheet-notice");
    notice.hidden = true;
    notice.textContent = "";
  });
  for (const sheet of [threads, more]) {
    sheet.addEventListener("click", (event) => {
      if (event.target !== sheet) return;
      const { top, bottom, left, right } = sheet.getBoundingClientRect();
      if (event.clientY < top || event.clientY > bottom || event.clientX < left || event.clientX > right) {
        sheet.close();
      }
    });
  }

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
    if (inline) threadPicker.before(avatarLabel, avatarSelect);
    else avatarOptions.append(avatarLabel, avatarSelect);
  }

  function placeControls() {
    if (mobile.matches) {
      get("mobile-thread-panel").append(threadPanel);
      get("mobile-thread-controls").append(threadControls);
      get("send").before(startCall);
    } else {
      for (const sheet of [threads, more]) sheet.close();
      get("chat-view").prepend(threadPanel);
      get("thread-activity").after(threadControls);
    }
    placeAvatarControl();
    if (!mobile.matches) threadPicker.before(startCall);
    scheduleFit();
  }

  mobile.addEventListener("change", placeControls);
  viewport?.addEventListener("resize", scheduleFit);
  viewport?.addEventListener("scroll", scheduleFit);
  placeControls();
  return {
    isMobile: () => mobile.matches,
    showThreads: () => show(threads),
    closeThreads: () => threads.close(),
    closeSheets: () => { threads.close(); more.close(); },
    placeAvatarControl,
  };
}
