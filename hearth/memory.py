"""Structured Markdown notes, their generated catalog, and the v1 migration."""

import hashlib
import json
import re
from datetime import datetime, timezone

import yaml

from .storage import MAX_NOTE, HearthError, atomic_write, iso, new_id

PROFILE = {
    "name": "", "preferred_name": "", "pronouns": "", "phone": "", "addresses": [],
    "work": {"employer": "", "role": ""}, "pets": [], "interests": [], "communication": [],
}
ADDRESS = {"id", "label", "address", "notes"}
TYPES = ("user", "contact", "organization", "project", "place", "event", "interest", "misc")
TOPICS = ("food", "travel", "shopping-and-money", "home-and-health", "leisure")
APPROVAL_NOTE = "APPROVAL_PREFERENCES.md"
PROFILE_NOTE = "USER.md"
PROACTIVITY_NOTE = "PROACTIVITY_PREFERENCES.md"
PINNED = {PROFILE_NOTE, APPROVAL_NOTE}
ID = re.compile(r"[\w-]+(?:/[\w-]+)?")
FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", re.S)
HEADING = re.compile(r"(?m)^#{1,6} +(.+?) *#* *$")
PRIVATE_NUMBER = re.compile(
    r"\b\d{3}-\d{2}-\d{4}\b|\b(?:ssn|social security|passport|national id|driver'?s licen[cs]e|"
    r"card number|credit card|debit card|cvv|cvc)\s*(?:number|no\.?|#)?\s*[:=]\s*\S+", re.I,
)
CARD = re.compile(r"(?<![\d+])(?:\d[ -]?){12,18}\d(?!\d)")


class UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        mapping = super().construct_mapping(node, deep)
        if len(mapping) != len(node.value):
            raise ValueError("Duplicate YAML key.")
        return mapping


def clean_content(text):
    from .gateway_tools import redact_text

    def card_number(value):
        digits = "".join(c for c in value if c.isdecimal())
        products = [int(digit) * (1 + index % 2) for index, digit in enumerate(reversed(digits))]
        return sum(value - 9 if value > 9 else value for value in products) % 10 == 0

    if PRIVATE_NUMBER.search(text) or any(card_number(match[0]) for match in CARD.finditer(text)):
        raise HearthError("Memory cannot store identity documents or payment card details.")
    return redact_text(text)


def note_id(path):
    return {PROFILE_NOTE: "user", APPROVAL_NOTE: "approval-preferences",
            PROACTIVITY_NOTE: "proactivity-preferences"}.get(path, path.removesuffix(".md"))


def default_type(path):
    return {
        PROFILE_NOTE: "user", "people": "contact", "locations": "place",
        "projects": "project", "daily": "event",
    }.get(path.split("/")[0], "misc")


def valid_type(path, kind):
    expected = default_type(path)
    if path.startswith("people/"):
        return kind in ("contact", "organization")
    return kind == expected if expected != "misc" else kind in ("organization", "event", "interest", "misc")


def strings(values):
    return isinstance(values, list) and all(isinstance(item, str) for item in values)


def normalize_profile(value):
    if not isinstance(value, dict) or value.keys() != PROFILE.keys():
        raise HearthError("The profile must have all nine profile fields.")
    if (not all(isinstance(value[key], str) for key in ("name", "preferred_name", "pronouns", "phone"))
            or not all(strings(value[key]) for key in ("pets", "interests", "communication"))):
        raise HearthError("Use text for profile fields and lists of text for pets, interests and communication.")
    work, addresses = value["work"], value["addresses"]
    if not isinstance(work, dict) or work.keys() != PROFILE["work"].keys() or not all(
        isinstance(item, str) for item in work.values()
    ):
        raise HearthError("Enter an employer and role under work.")
    ids = set()
    if not isinstance(addresses, list):
        raise HearthError("Addresses must be a list.")
    for address in addresses:
        if (not isinstance(address, dict) or address.keys() != ADDRESS or not all(
                isinstance(item, str) for item in address.values()) or not ID.fullmatch(address["id"])
                or address["id"] in ids):
            raise HearthError("Every address needs a unique id, label, address and notes.")
        ids.add(address["id"])
    return {**value, "work": {key: work[key] for key in PROFILE["work"]},
            "addresses": [{key: item[key] for key in ("id", "label", "address", "notes")} for item in addresses]}


def parse(path, content, *, strict=False):
    """Return metadata, Markdown body, and the number of front matter lines."""
    fallback = {"id": note_id(path), "type": default_type(path), "relation": "", "related": []}
    if path == PROFILE_NOTE:
        fallback = {"profile": PROFILE, **fallback}
    match = FRONT.match(content)
    if match:
        try:
            data = yaml.load(match[1], Loader=UniqueLoader)
            if (not isinstance(data, dict) or data.keys() - fallback.keys()
                    or data.get("id") != note_id(path) or not valid_type(path, data.get("type"))
                    or not isinstance(data.get("relation", ""), str)
                    or not strings(data.get("related"))
                    or any(not ID.fullmatch(item) for item in data["related"])
                    or len(set(data["related"])) != len(data["related"])
                    or data["id"] in data["related"]):
                raise ValueError
            if path == PROFILE_NOTE:
                data["profile"] = normalize_profile(data.get("profile"))
            elif default_type(path) == "contact" and "relation" not in data:
                raise ValueError
            return {**fallback, **data}, content[match.end():], match[0].count("\n")
        except (yaml.YAMLError, ValueError, TypeError, HearthError, RecursionError):
            if strict:
                raise HearthError("Invalid memory front matter. Check the id, type, relation, related links and profile.") from None
    elif strict:
        raise HearthError("Start the note with YAML front matter.")
    return fallback, content, 0


def render(data, body):
    return "---\n" + yaml.safe_dump(data, sort_keys=False, allow_unicode=True) + "---\n" + body


def canonical(path, content, previous=None):
    # Legacy tools and older clients send plain Markdown. Preserve existing metadata for those writes.
    if FRONT.match(content) or content.startswith("---\n"):
        data, body, _ = parse(path, content, strict=True)
    else:
        data, _, _ = parse(path, previous or "")
        body = content
    result = clean_content(render(data, body))
    parse(path, result, strict=True)
    if len(result) > MAX_NOTE:
        raise HearthError("Supply Markdown content of at most 24,000 characters.")
    return result


def revision(content):
    return hashlib.sha256(content.encode()).hexdigest()


def catalog_row(path, content, modified):
    data, body, _ = parse(path, content)
    heading = HEADING.search(body)
    return {
        **{key: data[key] for key in ("id", "type", "relation", "related")},
        "path": path, "title": heading[1] if heading else display_name(path),
        "size": len(content.encode()), "updated": modified.isoformat(timespec="microseconds"),
    }


def catalog(storage):
    rows = [catalog_row(path, storage.read(path), datetime.fromtimestamp(
        storage.memory_path(path).stat().st_mtime, timezone.utc)) for path in storage.files()]
    generated = storage.memory / ".index.json"
    value = json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
    if not generated.is_file() or generated.read_text(encoding="utf-8") != value:
        atomic_write(generated, value)
    return rows


def display_name(path):
    if path.startswith("daily/"):
        return note_id(path).split("/")[-1]
    return note_id(path).split("/")[-1].replace("-", " ").title()


def resolve(storage, *, path=None, id=None):
    if path is not None and id is None:
        storage.memory_path(path)
        return path
    if path is None and isinstance(id, str) and ID.fullmatch(id):
        for candidate in storage.files():
            if note_id(candidate) == id:
                return candidate
    raise HearthError("Choose a memory note by id or path.")


def profile_record(storage):
    if PROFILE_NOTE not in storage.files():
        return {"profile": PROFILE, "notes": "", "revision": None}
    from .gateway_tools import redact_text
    text = storage.read(PROFILE_NOTE)
    data, notes, _ = parse(PROFILE_NOTE, redact_text(text))
    return {"profile": data["profile"], "notes": notes.strip(), "revision": revision(text)}


def approval_content(policy, previous=None):
    data, body, _ = parse(APPROVAL_NOTE, previous or "# Approval preferences\n")
    body = re.split(r"(?m)^<!-- hearth:approval-policy -->\s*$", body, maxsplit=1)[0].rstrip()
    lines = [f"- {category.title()}: {'Always ask' if value == 'ask' else 'Allow without asking'}"
             for category, value in policy.items()]
    return render(data, body + "\n\n<!-- hearth:approval-policy -->\n" + "\n".join(lines) + "\n")


def legacy_metadata(path, content):
    data, body, header = parse(path, content)
    if header:
        return data, body
    if path == PROFILE_NOTE:
        profile = {**PROFILE}
        for key in ("name", "preferred_name", "pronouns", "phone"):
            label = key.replace("_", r"[ _-]")
            if match := re.search(rf"(?im)^(?:[-*] +)?(?:\*\*)?{label}(?:\*\*)?:\s*(\S[^\n]*)$", body):
                profile[key] = match[1].strip()
        data["profile"] = profile
    if path.startswith("people/"):
        if match := re.search(r"(?im)^(?:[-*] +)?relation:\s*(\S[^\n]*)$", body):
            data["relation"] = match[1].strip()
    return data, body


def related_changes(storage, path, target=None):
    old = note_id(path)
    new = note_id(target) if target else None
    changes = {}
    for candidate in storage.files():
        if candidate == path:
            continue
        data, body, _ = parse(candidate, storage.read(candidate))
        related = data["related"]
        if old in related:
            data["related"] = list(dict.fromkeys(new if item == old else item for item in related
                                                 if item != old or new))
        if target:
            updated = re.sub(r"(\[\[|\]\()(" + re.escape(path) + "|" + re.escape(old) + r")(?=[\]#|)])",
                             lambda match: match[1] + (target if match[2] == path else new), body)
        else:
            updated = body
        if related != data["related"] or updated != body:
            changes[candidate] = render(data, updated)
    return changes


def initialize(storage, *, fresh):
    from . import approvals, memory_edits

    state = storage.load()
    if state.get("structured_memory"):
        catalog(storage)
        return
    backup = storage.root / "memory-backups" / "before-structured-memory.json"
    recovered = not fresh and backup.is_file()
    original = (json.loads(backup.read_text(encoding="utf-8")) if recovered else
                {path: storage.read(path) for path in storage.files()})
    changes = {}
    targets = {}
    for path in original:
        name = note_id(path).removeprefix("topics/")
        target = f"{name}.md" if path == f"topics/{name}.md" and name in TOPICS and f"{name}.md" not in original else path
        targets[path] = target
    remap = {note_id(path): note_id(target) for path, target in targets.items() if path != target}
    for path, content in original.items():
        target = targets[path]
        data, body = legacy_metadata(path, content)
        data["id"] = note_id(target)
        data["related"] = list(dict.fromkeys(remap.get(item, item) for item in data["related"]))
        body = re.sub(r"(\[\[|\]\()(" + "|".join(re.escape(item) for item in remap) + r")(?:\.md)?(?=[\]#|)])",
                      lambda match: match[1] + remap[match[2]] + (".md" if match[0].endswith(".md") else ""), body
                      ) if remap else body
        if target != path:
            changes[path] = None
        _, old_body, header = parse(path, content)
        if not header or target != path or old_body != body or any(item in remap.values() for item in data["related"]):
            changes[target] = render(data, body)
    if PROFILE_NOTE not in original:
        changes[PROFILE_NOTE] = render({"profile": PROFILE, "id": "user", "type": "user", "related": []}, "")
    for subject in TOPICS:
        path = f"{subject}.md"
        if path not in targets.values():
            changes[path] = render({"id": subject, "type": "interest", "related": []},
                                   f"\n# {display_name(path)}\n")
    changes[APPROVAL_NOTE] = approval_content(approvals.policy(state), changes.get(APPROVAL_NOTE)
                                              or original.get(APPROVAL_NOTE))
    changes = {path: text for path, text in changes.items() if text != original.get(path)}
    before = memory_edits.snapshot(storage, state, changes)
    before["notes"] = {path: original.get(path) for path in changes}
    if changes and not fresh and not recovered:
        atomic_write(backup, json.dumps(original, ensure_ascii=False))
    action = {"id": new_id(), "kind": "memory", "title": "Memory moved to the new layout",
              "status": "complete", "at": iso(), "paths": sorted(changes)}
    try:
        memory_edits.write_notes(storage, changes)
        if changes and not fresh:
            memory_edits.record(storage, state, action, before)
            state["actions"][action["id"]] = action
        state["structured_memory"] = True
        catalog(storage)
        storage.save(state)
    except OSError:
        memory_edits.write_notes(storage, before["notes"])
        catalog(storage)
        raise


def forget_requested(prompt):
    request = re.sub(r"^\s*(?:(?:please|(?:can|could|would) you|I (?:want|need) you to)\s+)*(?:permanently\s+)?",
                     "", prompt, flags=re.I).strip()
    if re.fullmatch(r"forget (?:about )?(?:it|that)[.!?]?", request, re.I):
        return False
    return bool(re.match(r"(?:forget(?!\s+to\b)\s+|(?:erase|remove|delete)\s+.+\bfrom (?:your )?memory\b|"
                         r"请?(?:忘记|忘掉|从记忆中删除))", request, re.I | re.S))


def words(text):
    spaced = re.sub(r"[\u3400-\u9fff]", r" \g<0> ", text)
    return re.findall(r"[^\W_]+", spaced.casefold())


def forget_rule(groups):
    if (not isinstance(groups, list) or not 1 <= len(groups) <= 12 or
            any(not strings(group) or not 1 <= len(group) <= 8 for group in groups)):
        raise HearthError("Provide the phrases that identify the information to forget.")
    salt = new_id()
    encoded = []
    for group in groups:
        phrases = [words(text) for text in group if 2 <= len(text) <= 120]
        if len(phrases) != len(group) or any(not phrase for phrase in phrases):
            raise HearthError("Use distinctive phrases to identify the information to forget.")
        encoded.append([[len(phrase), phrase_hash(salt, phrase)] for phrase in phrases])
    return {"id": salt, "at": iso(), "groups": encoded}


def phrase_hash(salt, phrase):
    return hashlib.sha256((salt + " ".join(phrase)).encode()).hexdigest()


def matches_rule(text, rules):
    if not rules:
        return False
    tokens = words(text)
    for rule in rules:
        hashes = {}
        for group in rule["groups"]:
            for length, _ in group:
                if length not in hashes:
                    hashes[length] = {phrase_hash(rule["id"], tokens[i:i + length])
                                      for i in range(max(0, len(tokens) - length + 1))}
            if all(value in hashes[length] for length, value in group):
                return True
    return False


def standing_rules(storage):
    path = storage.root / "memory-forget.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def check_standing_rules(storage, content):
    if matches_rule(content, standing_rules(storage)):
        raise HearthError("A standing forget rule prevents Hearth from saving that information again.")
