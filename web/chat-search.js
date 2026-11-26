import { slashSearchShortcut } from "./dom.js";

const relativeDates = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

export function relativeChatTime(at, now = Date.now()) {
  if (!at) return "";
  const seconds = (Date.parse(at) - now) / 1000;
  if (!Number.isFinite(seconds)) return "";
  const units = [[31536000, "year"], [2592000, "month"], [604800, "week"], [86400, "day"],
    [3600, "hour"], [60, "minute"]];
  const [size, unit] = units.find(([size]) => Math.abs(seconds) >= size) || [1, "second"];
  return unit === "second" && Math.abs(seconds) < 10 ? "Just now" : relativeDates.format(Math.trunc(seconds / size), unit);
}

export function groupChatResults(results) {
  const groups = new Map();
  for (const result of results) {
    if (!groups.has(result.thread_id)) groups.set(result.thread_id, { title: result.thread_title, results: [] });
    groups.get(result.thread_id).results.push(result);
  }
  return [...groups.values()];
}

export function chatSearchShortcut(event) {
  if (event.defaultPrevented || event.repeat || event.isComposing || event.altKey || event.shiftKey) return false;
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") return true;
  return slashSearchShortcut(event);
}
