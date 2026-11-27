import { node as element } from "../dom.js";

export const kinds = {
  plan: ["Plan", "file-text"], list: ["List", "list"], note: ["Note", "file-text"],
  transcript: ["Transcript", "mic"], export: ["Export", "download"],
  page: ["Page", "page"],
};
export const formatFilters = { documents: ["docx", "md", "txt"], pdfs: ["pdf"], sheets: ["xlsx", "csv"], slides: ["pptx"] };

export function artifactFilterFromHash(hash) {
  if (hash === "#artifacts") return "all";
  if (hash === "#pages") return "pages";
  const [, format, kind] = hash.match(/^#artifacts\/([a-z]+)(?:\/([a-z]+))?$/) || [];
  if (kind) return Object.hasOwn(formatFilters, format) && isKindFilter(kind) ? `${format}/${kind}` : undefined;
  if (format === "pages" || Object.hasOwn(formatFilters, format) || isKindFilter(format)) return format;
}

export function isKindFilter(value) {
  return value !== "page" && Object.hasOwn(kinds, value);
}

export function filterParts(value) {
  const [format, kind] = value.split("/");
  return isKindFilter(format) ? ["all", format] : [format, kind];
}

export function csvRows(text) {
  const rows = [];
  let row = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < text.length; index++) {
    const char = text[index];
    if (char === '"') {
      if (quoted && text[index + 1] === '"') {
        value += '"';
        index++;
      } else if (quoted || !value) {
        quoted = !quoted;
      } else {
        value += char;
      }
    } else if (!quoted && (char === "," || char === "\n" || char === "\r")) {
      row.push(value);
      value = "";
      if (char === ",") continue;
      if (char === "\r" && text[index + 1] === "\n") index++;
      rows.push(row);
      row = [];
    } else {
      value += char;
    }
  }
  if (value || row.length || /"$/.test(text)) rows.push([...row, value]);
  return rows;
}

function inlineMarkdown(target, text) {
  const tokens = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\)|https?:\/\/[^\s<>]+[^\s<>.,!?;:)\]])/g;
  let end = 0;
  for (const match of text.matchAll(tokens)) {
    target.append(text.slice(end, match.index));
    const token = match[0];
    if (token.startsWith("[")) {
      const split = token.indexOf("](");
      const link = element("a", "", token.slice(1, split));
      link.href = token.slice(split + 2, -1);
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      target.append(link);
    } else if (token.startsWith("http")) {
      const link = element("a", "", token);
      link.href = token;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      target.append(link);
    } else if (token.startsWith("**")) {
      target.append(element("strong", "", token.slice(2, -2)));
    } else {
      target.append(element(token.startsWith("`") ? "code" : "em", "", token.slice(1, -1)));
    }
    end = match.index + token.length;
  }
  target.append(text.slice(end));
}

export function markdown(text, className = "artifact-markdown") {
  const content = element("div", className);
  const lines = text.split(/\r?\n/);
  const cells = (line) => line.trim().replace(/^\||\|$/g, "").split("|").map((value) => value.trim());
  let block, code;
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index];
    if (line.startsWith("```")) {
      if (!code) {
        code = element("pre");
        content.append(code);
      } else {
        code = undefined;
      }
      block = undefined;
    } else if (code) {
      code.append(line + "\n");
    } else if (line.includes("|") && lines[index + 1]?.includes("|")
               && cells(lines[index + 1]).every((cell) => /^:?-{3,}:?$/.test(cell))) {
      const wrap = element("div", "artifact-table");
      const table = element("table");
      const head = table.createTHead().insertRow();
      const headers = cells(line);
      for (const label of headers) {
        const cell = element("th");
        cell.scope = "col";
        inlineMarkdown(cell, label);
        head.append(cell);
      }
      const body = table.createTBody();
      index += 2;
      while (lines[index]?.includes("|")) {
        const values = cells(lines[index++]);
        const row = body.insertRow();
        headers.forEach((_, column) => inlineMarkdown(row.insertCell(), values[column] || ""));
      }
      index--;
      wrap.append(table);
      content.append(wrap);
      block = undefined;
    } else if (!line.trim()) {
      block = undefined;
    } else if (/^#{1,6} /.test(line)) {
      const level = line.indexOf(" ");
      const heading = element(`h${Math.min(level + 2, 6)}`);
      inlineMarkdown(heading, line.slice(level + 1));
      content.append(heading);
      block = undefined;
    } else {
      const item = /^(?:[-*+] |\d+\. )/.exec(line);
      const quote = line.startsWith("> ");
      const tag = item ? (/^\d/.test(line) ? "OL" : "UL") : quote ? "BLOCKQUOTE" : "P";
      if (block?.tagName !== tag) {
        block = element(tag.toLowerCase());
        content.append(block);
      }
      if (item) {
        const bullet = element("li");
        inlineMarkdown(bullet, line.slice(item[0].length));
        block.append(bullet);
      } else {
        if (block.childNodes.length) block.append(" ");
        inlineMarkdown(block, quote ? line.slice(2) : line);
      }
    }
  }
  return content;
}
