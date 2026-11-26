import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { contrastPairs } from "./contrast-pairs.mjs";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_PATH || "playwright");
const url = process.env.HEARTH_QA_URL || "http://127.0.0.1:39519";
const before = process.env.HEARTH_QA_BEFORE_URL;
const shots = process.env.HEARTH_QA_SCREENSHOTS;
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
const failures = new Map();
const minima = new Map();
let measurements = 0;

async function audit(page, state, scheme, width) {
  const changedControls = /^Settings|^workspace drawer$|^Chat$/.test(state);
  const pairs = await page.evaluate(contrastPairs, { dark: scheme === "dark", changedControls });
  assert.ok(pairs.length, `No visible elements in ${state}`);
  measurements += pairs.length;
  for (const pair of pairs) {
    const key = `${scheme} ${pair.threshold === 4.5 ? "body text" : "large text / non-text"}`;
    const location = `${state} at ${width}px`;
    if (pair.ratio < (minima.get(key)?.ratio ?? Infinity)) minima.set(key, { ...pair, location });
    if (pair.ratio + 1e-6 < pair.threshold) {
      const id = `${scheme} ${pair.element} ${pair.colors} ${pair.sample.includes("border") ? "border" : ""}`;
      if (!failures.has(id)) failures.set(id, { ...pair, location, scheme });
    }
  }
}

async function save(page, name) {
  if (shots) await page.screenshot({ path: join(shots, `run19-${name}.png`), animations: "disabled" });
}

async function go(page, id) {
  if (await page.locator("#open-menu").isVisible()) {
    await page.locator("#open-menu").click();
    await page.locator(`#workspace-drawer [data-view=${id}]`).click();
  } else {
    await page.locator(`.sidebar [data-view=${id}]`).click();
  }
  await page.locator(`#${id}-view`).waitFor();
}

async function chooseSetting(page, id) {
  const disclosure = page.locator(`[data-settings=${id}]`);
  const panel = page.locator(`#settings-${id}`);
  if (!await panel.isVisible()) await disclosure.click();
  await panel.waitFor();
}

async function checkMovedSettings(page, check, shot) {
  await chooseSetting(page, "connections");
  for (const name of ["Configured", "Not configured"]) {
    const tab = page.getByRole("tab", { name: new RegExp(`^${name}`) });
    await tab.click();
    const panel = page.locator(`#${await tab.getAttribute("aria-controls")}`);
    await panel.locator(".connection-card").first().waitFor();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth === innerWidth));
    await check(`Settings Connections ${name}`);
    await shot(`settings-connections-${await panel.getAttribute("id")}`);
  }
}

async function checkSkills(page, check, shot) {
  await go(page, "skills");
  await page.locator("#skill-list article").first().waitFor();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth === innerWidth));
  await check("Skills library");
  await shot("skills");
  await page.locator("#skill-new").click();
  await page.locator("#skill-editor:modal").waitFor();
  await check("Skills editor");
  await shot("skills-editor");
  await page.locator("#skill-close").click();
}

async function drawerChecks(page) {
  const toggle = page.locator("#open-menu");
  const drawer = page.locator("#workspace-drawer");
  await toggle.click();
  assert.equal(await toggle.getAttribute("aria-expanded"), "true");
  assert.ok(await drawer.locator("[aria-current=page]").isVisible());
  await page.keyboard.press("Shift+Tab");
  assert.equal(await page.evaluate(() => document.activeElement.dataset.view), "settings");
  await page.keyboard.press("Tab");
  assert.equal(await page.evaluate(() => document.activeElement.getAttribute("aria-label")), "Close menu");
  await page.keyboard.press("Escape");
  await drawer.waitFor({ state: "hidden" });
  await toggle.focus();
  await toggle.click();
  await page.mouse.click((await page.viewportSize()).width - 4, 30);
  await drawer.waitFor({ state: "hidden" });
  await toggle.click();
  const touch = await page.context().newCDPSession(page);
  await touch.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: 235, y: 90 }] });
  await touch.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: 115, y: 95 }] });
  await touch.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await touch.detach();
  await drawer.waitFor({ state: "hidden" });
  assert.equal(await toggle.getAttribute("aria-expanded"), "false");
}

async function screens(scheme, width, height) {
  const mobile = width <= 760;
  const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: scheme,
    reducedMotion: "reduce", isMobile: mobile, hasTouch: mobile });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const check = (state) => audit(page, state, scheme, width);
  const shot = (name) => mobile && scheme === "dark" ? save(page, `dark-${name}`) : undefined;
  page.setDefaultTimeout(7500);
  await page.goto(url);
  assert.equal(await page.title(), "Hearth");
  await go(page, "chat");
  await page.locator(".chat-markdown table").waitFor();
  assert.match(await page.locator(".chat-markdown").first().innerText(), /Seattle weekend/);
  const screenshotLayout = page.locator("#composer");
  if (mobile) {
    assert.ok(Math.abs((await screenshotLayout.boundingBox()).y + (await screenshotLayout.boundingBox()).height - height) <= 1);
    await save(page, `menu-closed-${scheme}`);
    await page.locator("#open-menu").click();
    await check("workspace drawer");
    await save(page, `menu-open-${scheme}`);
    await page.keyboard.press("Escape");
    await page.locator("#workspace-drawer").waitFor({ state: "hidden" });
    await drawerChecks(page);
  }
  await check("Chat");
  await shot("chat");
  await page.locator(".remembered summary").click();
  assert.equal(await page.locator(".message-route").getByText("DeepSeek-V4.1-Flash", { exact: true }).count(), 0);
  await page.locator(".message.assistant").first().press("Enter");
  await page.getByRole("dialog", { name: "Message actions" }).waitFor();
  await check("Chat message menu");
  await page.keyboard.press("Escape");
  await page.locator("#message").focus();
  await check("Chat expanded actions, memory, and focus");
  await page.locator(".remembered summary").click();
  await page.getByRole("button", { name: "Save to Box", exact: true }).first().click();
  await page.locator("#notice").waitFor();
  await check("Chat notice");
  if (mobile) await page.locator("#open-menu").click();
  await page.getByRole("button", { name: "Seattle notes", exact: true }).click();
  await page.getByText("Any good viewpoints?").waitFor();
  const more = page.getByRole("button", { name: "Show more", exact: true });
  await more.click();
  assert.equal(await page.getByRole("button", { name: "Show less", exact: true }).getAttribute("aria-expanded"), "true");
  await page.getByRole("button", { name: "Show less", exact: true }).click();
  await check("Side chat");
  await shot("side-chat");
  await go(page, "timeline");
  await page.locator(".timeline-entry").first().waitFor();
  await shot("timeline");
  if (mobile && scheme === "dark") await save(page, "timeline-after");
  const entryKinds = await page.locator(".timeline-entry").evaluateAll((items) => new Set(items.map((el) => el.dataset.kind)).size);
  assert.ok(entryKinds >= 16, `Only ${entryKinds} Timeline entry kinds`);
  await check("Timeline");
  const detail = page.locator(".timeline-entry[data-kind=search] .timeline-card-head").first();
  await detail.focus();
  await page.keyboard.press("Enter");
  await page.locator(".timeline-entry[data-kind=search] .timeline-raw summary").first().click();
  await page.locator(".timeline-raw pre").first().waitFor();
  await check("Timeline expanded details, raw view, and focus");
  await page.locator(".timeline-card-head").evaluateAll((summaries) => {
    for (const summary of summaries) if (!summary.parentElement.open) summary.click();
  });
  await check("All Timeline entry details");
  await page.locator(".timeline-undo").first().click();
  await page.locator(".timeline-confirm:visible").waitFor();
  await check("Timeline undo confirmation");
  await shot("timeline-undo");
  await page.locator("#timeline-search").fill("no-contrast-fixture-results");
  await page.locator(".timeline-empty").waitFor();
  await check("Timeline empty");
  await page.locator("#timeline-search").fill("");
  await go(page, "artifacts");
  await page.locator(".artifact-card").first().waitFor();
  await check("Artifacts grid");
  await shot("artifacts");
  await page.locator("#artifact-list").click();
  await check("Artifacts list");
  await shot("artifacts-list");
  for (const [format, selector] of Object.entries({ docx: ".artifact-document", pdf: ".artifact-pdf", xlsx: ".artifact-sheet", pptx: ".artifact-slides" })) {
    const card = page.locator(".artifact-card").filter({ has: page.locator(`.artifact-badge.is-${format}`) }).first();
    await card.locator(".artifact-card-title").click();
    await page.locator(selector).waitFor();
    await check(`Artifact ${format.toUpperCase()} drawer`);
    await shot(`artifact-${format}`);
    await page.locator("#artifact-close").click();
  }
  await page.locator("#artifact-search").fill("no-contrast-fixture-results");
  await page.locator("#artifact-empty").waitFor();
  await check("Artifacts empty");
  await page.locator("#artifact-search").fill("");
  await go(page, "memory");
  await page.getByRole("tab", { name: /People/ }).click();
  await page.locator(".memory-note-body").waitFor();
  await check("Memory");
  await shot("memory");
  await go(page, "reminders");
  await page.locator(".delivery-card").first().waitFor();
  await page.locator("#reminder-create summary").click();
  await check("Reminders including create form");
  await shot("reminders");
  await go(page, "inbox");
  await page.locator(".inbox-card").first().waitFor();
  const source = page.locator(".inbox-source summary").first();
  if (await source.isVisible()) await source.click();
  await check("Inbox and source");
  await shot("inbox");
  await go(page, "settings");
  await check("Settings");
  await shot("settings");
  await checkMovedSettings(page, check, (name) => save(page, `${name}-${width}-${scheme}`));
  for (const id of ["brain", "memory", "artifacts", "search", "appearance", "voice", "reminders",
    "proactivity", "approvals", "home"]) {
    await chooseSetting(page, id);
    await check(`Settings ${id}`);
    await shot(`settings-${id}`);
  }
  await checkSkills(page, check, shot);
  await go(page, "chat");
  await page.locator("#start-call").click();
  await page.locator("#call-sheet:modal").waitFor();
  await check("Demo call sheet");
  await page.locator("#call-captions li").nth(1).waitFor();
  await check("Active demo call with captions");
  await shot("call");
  await page.keyboard.press("Escape");
  const done = page.locator("#call-done");
  if (await done.isVisible()) await done.click();
  if (await page.locator("#call-sheet").isVisible()) await page.keyboard.press("Escape");
  await page.locator("#call-sheet").waitFor({ state: "hidden" });
  if (mobile) await page.locator("#open-menu").click();
  await page.locator("#new-thread").click();
  await page.locator("#side-welcome").waitFor();
  await check("Empty side chat");
  assert.deepEqual(errors, [], `Browser exceptions in ${scheme} at ${width}px`);
  console.log(`Audited ${scheme} at ${width} × ${height}`);
  await ctx.close();
}

try {
  if (shots) await mkdir(shots, { recursive: true });
  for (const scheme of ["dark", "light"]) {
    for (const [width, height] of [[390, 844], [1440, 1000]]) await screens(scheme, width, height);
  }
  for (const scheme of ["dark", "light"]) {
    for (const [width, height] of [[375, 812], [430, 932], [844, 390]]) {
      const page = await browser.newPage({ viewport: { width, height }, colorScheme: scheme,
        reducedMotion: "reduce", isMobile: true, hasTouch: true });
      await page.goto(url);
      await drawerChecks(page);
      await page.locator("#open-menu").click();
      await page.locator("#workspace-drawer [data-view=timeline]").click();
      await page.locator(".timeline-entry").first().waitFor();
      if (width === 375) {
        await go(page, "settings");
        await checkMovedSettings(page, (state) => audit(page, state, scheme, width),
          (name) => save(page, `${name}-${width}-${scheme}`));
      }
      await page.close();
    }
  }
  if (before && shots) {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 }, colorScheme: "dark",
      reducedMotion: "reduce", isMobile: true, hasTouch: true });
    await page.goto(before);
    await page.locator(".mobile-tabs [data-view=timeline]").click();
    await page.locator(".timeline-entry").first().waitFor();
    await save(page, "timeline-before");
  }
} finally {
  for (const [key, row] of minima) console.log(`Minimum ${key} ${row.ratio.toFixed(3)}:1 — ${row.sample} (${row.location})`);
  for (const row of [...failures.values()].sort((a, b) => a.ratio - b.ratio)) {
    console.error(`${row.scheme} ${row.ratio.toFixed(3)} < ${row.threshold} ${row.element} "${row.sample}" [${row.colors}] ${row.location}`);
  }
  console.log(`${measurements} contrast measurements, ${failures.size} distinct failures`);
  await browser.close();
}
assert.equal(failures.size, 0, "Some visible colors are below WCAG AA.");
