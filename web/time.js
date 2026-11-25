export const DEFAULT_TIME_ZONE = "America/Los_Angeles";
let timeZone = DEFAULT_TIME_ZONE;
const formatters = new Map();

export function setTimeZone(value) {
  let next = DEFAULT_TIME_ZONE;
  if (value && value !== next) {
    try {
      new Intl.DateTimeFormat("en", { timeZone: value });
      next = value;
    } catch { /* Keep the workspace default for an invalid zone. */ }
  }
  if (next === timeZone) return false;
  timeZone = next;
  formatters.clear();
  return true;
}

export function timeFormatter(options, locale) {
  return { format(value) {
    const key = JSON.stringify([locale, options]);
    if (!formatters.has(key)) {
      formatters.set(key, new Intl.DateTimeFormat(locale, { ...options, timeZone }));
    }
    return formatters.get(key).format(value);
  } };
}

const wallClock = timeFormatter({
  year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
}, "sv-SE");

export const localInputTime = (value) => wallClock.format(new Date(value)).replace(" ", "T");
export const localDay = (value) => localInputTime(value).slice(0, 10);

export function previousDay(value) {
  const day = Date.parse(localDay(value));
  return new Date(day - 86400000).toISOString().slice(0, 10);
}

export function localTimeToISO(value) {
  const wall = Date.parse(value + "Z");
  let estimate = wall;
  // Resolve the zone offset on the target date, including daylight-saving changes.
  for (let attempt = 0; attempt < 3; attempt++) {
    const displayed = localInputTime(estimate);
    if (displayed === value) return new Date(estimate).toISOString();
    estimate += wall - Date.parse(displayed + "Z");
  }
  throw new Error("Choose a time that exists in your workspace time zone.");
}
