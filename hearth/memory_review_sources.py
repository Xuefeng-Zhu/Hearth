"""Collect review evidence and build edits from the original Markdown."""

import re
from collections import defaultdict

from . import memory, recall
from .proactive_context import private_match, private_text
from .storage import HearthError

POLICY_NOTES = {memory.APPROVAL_NOTE, memory.PROACTIVITY_NOTE}
MAX_TEXT = 800
STALE = " _(marked stale)_"
BLOCK = re.compile(r"^\s*(?:#{1,6}\s|>|<|\||\[.+\]:|(?:[-*_]\s*){3,}$)")
BULLET = re.compile(r"^\s*(?:[-*+] |\d+[.)] )")


def fact(text):
    return BULLET.sub("", text, count=1).strip()


def fact_key(text):
    return " ".join(fact(text).casefold().rstrip(".").split())


def safe(text, rules):
    return (0 < len(text) <= MAX_TEXT and private_text(text) == text
            and not private_match(text, rules))


def note_sources(path, raw, rules):
    data, body, offset = memory.parse(path, raw)
    if private_text(path) != path or private_match(path + " " + raw, rules):
        return
    if path == memory.PROFILE_NOTE:
        # Keep profile field names alongside their values so a conflict shows both versions.
        profile = data["profile"]
        fields = [(key, value) for key, value in profile.items() if isinstance(value, str) and key != "phone"]
        fields += list(profile["work"].items())
        fields += [(key, value) for key in ("pets", "interests", "communication") for value in profile[key]]
        for label, value in fields:
            text = f"{label.replace('_', ' ').capitalize()}: {value}"
            if value and safe(text, rules):
                yield {"kind": "profile", "path": path, "line": 1, "text": text, "context": "Profile"}
    lines = body.splitlines()
    heading, fence = "", ""
    for index, line in enumerate(lines):
        text = line.strip()
        if match := re.match(r"^(`{3,}|~{3,})", text):
            marker = match[1]
            if not fence:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = ""
            continue
        if fence or line.startswith(("    ", "\t")):
            continue
        if match := memory.HEADING.fullmatch(text):
            heading = match[1]
            continue
        if not safe(text, rules) or BLOCK.match(text) or not fact_key(text) or text.endswith(STALE):
            continue
        # Only standalone paragraphs or simple list entries can be changed by a proposal.
        neighbours = lines[max(0, index - 1):index] + lines[index + 1:index + 2]
        if BULLET.match(text):
            editable = not any(other.startswith((" ", "\t")) for other in lines[index + 1:index + 2])
        else:
            editable = not any(other.strip() and not BLOCK.match(other) and not BULLET.match(other)
                               for other in neighbours)
        yield {"kind": "note" if editable else "excerpt", "path": path, "line": index + offset + 1,
               "text": text, "context": heading if safe(heading, rules) else ""}


def note_snapshot(storage):
    return {path: storage.memory_path(path).stat().st_mtime_ns
            for path in storage.files() if path not in POLICY_NOTES}


def window(rows, offset, limit):
    if len(rows) <= limit:
        return rows
    start = offset % len(rows)
    return (rows[start:] + rows[:start])[:limit]


def collect(storage, paths, rules, offset, limit):
    profile, notes = [], []
    for path in paths:
        rows = note_sources(path, storage.read(path), rules)
        (profile if path == memory.PROFILE_NOTE else notes).extend(rows)
    return profile[:32] + window(notes, offset, limit)


def indexed_sources(records, notes, rules):
    indexed = defaultdict(list)
    for item in records:
        indexed[item["path"]].append(item)
    for row in notes:
        if any(item["line"] <= row["line"] <= item["end_line"] and row["text"] in item["excerpt"]
               for item in indexed.get(row["path"], [])):
            row["indexed"] = True
    # Other indexed entries may flag a conflict. Only note lines can be edited or promoted.
    return [{"kind": "pinecone", "path": item["path"], "line": item["line"], "text": item["excerpt"],
             "context": item["source"]}
            for item in records if item["source"] != "Markdown"
            and safe(item["excerpt"], rules) and safe(item["path"], rules)
            and not private_match(recall.vector_text(item), rules)]


def current_line(source, raw, rules):
    candidates = [row for row in note_sources(source["path"], raw, rules)
                  if all(row[key] == source[key] for key in ("kind", "text", "context"))]
    for row in candidates:
        if row["line"] == source["line"]:
            return row["line"]
    if len(candidates) == 1:
        return candidates[0]["line"]
    raise HearthError("A source changed. Reject the outdated proposal or run Memory review again.")


def build_edits(storage, items, rules):
    raw, edits, promotions = {}, defaultdict(dict), {}

    def line(source):
        path = source["path"]
        if path not in raw:
            if not storage.memory_path(path).is_file():
                raise HearthError("A source was removed. Reject the outdated proposal.")
            raw[path] = storage.read(path)
        return current_line(source, raw[path], rules)

    for item in items:
        kind, sources = item["kind"], item["sources"]
        if kind == "contradiction":
            continue
        locations = [line(source) for source in sources]
        if len(set(zip((source["path"] for source in sources), locations))) != len(sources):
            raise HearthError("The source occurrences changed. Reject the outdated proposal.")
        if kind == "promote":
            text = fact(sources[0]["text"])
            promotions[fact_key(text)] = text
            continue
        target = sources[-1]
        edits[target["path"]][locations[-1]] = kind

    result = {}
    for path, changes in edits.items():
        # The line numbers include front matter. Preserve every byte outside selected lines.
        lines = raw[path].splitlines(keepends=True)
        for number, kind in sorted(changes.items(), reverse=True):
            old = lines[number - 1]
            if kind == "merge":
                del lines[number - 1]
            else:
                content = old.rstrip("\r\n")
                lines[number - 1] = content.rstrip() + STALE + old[len(content):]
        result[path] = "".join(lines)

    if promotions:
        path = memory.PROFILE_NOTE
        current = storage.read(path) if storage.memory_path(path).is_file() else ""
        data, body, _ = memory.parse(path, current)
        existing = {fact_key(row["text"]) for row in note_sources(path, current, rules)}
        added = [value for key, value in promotions.items() if key not in existing]
        if added:
            result[path] = memory.render(data, body.rstrip() + "\n\n" +
                                         "".join(f"- {value}\n" for value in added))

    return [{"path": path, "content": content} for path, content in sorted(result.items())]
