export const settingsGroups = [
  ["Assistant", [
    ["brain", "Brain", "Models and routing", "route"],
    ["memory", "Memory", "Recall and saved facts", "book"],
    ["search", "Search", "Web search providers", "search"],
    ["voice", "Voice", "Calls and dictation", "mic"],
  ]],
  ["Connected", [
    ["connections", "Connections", "Fly connectors and health", "plug"],
    ["artifacts", "Artifacts", "File sync and Box storage", "files"],
  ]],
  ["Notifications", [
    ["reminders", "Reminders", "Delivery and forwarded mail", "bell"],
    ["feed", "Feed", "Topics and steering", "sparkle"],
    ["proactivity", "Action suggestions", "Quiet hours and email digests", "bell"],
    ["automations", "Automations", "When events trigger actions", "clock"],
    ["watchers", "Watchers", "Public pages and Apify status", "monitor"],
    ["approvals", "Approvals", "When Hearth asks first", "shield"],
  ]],
  ["App", [
    ["home", "Home", "Weather location", "home"],
    ["appearance", "Appearance", "Ember view and style", "image"],
    ["about", "About", "Deployed Hearth version", "history"],
  ]],
];
const sectionNames = new Set(settingsGroups.flatMap(([, sections]) => sections.map(([section]) => section)));
export const configTabs = ["configured", "not-configured"];

export function settingsHash(section, target) {
  return "#settings" + (section ? `/${section}` : "") + (target ? `/${encodeURIComponent(target)}` : "");
}

export function connectionHash(tab) {
  return settingsHash("connections", tab);
}

export function settingsRoute(hash) {
  if (hash === "#settings") return { view: "settings", hash };
  const [root, ...path] = hash.slice(1).split("/");
  const [section, item, extra] = root === "settings" ? path : [root, ...path];
  if (extra !== undefined || (root !== "settings" && root !== "connections") || !sectionNames.has(section)) return;
  const target = section === "connections" && configTabs.includes(item) ? item : undefined;
  return { view: "settings", section, target, hash: settingsHash(section, target) };
}
