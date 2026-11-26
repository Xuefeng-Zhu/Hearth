"""Permanent chat forget across Hearth's managed memory and local recovery data."""

import json
import re

from . import memory
from .proactive_context import retire
from .storage import atomic_write

REDACTED = "[forgotten]"


def scrub_value(value, rules):
    if isinstance(value, str):
        return REDACTED if memory.matches_rule(value, rules) else value
    if isinstance(value, list):
        return [scrub_value(item, rules) for item in value]
    if isinstance(value, dict):
        return {key: scrub_value(item, rules) for key, item in value.items()}
    return value


def plain_values(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(plain_values(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(plain_values(item) for item in value)
    return ""


def prune_note(path, text, rules):
    data, body, header = memory.parse(path, text)
    if path not in memory.PINNED and memory.matches_rule(data["id"], rules):
        return None
    context = data["id"]
    title = memory.HEADING.search(body)
    if title:
        context += " " + title[1]
    if not memory.matches_rule(context + " " + text, rules):
        return text
    blocks = re.split(r"(\n[ \t]*\n)", body)
    section = context
    for i in range(0, len(blocks), 2):
        block = blocks[i]
        if heading := memory.HEADING.search(block):
            section = context + " " + heading[1]
        if not memory.matches_rule(section + " " + block, rules):
            continue
        lines = block.splitlines(keepends=True)
        matching = [line for line in lines if memory.matches_rule(section + " " + line, rules)]
        blocks[i] = "".join(line for line in lines if line not in matching) if matching else ""
    updated = "".join(blocks)
    for key in ("relation", "related", "profile"):
        if key in data:
            value = data[key]
            if key == "related":
                data[key] = [item for item in value if not memory.matches_rule(item, rules)]
            else:
                data[key] = scrub_value(value, rules)
    if updated == body and memory.matches_rule(context + " " + body, rules):
        updated = ""
    if path not in memory.PINNED and not updated.strip() and not header:
        return None
    return memory.render(data, updated) if header else updated


def scrub_notes(notes, rules):
    return {path: prune_note(path, text, rules) if isinstance(text, str) else text for path, text in notes.items()}


def scrub_messages(rows, rules, message_id=None):
    clean = []
    removed = set()
    for row in rows:
        if (message_id and row.get("id") == message_id) or memory.matches_rule(plain_values(row), rules):
            removed.add(row.get("id"))
            continue
        clean.append(row)
    return clean, removed


def scrub_state(state, rules, message_id=None):
    if "messages" in state:
        state["messages"], _ = scrub_messages(state["messages"], rules, message_id)
    activity = state.get("activity", [])
    state["activity"] = [row for row in activity if not (
        row.get("message_id") == message_id and message_id or memory.matches_rule(plain_values(row), rules))]
    for row in state.get("proactivity", {}).get("cards", {}).values():
        retire(row)
    actions = state.get("actions", {})
    changes = state.get("memory_changes", {})
    expired = set()
    for identity, change in changes.items():
        if any(scrub_notes(change[key]["notes"], rules) != change[key]["notes"] for key in ("before", "after")):
            expired.add(identity)
    for identity, row in list(actions.items()):
        if identity in expired or (row.get("kind") in {"remember", "memory"} or
                                    str(row.get("tool", "")).startswith("memory_")) and (
                memory.matches_rule(plain_values(row), rules)):
            changes.pop(identity, None)
            actions[identity] = {key: val for key, val in row.items()
                                 if key in {"id", "kind", "at", "thread_id", "status"}}
            actions[identity].update(title="Memory history removed by a forget request", status="complete")
    origins = state.get("memory_origins", {})
    for path in list(origins):
        if memory.matches_rule(path, rules):
            origins.pop(path)


def write_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False))


def scrub_workspace(live, rules, message_id=None):
    root = live / "memory"
    removed = 0
    for file in root.glob("**/*.md"):
        if file.is_symlink() or not file.is_file():
            continue
        path = file.relative_to(root).as_posix()
        before = file.read_text(encoding="utf-8")
        after = prune_note(path, before, rules)
        if after == before:
            continue
        removed += 1
        if after is None:
            file.unlink()
        else:
            atomic_write(file, after)
    for file in (live / "threads").glob("*.jsonl"):
        rows = [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()]
        clean, ids = scrub_messages(rows, rules, message_id)
        if ids:
            atomic_write(file, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in clean))
    thread_index = live / "threads" / "index.json"
    if thread_index.is_file():
        data = json.loads(thread_index.read_text(encoding="utf-8"))
        cleaned = scrub_value(data, rules)
        if cleaned != data:
            write_json(thread_index, cleaned)
    state_path = live / "state.json"
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        scrub_state(state, rules, message_id)
        write_json(state_path, state)
    for file in (live / "index").glob("*.json"):
        if re.fullmatch(r"[a-f0-9]{24}\.json", file.name):
            file.unlink()
        elif file.name == "box-artifacts.json":
            data = json.loads(file.read_text(encoding="utf-8"))
            rows = data.get("rows", {})
            safe = {key: row for key, row in rows.items() if not memory.matches_rule(plain_values(row), rules)}
            if safe != rows:
                write_json(file, {**data, "rows": safe})
    return removed


def apply(storage, rules, message_id=None):
    removed = scrub_workspace(storage.live, rules, message_id)
    for snapshot in (storage.root / "checkpoints").glob("*/live"):
        scrub_workspace(snapshot, rules, message_id)
        (snapshot / "memory" / ".index.json").unlink(missing_ok=True)
    for backup in (storage.root / "memory-backups").glob("*.json"):
        notes = json.loads(backup.read_text(encoding="utf-8"))
        write_json(backup, scrub_notes(notes, rules))
    memory.catalog(storage)
    return removed


def purge(app, groups, message_id):
    storage = app.storage
    rule = memory.forget_rule(groups)
    with app.memory_index.lock, storage.lock():
        # Persist the rule first, so reads and subsequent writes are protected even if cleanup is interrupted.
        rules = memory.standing_rules(storage) + [rule]
        journal = storage.root / "memory-forget-pending.json"
        write_json(journal, {"rule": rule, "message_id": message_id})
        write_json(storage.root / "memory-forget.json", rules)
        removed = apply(storage, [rule], message_id)
        journal.unlink()
        action = app.agent.add_action("memory", "Memory permanently forgotten", status="complete",
                                      permanent=True, notes_changed=removed)
        with app.memory_index.query_cache_lock:
            app.memory_index.query_cache.clear()
    app.memory_sync.request()
    return {"action": action, "message": "Hearth recorded a standing forget rule and removed matching memory."}


def recover(storage):
    journal = storage.root / "memory-forget-pending.json"
    if journal.is_file():
        pending = json.loads(journal.read_text(encoding="utf-8"))
        rule = pending["rule"]
        rules = memory.standing_rules(storage)
        if rule not in rules:
            write_json(storage.root / "memory-forget.json", rules + [rule])
        apply(storage, [rule], pending["message_id"])
        journal.unlink()
