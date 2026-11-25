"""Local artifact copies, Box synchronization, and item-level Timeline undo."""

import csv
import hashlib
import io
import json
import re
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import box, timeline
from .connectors import ConnectorError
from .gateway_tools import redact_text, scrub
from .storage import HearthError, iso, new_id
from .threads import MAIN_ORIGIN, compact


def filename(title, fmt, suffix=""):
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    safe = re.sub(r"[^a-zA-Z0-9 ._-]+", "-", ascii_title)
    safe = re.sub(r" +", " ", safe).strip(" ._-")[:100].rstrip(" .") or "Artifact"
    return safe + suffix + (f".{fmt}" if fmt else "")


def clean_content(content, fmt):
    if not isinstance(content, str) or len(content) > box.MAX_BYTES or "\0" in content:
        raise HearthError("Artifact text must be at most 128 KiB and contain no null characters.")
    try:
        if fmt == "json":
            content = json.dumps(scrub(json.loads(content)), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        else:
            content = redact_text(content)
        size = len(content.encode("utf-8"))
    except (ValueError, RecursionError):
        raise HearthError("Enter valid UTF-8 text in the selected format.") from None
    if size > box.MAX_BYTES:
        raise HearthError("Artifact text must be at most 128 KiB.")
    return content, size


def format_text(title, text, fmt):
    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Text"])
        writer.writerows([line] for line in text.splitlines())
        return buffer.getvalue()
    if fmt == "json":
        return json.dumps({"title": title, "content": text}, ensure_ascii=False)
    return text


def when(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def metadata(item):
    version = item.get("file_version")
    return {"box_id": item["id"], "version_id": version.get("id") if isinstance(version, dict) else None,
            "version_number": item.get("version_number"), "etag": item.get("etag"),
            "box_updated_at": when(item.get("modified_at"))}


def box_versions(*rows):
    history = {}
    for row in rows:
        for entry in row.get("box_history", []):
            history[entry["id"]] = entry
        if box.box_id(identity := row.get("version_id")):
            previous = history.get(identity, {})
            history[identity] = {"id": identity, "number": row.get("version_number") or previous.get("number"),
                                 "at": row.get("box_updated_at") or previous.get("at")}
    return list(history.values())


def digest(content):
    return hashlib.sha1(content.encode("utf-8")).hexdigest()


def public(row, *, content=False):
    hidden = {"content", "box_connection", "box_history", "etag", "deleted", "folder_id", "folder_connection",
              "source_tag"}
    result = {key: value for key, value in row.items() if key not in hidden}
    if row.get("box_id"):
        result["box_url"] = f"https://app.box.com/file/{row['box_id']}"
    if row["sync"] == "saving":
        result.update(sync="error", sync_message="A Box save was interrupted. Retry to check Box.")
    if content and "content" in row:
        result["content"] = row["content"]
    return result


def message_artifacts(state, thread_id):
    by_message = {}
    for row in state.get("artifacts", {}).values():
        if row.get("deleted") or row.get("thread_id") != thread_id or not row.get("message_id"):
            continue
        by_message.setdefault(row["message_id"], []).append(public(row))
    return by_message


class Artifacts:
    def __init__(self, storage, threads, connections, operation):
        self.on_memory_change = lambda: None
        self.storage = storage
        self.threads = threads
        self.connections = connections
        self.operation = operation
        self.lock = threading.RLock()
        self.remote = {}
        self.scope = None

    def config(self):
        return self.connections.config.get("artifacts", box.DEFAULTS)

    def connection(self):
        return self.connections.selected.get("box")

    def client(self):
        identity = self.connection()
        return box.Box(self.connections.gateway, self.connections.gateway_entry("box", identity)) if identity else None

    def info(self):
        return {"settings": self.config(), "connected": bool(self.connection())}

    def bootstrap(self, client):
        name = self.config()["folder_name"]
        cache = self.connections.config.get("box_folders", {})
        if cache.get("name") == name and cache.get("connection") == self.connection():
            return cache
        root = client.folders("0", [name])[name]
        subfolders = client.folders(root, box.FOLDERS.values())
        cache = {"name": name, "connection": self.connection(), "root": root,
                 "kinds": {kind: subfolders[label] for kind, label in box.FOLDERS.items()}}
        self.connections.save_box_folders(cache)
        return cache

    def walk(self, client):
        name = self.config()["folder_name"]
        cache = self.connections.config.get("box_folders", {})
        root = cache.get("root") if cache.get("name") == name and cache.get("connection") == self.connection() else None
        if root:
            try:
                return self.walk_tree(client, root)
            except ConnectorError as error:
                if error.status != 404:
                    raise
        root = next((item["id"] for item in client.items("0") if item.get("type") == "folder"
                     and str(item.get("name")).casefold() == name.casefold() and box.box_id(item.get("id"))), None)
        if root is None:
            return {}
        return self.walk_tree(client, root)

    def walk_tree(self, client, root):
        names = {label.casefold(): kind for kind, label in box.FOLDERS.items()}
        pending = {root: "note"}
        seen, rows = {root}, {}
        with ThreadPoolExecutor(max_workers=5) as workers:
            while pending:
                batch = {folder: workers.submit(list, client.items(folder)) for folder in pending}
                next_level = {}
                for folder, result in batch.items():
                    kind = pending[folder]
                    for item in result.result():
                        identity, label = item.get("id"), item.get("name")
                        if not box.box_id(identity) or not isinstance(label, str):
                            continue
                        if item.get("type") == "folder" and identity not in seen:
                            if len(seen) >= 200:
                                raise HearthError("This Box folder tree exceeds Hearth’s 200-folder browsing limit.")
                            seen.add(identity)
                            next_level[identity] = names.get(label.casefold(), kind) if folder == root else kind
                        elif item.get("type") == "file":
                            row = self.box_row(item, kind)
                            rows[row["id"]] = row
                pending = next_level
        return rows

    def box_row(self, item, kind):
        label = redact_text(item["name"])
        stem, sep, ext = label.rpartition(".")
        fmt = re.sub(r"[^a-z0-9]", "", ext.lower())[:12] if sep else ""
        title = stem if sep and stem else label
        row = {**metadata(item), "id": f"box-{item['id']}", "title": title[:160], "filename": filename(title, fmt),
               "box_connection": self.connection(), "kind": kind, "format": fmt, "source": "Box",
               "sync": "synced", "size": item.get("size"), "created_at": when(item.get("created_at")),
               "updated_at": when(item.get("modified_at"))}
        return {**row, "revision": self.box_revision(row)}

    @staticmethod
    def box_revision(row):
        return f"box:{row.get('etag') or row.get('version_id') or row.get('box_updated_at')}"

    def list(self):
        with self.lock:
            scope = (self.connection(), self.config()["folder_name"])
            if self.scope != scope:
                self.scope, self.remote = scope, {}
            error = None
            if client := self.client():
                try:
                    self.remote = self.walk(client)
                except ConnectorError as exc:
                    error = box.error_message(exc, "listing the folder")
                except HearthError as exc:
                    error = str(exc)
            with self.storage.lock():
                local = self.storage.load().get("artifacts", {})
            represented = {row["box_id"] for row in local.values()
                           if row.get("box_id") and row.get("box_connection") == self.connection()}
            rows = [row for row in self.remote.values() if row["box_id"] not in represented]
            for row in local.values():
                if row.get("deleted"):
                    continue
                if row.get("box_id") and row.get("box_connection") == self.connection() and row["sync"] == "synced":
                    remote = self.remote.get(f"box-{row['box_id']}")
                    if remote:
                        row = {**row, "updated_at": remote["updated_at"], "size": remote["size"]}
                rows.append(row)
            return {**self.info(), "artifacts": [public(row) for row in rows], "box_error": error}

    def memory_rows(self, previous):
        if self.list()["box_error"]:
            return None
        with self.lock:
            client = self.client()
            if client is None:
                return None
            with self.storage.lock():
                local = self.storage.load().get("artifacts", {})
            represented = {row["box_id"]: row for row in local.values()
                           if row.get("box_id") and row.get("box_connection") == self.connection()}
            rows = {}
            for row in self.remote.values():
                linked = represented.get(row["box_id"])
                if (linked and (linked.get("deleted") or linked.get("sync") != "synced")
                        or row["format"] not in box.FORMATS
                        or (type(row.get("size")) is int and row["size"] > box.MAX_BYTES)):
                    continue
                key = linked["id"] if linked else row["id"]
                old = previous.get(key, {})
                if old.get("revision") == row["revision"]:
                    rows[key] = old
                    continue
                if linked and linked.get("version_id") == row.get("version_id") and "content" in linked:
                    continue
                try:
                    content = redact_text(client.content(row["box_id"]))
                except (ConnectorError, HearthError):
                    if old:
                        rows[key] = old
                else:
                    rows[key] = {**row, "id": key, "content": content}
            return rows

    def find(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r"(?:[a-f0-9]{32}|box-[0-9]{1,30})", identity):
            raise HearthError("Invalid artifact.")
        with self.storage.lock():
            local = self.storage.load().get("artifacts", {})
            row = local.get(identity)
            if row is None and identity.startswith("box-") and any(
                    item.get("box_id") == identity[4:] and item.get("box_connection") == self.connection()
                    for item in local.values()):
                raise HearthError("This artifact is no longer available.")
        if row is None and identity.startswith("box-"):
            if identity not in self.remote or self.scope != (self.connection(), self.config()["folder_name"]):
                self.list()
            row = self.remote.get(identity)
        if row is None or row.get("deleted"):
            raise HearthError("This artifact is no longer available.")
        return row

    def for_row(self, row):
        return self.client() if row.get("box_connection") == self.connection() else None

    def detail(self, identity, *, versions=True):
        with self.lock:
            saved = row = self.find(identity)
            history, warnings = [], []
            history_source = None
            remote = {}
            client = self.for_row(row)
            if row.get("box_id") and client:
                try:
                    item = client.file(row["box_id"])
                    remote = metadata(item)
                    if row["sync"] == "synced":
                        stale = row.get("version_id") != remote["version_id"]
                        row = {**row, **remote, "size": item.get("size", row["size"]),
                               "updated_at": remote["box_updated_at"] or row["updated_at"]}
                        if stale or "content" not in row:
                            row.pop("content", None)
                            current_size = row.get("size")
                            if row["format"] in box.FORMATS and (type(current_size) is not int
                                                                 or current_size <= box.MAX_BYTES):
                                row["content"] = client.content(row["box_id"])
                except ConnectorError as error:
                    warnings.append(box.error_message(error, "loading the Box file"))
                except HearthError as error:
                    warnings.append(str(error))
                if versions:
                    current = remote if box.box_id(remote.get("version_id")) else saved
                    if box.box_id(current.get("version_id")):
                        history.append({"id": current["version_id"], "number": current["version_number"],
                                        "at": current["box_updated_at"], "current": True})
                    try:
                        older = [{"id": item["id"], "number": item.get("version_number"),
                                  "at": when(item.get("modified_at") or item.get("created_at")), "current": False}
                                 for item in client.versions(row["box_id"])
                                 if box.box_id(item.get("id")) and item["id"] != current.get("version_id")]
                        history.extend(older)
                        history_source = "box"
                    except ConnectorError as error:
                        if not box.unsupported(error):
                            warnings.append(box.error_message(error, "loading Box versions"))
            if row.get("box_id") and not client:
                if "content" not in row:
                    warnings.append("Connect the original Box account in Connections to preview this file.")
            if versions and row.get("box_id") and history_source is None:
                history_source = "hearth"
                with self.storage.lock():
                    actions = self.storage.load().get("artifact_undo", {}).values()
                snapshots = [action["before"] for action in actions
                             if action["id"] == identity and action.get("before")
                             and action["before"].get("box_id") == row["box_id"]]
                known = box_versions(*snapshots, saved, remote)
                current_id = remote.get("version_id") or saved.get("version_id")
                history = [{**entry, "current": entry["id"] == current_id} for entry in reversed(known)]
                history.sort(key=lambda entry: not entry["current"])
            if row.get("box_id") and row["sync"] == "synced":
                row = {**row, "revision": self.box_revision(row)}
            return {**public(row, content=True), "versions": history, "version_source": history_source,
                    "warnings": warnings,
                    "box_connected": bool(self.connection())}

    def write(self, row, operation=None, before=None):
        with self.storage.lock():
            state = self.storage.load()
            if operation:
                origin = {**row, "source": row.get("source_tag")}
                event = timeline.entry("artifact", f"Artifact {operation} · {row['title']}", origin,
                                       id=new_id(), at=iso(), provider="box" if row.get("box_id") else None,
                                       data={"artifact_id": row["id"], "detail": row.get("sync_message"),
                                             "file": row["filename"]})
                event.update(action_id=event["id"], undoable=True, error=row["sync"] == "error")
                state.setdefault("activity", []).append(event)
                state.setdefault("artifact_undo", {})[event["id"]] = {
                    "operation": operation, "id": row["id"], "revision": row["revision"], "before": before}
            state.setdefault("artifacts", {})[row["id"]] = row
            self.storage.save(state)
        self.on_memory_change()

    def synchronize(self, row, *, retry=False):
        client = self.for_row(row) if row.get("box_id") else self.client()
        if client is None:
            return {**row, "sync": "local", "sync_message": "Box is disconnected."}
        try:
            folder = row.get("folder_id") if row.get("folder_connection") == self.connection() else None
            if not row.get("box_id") and not folder:
                folder = self.bootstrap(client)["kinds"][row["kind"]]
                row = {**row, "folder_id": folder, "folder_connection": self.connection()}
                self.write(row)
            current = None
            if retry and row.get("box_id"):
                current = client.file(row["box_id"])
                if current.get("sha1") != digest(row["content"]):
                    current = None
            if current is None:
                try:
                    current = client.upload(row, folder)
                except ConnectorError as error:
                    if error.status == 404 and not row.get("box_id"):
                        self.connections.save_box_folders({})
                        folder = self.bootstrap(client)["kinds"][row["kind"]]
                        row = {**row, "folder_id": folder}
                        self.write(row)
                        current = client.upload(row, folder)
                    elif error.status == 409 and not row.get("box_id"):
                        current = next((item for item in client.items(folder) if item.get("type") == "file"
                                        and item.get("name") == row["filename"] and box.box_id(item.get("id"))
                                        and item.get("sha1") == digest(row["content"])), None)
                        if current is None:
                            raise
                    else:
                        raise
        except ConnectorError as error:
            if box.unsupported(error):
                return {**row, "sync": "local", "sync_message": box.UNAVAILABLE}
            return {**row, "sync": "error", "sync_message": box.error_message(error, "saving the file")}
        version = metadata(current)
        return {**row, **version, "box_history": box_versions(row, version), "box_connection": self.connection(),
                "sync": "synced", "sync_message": None}

    def create(self, *, title, kind="note", content, format=None, origin=None, message_id=None):
        with self.operation, self.lock:
            if not isinstance(kind, str) or kind not in box.FOLDERS or not isinstance(title, str) or not title.strip():
                raise HearthError("Choose an artifact title and kind.")
            fmt = self.config()["format"] if format is None else format
            if not isinstance(fmt, str) or fmt not in box.FORMATS:
                raise HearthError("Choose Markdown, plain text, CSV, or JSON.")
            content, size = clean_content(content, fmt)
            title = compact(redact_text(title[:300]), 110) or "Artifact"
            identity, now = new_id(), iso()
            row = {"id": identity, "title": title, "kind": kind, "filename": filename(title, fmt, f" - {identity[:8]}"),
                   "format": fmt, "content": content, "size": size, "source": "Hearth", "revision": new_id(),
                   "created_at": now, "updated_at": now, "sync": "local", **(origin or {})}
            if message_id:
                row["message_id"] = message_id
                row["from_message"] = True
            if self.config()["auto_save"] and self.connection():
                row["sync"] = "saving"
                self.write(row)
                row = self.synchronize(row)
            self.write(row, "created")
            return public(row)

    def save_message(self, thread_id, message_id):
        with self.operation:
            return self.save_message_locked(thread_id, message_id)

    def save_message_locked(self, thread_id, message_id):
        with self.storage.lock():
            thread = self.threads.describe(thread_id)
            message = next((item for line, item in enumerate(self.threads.messages(thread_id), 1)
                            if (item.get("id") or f"{thread_id}:{line}") == message_id
                            and item["role"] in ("assistant", "call")), None)
            if not message:
                raise HearthError("That reply is no longer available.")
            existing = [item for item in message_artifacts(self.storage.load(), thread_id).get(message_id, [])
                        if item.get("from_message")]
            if existing:
                return existing[0]
        text = message["content"]
        kind, title = "note", compact(text.lstrip("# "), 72) or "Chat reply"
        if message["role"] == "call":
            kind, title = "transcript", message["content"]
            text = "\n".join(f"{'You' if line['role'] == 'user' else 'Agent'}: {line['text']}"
                             for line in message.get("lines", []))
            if not text:
                raise HearthError("This call has no saved transcript.")
        fmt = self.config()["format"]
        return self.create(title=title, kind=kind, content=format_text(title, text, fmt), format=fmt, message_id=message_id,
                           origin={"thread_id": thread_id, "thread_title": thread["title"],
                                   **({"source_tag": message["source"]} if message.get("source") else {})})

    def bind(self, identities, message_id):
        if not identities:
            return
        with self.storage.lock():
            state = self.storage.load()
            for identity in identities:
                if row := state.get("artifacts", {}).get(identity):
                    row["message_id"] = message_id
            self.storage.save(state)

    def mutate(self, operation, body):
        with self.lock:
            identity = body.get("id")
            before = self.find(identity)
            if operation == "retry" and body.keys() == {"id"}:
                if before["sync"] == "synced" or "content" not in before:
                    return public(before)
                row = self.synchronize(before, retry=True)
                self.write(row)
                return public(row)
            if operation == "delete" and body.keys() == {"id", "revision"}:
                revision = body["revision"]
                if before.get("box_id") and before["sync"] == "synced":
                    if revision != self.box_revision(before):
                        before = self.checked_row(before, revision)
                elif revision != before["revision"]:
                    raise HearthError("This artifact changed. Reopen it before making another change.")
                deleted = {**before, "deleted": True, "revision": new_id(),
                           "sync_message": "Moved to Hearth Trash. The Box file remains in Box."
                           if before.get("box_id") else "Moved to Hearth Trash. Restore it from Timeline."}
                self.write(deleted, "deleted", before)
                return public(deleted)
            if operation == "update" and body.keys() == {"id", "revision", "content"}:
                row = self.checked_row(before, body["revision"])
                snapshot = {**row, "revision": before["revision"]}
                if row["format"] not in box.FORMATS:
                    raise HearthError("This format can be edited in Box.")
                content, size = clean_content(body["content"], row["format"])
                row = {**row, "content": content, "size": size, "revision": new_id(), "updated_at": iso(),
                       "sync": "local", "sync_message": None}
                if self.config()["auto_save"] and self.connection():
                    row["sync"] = "saving"
                    self.write(row)
                    row = self.synchronize(row)
                # The snapshot includes the Box version observed at edit time.
                self.write(row, "updated", snapshot)
                return public(row)
        raise HearthError("Invalid artifact request.")

    def checked_row(self, row, revision):
        if row.get("box_id") and row["sync"] == "synced":
            client = self.for_row(row)
            if client is None:
                raise HearthError("Connect the original Box account to change this file.")
            try:
                row = {**row, **metadata(client.file(row["box_id"]))}
            except ConnectorError as error:
                raise HearthError(box.error_message(error, "checking the file")) from None
            row["revision"] = self.box_revision(row)
        if row["revision"] != revision:
            raise HearthError("This artifact changed. Reopen it before making another change.")
        return row

    def undo(self, action_id):
        with self.lock:
            with self.storage.lock():
                state = self.storage.load()
                action = state.get("artifact_undo", {}).get(action_id)
                row = state.get("artifacts", {}).get(action["id"]) if action else None
            if not row or row["revision"] != action["revision"]:
                raise HearthError("This artifact changed after that action. Undo the most recent change first.")
            operation, before = action["operation"], action["before"]
            if operation == "created":
                restored = {**row, "deleted": True}
            elif operation == "deleted":
                restored = before
            else:
                restored = self.undo_update(row, before)
            with self.storage.lock():
                state = self.storage.load()
                state["artifacts"][row["id"]] = restored
                del state["artifact_undo"][action_id]
                event = next(event for event in state["activity"] if event["id"] == action_id)
                event.update(undone=True, undoable=False, undone_at=iso())
                self.storage.save(state)
            self.on_memory_change()
            return {"ok": True}

    def undo_update(self, row, before):
        if row["sync"] != "synced":
            return before
        client = self.for_row(row)
        if not client:
            raise HearthError("Connect the original Box account to restore this edit.")
        version_id = before.get("version_id")
        if before["sync"] == "synced" and not box.box_id(version_id):
            raise HearthError("The previous Box version could not be identified.")
        try:
            current = self.checked_row(row, self.box_revision(row))
            content = (client.content(row["box_id"], version_id) if before["sync"] == "synced"
                       else before["content"])
            item = client.upload({**current, "content": content})
        except ConnectorError as error:
            raise HearthError(box.error_message(error, "restoring the previous version")) from None
        version = metadata(item)
        return {**before, **version, "box_connection": row["box_connection"],
                "box_history": box_versions(before, row, version), "sync": "synced", "sync_message": None,
                "content": content, "size": len(content.encode("utf-8")), "updated_at": iso()}
