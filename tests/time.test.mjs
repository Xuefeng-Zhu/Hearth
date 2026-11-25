import assert from "node:assert/strict";
import { test } from "node:test";
import { localDay, localInputTime, localTimeToISO, previousDay, setTimeZone, timeFormatter } from "../web/time.js";

test("timestamps and day boundaries use the workspace zone", () => {
  const stamp = "2026-11-25T01:16:00Z";
  const clock = timeFormatter({ hour: "2-digit", minute: "2-digit", hourCycle: "h23" }, "en-US");
  assert.equal(clock.format(new Date(stamp)), "17:16");
  assert.equal(localDay(stamp), "2026-11-24");
  assert.equal(previousDay(stamp), "2026-11-23");
  assert.ok(setTimeZone("Asia/Shanghai"));
  assert.equal(clock.format(new Date(stamp)), "09:16");
  assert.equal(localDay(stamp), "2026-11-25");
  setTimeZone();
});

test("datetime fields round-trip in Pacific daylight and standard time", () => {
  assert.equal(localInputTime("2026-07-15T19:00:00Z"), "2026-07-15T12:00");
  assert.equal(localTimeToISO("2026-07-15T12:00"), "2026-07-15T19:00:00.000Z");
  assert.equal(localTimeToISO("2026-11-25T12:00"), "2026-11-25T20:00:00.000Z");
  assert.throws(() => localTimeToISO("2026-03-08T02:30"), /exists/);
});
