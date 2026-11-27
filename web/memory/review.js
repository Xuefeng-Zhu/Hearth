import { useLayoutEffect, useRef, useState } from "preact/hooks";
import { html, Icon } from "../chat/view.js";
import { MemoryButton } from "./view.js";

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

function progress(info) {
  if (info.running) return "Review running…";
  if (!info.last) return "";
  if (info.last.error) return info.last.error;
  if (info.last.status === "interrupted") return "Review interrupted. Run again to check the latest sources.";
  return info.last.count ? "" : "The last pass found no new proposals.";
}

export function createReviewSettings({ api }) {
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

  return settings;
}

function ReviewItems({ review, decide, working }) {
  if (!review) return null;
  const pending = (item) => item.status === "pending";
  return html`
    <div class="memory-review-header">
      <time class="meta" dateTime=${review.at}>${clock.format(new Date(review.at))} Pacific time</time>
      ${review.items.some((item) => pending(item) && item.kind !== "contradiction") && html`
        <${MemoryButton} className="memory-primary" symbol="check" disabled=${working} onClick=${() => decide("accept-all")}>
          Accept all
        </${MemoryButton}>`}
    </div>
    ${review.items.some((item) => pending(item) && item.kind === "contradiction") && html`
      <p class="meta">Accept all applies suggested edits. Review contradictions individually.</p>`}
    ${review.items.map((item) => {
      const [label, symbol, labels] = kinds[item.kind];
      const id = `memory-review-item-${item.id}`;
      return html`<article key=${item.id} class="memory-review-item" aria-labelledby=${id}>
        <h4 id=${id} tabIndex="-1"><${Icon} name=${symbol} size=${16} />${label}</h4>
        ${item.sources.map((source, index) => html`<div class="memory-review-source">
          <strong>${labels[index]}</strong><blockquote>${source.text}</blockquote>
          <p class="meta">${source.kind === "profile" ? "Profile fields" : `${source.path} · line ${source.line}${source.kind === "pinecone" ? " · Pinecone" : ""}`}</p>
        </div>`)}
        ${pending(item) ? html`
          ${item.kind === "contradiction" && html`<p class="meta">Accept acknowledges both versions. Edit the source to resolve them.</p>`}
          <div class="memory-actions">
            <${MemoryButton} className=${item.kind === "contradiction" ? undefined : "memory-primary"}
              symbol="check" disabled=${working} onClick=${() => decide("accept", item.id)}>Accept</${MemoryButton}>
            <${MemoryButton} symbol="x" disabled=${working} onClick=${() => decide("reject", item.id)}>Reject</${MemoryButton}>
          </div>`
          : html`<p class="meta memory-review-result">${statuses[item.status]}</p>`}
      </article>`;
    })}
  `;
}

export function Review({ api, initialDigest }) {
  const heading = useRef(null);
  const focus = useRef();
  const busy = useRef(false);
  const timer = useRef();
  const request = useRef(0);
  const [working, setWorking] = useState(false);
  const [data, setData] = useState({ reviews: [], review: undefined, message: "" });

  function display(info, selected, message) {
    const reviews = info.digests;
    const review = reviews.find((row) => row.id === selected)
      || reviews.find((row) => row.items.some((item) => item.status === "pending")) || reviews[0];
    setData({ reviews, review, message: message || progress(info) || (review ? "" : "Proposals will appear here after a Memory review.") });
  }

  async function load(selected, focusHeading = false) {
    clearTimeout(timer.current);
    const current = ++request.current;
    try {
      const info = await api("/api/memory/review");
      if (request.current !== current) return;
      if (focusHeading) focus.current = true;
      display(info, selected);
      if (info.running) timer.current = setTimeout(() => {
        if (!busy.current) load(selected);
      }, 1250);
    } catch (error) {
      if (request.current === current) setData((data) => ({ ...data, message: error.message }));
    }
  }

  async function decide(operation, item) {
    if (busy.current) return;
    busy.current = true;
    setWorking(true);
    try {
      const info = await api("/api/memory/review/decision", {
        digest: data.review.id, operation, ...(item ? { item } : {}),
      });
      if (!heading.current) return;
      focus.current = item || true;
      display(info, data.review.id, {
        accept: "Proposal reviewed.", reject: "Proposal rejected.", "accept-all": "Suggested edits accepted.",
      }[operation]);
    } catch (error) {
      if (heading.current) setData((data) => ({ ...data, message: error.message }));
    } finally {
      busy.current = false;
      if (heading.current) setWorking(false);
    }
  }

  useLayoutEffect(() => {
    load(initialDigest, Boolean(initialDigest));
    return () => {
      ++request.current;
      clearTimeout(timer.current);
    };
  }, []);
  useLayoutEffect(() => {
    if (!focus.current) return;
    const next = focus.current !== true && document.getElementById(`memory-review-item-${focus.current}`);
    (next || heading.current).focus({ preventScroll: true });
    focus.current = undefined;
  }, [data]);

  return html`<section class="memory-card memory-review">
    <h3 tabIndex="-1" ref=${heading}>Memory review</h3>
    <p class="meta" role="status">${data.message}</p>
    <label class="memory-review-picker" hidden=${data.reviews.length <= 1}>Review date<select id="memory-review-digest"
      disabled=${working} value=${data.review?.id || ""} onChange=${(event) => load(event.currentTarget.value)}>
      ${data.reviews.map((row) => html`<option key=${row.id} value=${row.id}>
        ${clock.format(new Date(row.at))} · ${row.items.filter((item) => item.status === "pending").length} pending
      </option>`)}
    </select></label>
    <div class="memory-review-list"><${ReviewItems} review=${data.review} ...${{ decide, working }} /></div>
  </section>`;
}
