import { node as element } from "../dom.js";
import { icon } from "../icons.js";

export function skillChip(skill, label = "Using skill") {
  const chip = element(skill.id ? "a" : "span", "skill-chip");
  if (skill.id) chip.href = `#skills/${encodeURIComponent(skill.id)}`;
  chip.append(icon("skill", 15), element("span", "", `${label}: ${skill.name}`));
  return chip;
}

export function memoryLabel(hit) {
  if (hit.artifact_id) return hit.heading || "Artifact";
  return `${hit.message_id ? hit.heading : hit.path} · line ${hit.line}`;
}
