import { icon } from "./icons.js";

const kinds = {
  merge: ["Merge duplicate", "check", ["Keep", "Remove duplicate"]],
  contradiction: ["Contradiction", "route", ["Version 1", "Version 2"]],
  promote: ["Add to profile", "user", ["Add this fact", "Also recorded in", "Also recorded in"]],
  stale: ["Mark stale", "clock", ["Mark this line stale"]],
};
const statuses = { accepted: "Accepted", rejected: "Rejected", acknowledged: "Acknowledged" };
const clock = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium", timeStyle: "short", timeZone: "America/Los_Angeles",
});

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function button(label, action, symbol, primary = false) {
  const control = element("button", primary ? "memory-primary" : "");
  control.type = "button";
  if (symbol) control.append(icon(symbol, 16));
  control.append(document.createTextNode(label));
  control.addEventListener("click", action);
  return control;
}

function progress(info) {
  if (info.running) return "Review running…";
  if (!info.last) return "";
  if (info.last.error) return info.last.error;
  if (info.last.status === "interrupted") return "Review interrupted. Run again to check the latest sources.";
  return info.last.count ? "" : "The last pass found no new proposals.";
}

export function createMemoryReview({ api }) {
  const form = document.getElementById("memory-review-settings");
  const controls = form.elements;
  const run = controls.run;
  const feedback = document.getElementById("memory-review-settings-status");
  const upcoming = document.getElementById("memory-review-next");
  let poll;
  let settingsRequest = 0;
  let running = false;
  let saving = false;

  function showSchedule(info, updateInputs) {
    if (updateInputs) {
      controls.enabled.checked = info.enabled;
      controls.time.value = info.time;
    }
    form.querySelector("fieldset").disabled = false;
    upcoming.textContent = info.next_run
      ? `Next run ${clock.format(new Date(info.next_run))} Pacific time`
      : info.enabled ? "Schedule starts when Hearth wakes." : "Nightly review is off.";
    running = info.running;
    run.disabled = running;
    feedback.textContent = progress(info);
  }

  async function settings(follow = false) {
    clearTimeout(poll);
    const sequence = ++settingsRequest;
    try {
      const info = await api("/api/memory/review");
      if (sequence !== settingsRequest) return;
      showSchedule(info, !follow);
      if (info.running && !form.closest("[hidden]")) poll = setTimeout(() => settings(true), 1250);
      else if (follow && info.last?.count && info.last.status === "complete") {
        feedback.textContent = `${info.last.count} new ${info.last.count === 1 ? "proposal" : "proposals"} in Memory review.`;
      }
    } catch (error) {
      if (sequence === settingsRequest) {
        feedback.textContent = error.message;
        run.disabled = false;
      }
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (saving) return;
    saving = true;
    controls.save.disabled = true;
    try {
      const info = await api("/api/memory/review/settings", { enabled: controls.enabled.checked, time: controls.time.value });
      showSchedule(info, true);
      feedback.textContent = "Review schedule saved.";
    } catch (error) {
      feedback.textContent = error.message;
    } finally {
      saving = false;
      controls.save.disabled = false;
    }
  });

  run.addEventListener("click", async () => {
    if (running) return;
    running = true;
    run.disabled = true;
    feedback.textContent = "Review running…";
    try {
      await api("/api/memory/review/run", {});
      await settings(true);
    } catch (error) {
      feedback.textContent = error.message;
      running = false;
      run.disabled = false;
    }
  });

  async function render(root, initialDigest) {
    const heading = element("h3", "", "Memory review");
    heading.tabIndex = -1;
    const status = element("p", "meta");
    status.setAttribute("role", "status");
    const list = element("div", "memory-review-list");
    const section = element("section", "memory-card memory-review");
    section.append(heading, status, list);
    root.append(section);
    let selected = initialDigest;
    let working = false;
    const datePicker = element("select");
    datePicker.id = "memory-review-digest";
    const picker = element("label", "memory-review-picker", "Review date");
    picker.append(datePicker);
    list.before(picker);

    function display(info) {
      const reviews = info.digests;
      const review = reviews.find((row) => row.id === selected)
        || reviews.find((row) => row.items.some((item) => item.status === "pending")) || reviews[0];
      selected = review?.id;
      picker.hidden = reviews.length <= 1;
      datePicker.replaceChildren(...reviews.map((row) => {
        const count = row.items.filter((item) => item.status === "pending").length;
        const option = element("option", "", `${clock.format(new Date(row.at))} · ${count} pending`);
        option.value = row.id;
        return option;
      }));
      datePicker.value = selected || "";
      const notice = progress(info);
      status.textContent = notice || (review ? "" : "Proposals will appear here after a Memory review.");
      list.replaceChildren();
      if (!review) return;
      const header = element("div", "memory-review-header");
      const time = element("time", "meta", `${clock.format(new Date(review.at))} Pacific time`);
      time.dateTime = review.at;
      header.append(time);
      if (review.items.some((item) => item.status === "pending" && item.kind !== "contradiction")) {
        header.append(button("Accept all", () => decide("accept-all"), "check", true));
      }
      list.append(header);
      if (review.items.some((item) => item.kind === "contradiction" && item.status === "pending")) {
        list.append(element("p", "meta", "Accept all applies suggested edits. Review contradictions individually."));
      }
      for (const item of review.items) {
        const [label, symbol, labels] = kinds[item.kind];
        const row = element("article", "memory-review-item");
        const title = element("h4", "", label);
        title.id = `memory-review-item-${item.id}`;
        title.tabIndex = -1;
        title.prepend(icon(symbol, 16));
        row.setAttribute("aria-labelledby", title.id);
        row.append(title);
        for (const [index, source] of item.sources.entries()) {
          const evidence = element("div", "memory-review-source");
          const excerpt = element("blockquote", "", source.text);
          const origin = source.kind === "profile" ? "Profile fields"
            : `${source.path} · line ${source.line}${source.kind === "pinecone" ? " · Pinecone" : ""}`;
          evidence.append(element("strong", "", labels[index]), excerpt, element("p", "meta", origin));
          row.append(evidence);
        }
        if (item.status !== "pending") {
          row.append(element("p", "meta memory-review-result", statuses[item.status]));
        } else {
          if (item.kind === "contradiction") {
            row.append(element("p", "meta", "Accept acknowledges both versions. Edit the source to resolve them."));
          }
          const actions = element("div", "memory-actions");
          actions.append(button("Accept", () => decide("accept", item.id), "check", item.kind !== "contradiction"),
            button("Reject", () => decide("reject", item.id), "x"));
          row.append(actions);
        }
        list.append(row);
      }
    }

    async function decide(operation, item) {
      if (working) return;
      working = true;
      list.querySelectorAll("button").forEach((control) => { control.disabled = true; });
      datePicker.disabled = true;
      try {
        const info = await api("/api/memory/review/decision", {
          digest: selected, operation, ...(item ? { item } : {}),
        });
        if (!section.isConnected) return;
        display(info);
        const next = item && document.getElementById(`memory-review-item-${item}`);
        (next || heading).focus({ preventScroll: true });
        status.textContent = {
          accept: "Proposal reviewed.", reject: "Proposal rejected.", "accept-all": "Suggested edits accepted.",
        }[operation];
      } catch (error) {
        status.textContent = error.message;
      } finally {
        working = false;
        datePicker.disabled = false;
        list.querySelectorAll("button").forEach((control) => { control.disabled = false; });
      }
    }

    async function load(focus = false) {
      try {
        const info = await api("/api/memory/review");
        if (!section.isConnected) return;
        display(info);
        if (focus) heading.focus({ preventScroll: true });
        if (info.running) setTimeout(() => {
          if (section.isConnected && !working) load();
        }, 1250);
      } catch (error) {
        status.textContent = error.message;
      }
    }
    datePicker.addEventListener("change", () => {
      selected = datePicker.value;
      load();
    });
    await load(Boolean(initialDigest));
  }

  return { render, settings };
}
