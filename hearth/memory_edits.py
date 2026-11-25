"""Record reversible edits to the memory corpus for Timeline."""

from . import recall
from .gateway_tools import redact_text
from .storage import HearthError, iso
from .threads import MAIN


def read_notes(storage, paths):
    return {path: storage.read(path) if storage.memory_path(path).is_file() else None for path in paths}


def snapshot(storage, state, paths=(), message_id=None):
    notes = read_notes(storage, paths)
    origins = state.get("memory_origins", {})
    return {"notes": notes, "origins": {path: origins.get(path) for path in notes},
            "forgotten": bool(message_id and message_id in state.get("forgotten_chat", []))}


def record(storage, state, action, before, message_id=None):
    paths = before["notes"]
    if not message_id:
        origins = state.setdefault("memory_origins", {})
        for path, content in read_notes(storage, paths).items():
            if content is None:
                origins.pop(path, None)
            elif content != paths[path]:
                old = before["origins"][path] or {}
                previous = {item["id"] for item in recall.note_chunks(path, redact_text(paths[path] or ""))}
                current_origin = {"thread_id": action.get("thread_id") or MAIN, "created_at": action["at"]}
                prior_origin = {"thread_id": old.get("thread_id") or MAIN,
                                "created_at": old.get("created_at") or action["at"]}
                origins[path] = {"excerpts": {
                    item["id"]: old.get("excerpts", {}).get(item["id"], prior_origin)
                    if item["id"] in previous else current_origin
                    for item in recall.note_chunks(path, redact_text(content))
                }}
    after = snapshot(storage, state, paths, message_id)
    if before != after:
        action["memory_change"] = True
        state.setdefault("memory_changes", {})[action["id"]] = {
            "before": before, "after": after, "message_id": message_id,
        }


def write_notes(storage, notes):
    for path, content in notes.items():
        if content is None:
            storage.memory_path(path).unlink(missing_ok=True)
        else:
            storage.write(path, content)


def restore(storage, action_id, *, redo=False):
    with storage.lock():
        state = storage.load()
        change = state.get("memory_changes", {}).get(action_id)
        action = state["actions"].get(action_id)
        if not change or not action or bool(action.get("undone")) != redo:
            raise HearthError("This memory change is no longer available.")
        previous, next_state = (change["before"], change["after"]) if redo else (change["after"], change["before"])
        message_id = change["message_id"]
        if snapshot(storage, state, previous["notes"], message_id) != previous:
            raise HearthError("This memory changed again. Undo the newer change first.")
        try:
            write_notes(storage, next_state["notes"])
            origins = state.setdefault("memory_origins", {})
            for path, value in next_state["origins"].items():
                if value is None:
                    origins.pop(path, None)
                else:
                    origins[path] = value
            if message_id:
                forgotten = state.setdefault("forgotten_chat", [])
                if next_state["forgotten"]:
                    forgotten.append(message_id)
                else:
                    forgotten.remove(message_id)
            action.update(undone=not redo, undone_at=None if redo else iso(), updated_at=iso())
            storage.save(state)
        except OSError:
            write_notes(storage, previous["notes"])
            raise
        return action
