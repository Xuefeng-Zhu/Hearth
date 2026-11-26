"""Local artifact copies, Box synchronization, and item-level Timeline undo."""

import hashlib
import re
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import box, office, timeline
from .connectors import ConnectorError
from .gateway_tools import redact_text
from .storage import HearthError, atomic_write, iso, new_id
from .threads import compact


def filename(title, fmt, suffix=""):
    safe = "".join(char if char.isalnum() or char in " ._-" else "-"
                   for char in unicodedata.normalize("NFC", title))
    safe = re.sub(r" +", " ", safe).strip(" ._-")
    safe = safe.encode("utf-8")[:175].decode("utf-8", errors="ignore").rstrip(" .") or "Artifact"
    return safe + suffix + (f".{fmt}" if fmt else "")


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
    return hashlib.sha1(content).hexdigest()


def public(row, *, content=False):
    hidden = {"content", "box_connection", "box_history", "etag", "deleted", "folder_id", "folder_connection",
              "source_tag", "from_message", "file_revision", "file_history", "structured", "reply_links"}
    result = {key: value for key, value in row.items() if key not in hidden}
    if row.get("box_id"):
        result["box_url"] = f"https://app.box.com/file/{row['box_id']}"
    if row.get("file_history"):
        result["version_number"] = row["file_history"][-1]["number"]
    if row["format"] in box.TEXT_TYPES:
        result["legacy"] = True
    if row["sync"] == "saving":
        result.update(sync="error", sync_message="A Box save was interrupted. Retry to check Box.")
    if content and "content" in row:
        result["content"] = row["content"]
    return result


def page_artifact(row):
    saved = row.get("box_files", {}).get(str(row["version"]))
    result = {key: row[key] for key in ("id", "title", "updated_at", "thread_id", "thread_title")}
    result.update(kind="page", format="html", filename=filename(row["title"], "html"),
                  version_number=row["version"], sync="synced" if saved else "local")
    if saved:
        result["box_url"] = saved["url"]
    return result


def page_artifacts(state):
    # Project both existing and new pages from the version store to keep a single source of truth.
    return (page_artifact(row) for row in state.get("pages", {}).values() if row["version"] is not None)


def message_artifacts(state, thread_id):
    by_message = {}
    for row in state.get("artifacts", {}).values():
        if row.get("deleted") or row.get("format") not in office.MIME_TYPES:
            continue
        for link in row.get("reply_links", []):
            if link["thread_id"] == thread_id:
                by_message.setdefault(link["message_id"], []).append(public(row))
    return by_message


class Artifacts:
    def __init__(self, storage, connections, operation):
        self.on_memory_change = lambda: None
        self.storage = storage
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
                state = self.storage.load()
            local = state.get("artifacts", {})
            represented = {row["box_id"] for row in local.values()
                           if row.get("box_id") and row.get("box_connection") == self.connection()}
            represented.update(saved["url"].removeprefix("https://app.box.com/file/")
                               for page in state.get("pages", {}).values()
                               for saved in page.get("box_files", {}).values())
            rows = [row for row in self.remote.values() if row["box_id"] not in represented]
            for row in local.values():
                if row.get("deleted"):
                    continue
                if row.get("box_id") and row.get("box_connection") == self.connection() and row["sync"] == "synced":
                    remote = self.remote.get(f"box-{row['box_id']}")
                    if remote and not row.get("file_revision"):
                        row = {**row, "updated_at": remote["updated_at"], "size": remote["size"]}
                rows.append(row)
            return {**self.info(), "artifacts": [*(public(row) for row in rows), *page_artifacts(state)],
                    "box_error": error}

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
                        or row["format"] not in box.TEXT_TYPES
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
        from .pages import page_detail

        with self.storage.lock():
            state = self.storage.load()
            if isinstance(identity, str) and (row := state.get("pages", {}).get(identity)) and row["version"] is not None:
                return {**page_artifact(row), **page_detail(state, row)}
        with self.lock:
            saved = row = self.find(identity)
            if row["format"] in office.MIME_TYPES:
                return self.office_detail(row)
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
                            if row["format"] in box.TEXT_TYPES and (type(current_size) is not int
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
                    warnings.append("Connect the original Box account in Settings → Connections to preview this file.")
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

    def file_path(self, row):
        return self.storage.live / "artifacts" / row["id"] / f"{row['file_revision']}.{row['format']}"

    def local_bytes(self, row):
        if row.get("file_revision"):
            return self.file_path(row).read_bytes()
        if "content" in row:
            return row["content"].encode("utf-8")
        raise HearthError("This artifact has no saved local copy.")

    def download(self, identity, *, inline=False):
        from .pages import page_bytes

        with self.storage.lock():
            state = self.storage.load()
            if isinstance(identity, str) and (row := state.get("pages", {}).get(identity)) and row["version"] is not None:
                if inline:
                    raise HearthError("Inline preview requires a local PDF.")
                return page_artifact(row), page_bytes(self.storage, row, row["version"])
        with self.lock:
            row = self.find(identity)
            if inline and (row["format"] != "pdf" or not row.get("file_revision")):
                raise HearthError("Inline preview requires a local PDF.")
            if row.get("file_revision") or "content" in row:
                return row, self.local_bytes(row)
            if client := self.for_row(row):
                try:
                    return row, client.download(row["box_id"])
                except ConnectorError as error:
                    raise HearthError(box.error_message(error, "downloading the file")) from None
            raise HearthError("Connect the original Box account to download this file.")

    def office_detail(self, row):
        history = row.get("file_history", [])
        result = {**public(row), "versions": [{**entry, "current": entry is history[-1]}
                                               for entry in reversed(history)],
                  "version_source": "hearth", "box_connected": bool(self.connection()), "warnings": []}
        if not history and row.get("version_id"):
            result["versions"] = [{"id": row["version_id"], "number": row["version_number"],
                                   "at": row["box_updated_at"], "current": True}]
            result["version_source"] = "box"
        if row.get("file_revision") and not self.file_path(row).is_file():
            result["warnings"].append("Hearth could not find the saved local copy.")
            return result
        if row.get("file_revision") or self.for_row(row):
            result["download_available"] = True
        if row["format"] == "pdf":
            result["inline_pdf"] = bool(row.get("file_revision"))
        elif result.get("download_available"):
            try:
                _, raw = self.download(row["id"])
                result["preview"] = office.preview(row["format"], raw)
            except HearthError as error:
                result["warnings"].append(str(error))
            except Exception:
                result["warnings"].append("Hearth could not read the file preview. Use Download to open the file.")
        return result

    def has_reply_file(self, thread_id, message_id):
        with self.storage.lock():
            return message_id in message_artifacts(self.storage.load(), thread_id)

    def recent(self, thread_id):
        with self.storage.lock():
            rows = [row for row in self.storage.load().get("artifacts", {}).values()
                    if not row.get("deleted") and row.get("structured")]
        rows.sort(key=lambda row: row["updated_at"], reverse=True)
        rows.sort(key=lambda row: row.get("thread_id") != thread_id
                  and not any(link["thread_id"] == thread_id for link in row.get("reply_links", [])))
        return [{key: row[key] for key in ("id", "title", "format", "thread_title") if key in row}
                for row in rows[:20]]

    def read_for_edit(self, identity):
        with self.lock:
            row = self.find(identity)
            if not row.get("structured"):
                raise HearthError("This file was imported. Hearth can edit files it generated.")
            return {"id": identity, "format": row["format"], "revision": row["revision"], **row["structured"]}

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
            content = self.local_bytes(row)
            current = None
            if retry and row.get("box_id"):
                current = client.file(row["box_id"])
                if current.get("sha1") != digest(content):
                    current = None
            if current is None:
                try:
                    current = client.upload(row, content, folder)
                except ConnectorError as error:
                    if error.status == 404 and not row.get("box_id"):
                        self.connections.save_box_folders({})
                        folder = self.bootstrap(client)["kinds"][row["kind"]]
                        row = {**row, "folder_id": folder}
                        self.write(row)
                        current = client.upload(row, content, folder)
                    elif error.status == 409 and not row.get("box_id"):
                        if retry:
                            current = next((item for item in client.items(folder) if item.get("type") == "file"
                                            and item.get("name") == row["filename"] and box.box_id(item.get("id"))
                                            and item.get("sha1") == digest(content)), None)
                        if current is None:
                            name = filename(row["title"], row["format"], f" - {row['id'][:8]}")
                            if name == row["filename"]:
                                raise
                            row = {**row, "filename": name}
                            self.write(row)
                            current = client.upload(row, content, folder)
                    else:
                        raise
        except ConnectorError as error:
            if box.unsupported(error):
                return {**row, "sync": "local", "sync_message": box.UNAVAILABLE}
            return {**row, "sync": "error", "sync_message": box.error_message(error, "saving the file")}
        version = metadata(current)
        if row.get("file_history"):
            last = {**row["file_history"][-1], "box_version_id": version["version_id"],
                    "box_version_number": version["version_number"]}
            row = {**row, "file_history": [*row["file_history"][:-1], last]}
        return {**row, **version, "box_history": box_versions(row, version), "box_connection": self.connection(),
                "sync": "synced", "sync_message": None}

    def create(self, fmt, value, *, kind="note", origin=None):
        if not isinstance(kind, str) or kind not in box.FOLDERS:
            raise HearthError("Choose a valid artifact kind.")
        with self.operation, self.lock:
            value = office.prepare(fmt, value)
            title = compact(value["title"], 160) or "Artifact"
            if title.casefold().endswith("." + fmt):
                title = title[:-(len(fmt) + 1)].rstrip() or "Artifact"
            identity, now = new_id(), iso()
            row = {"id": identity, "title": title, "kind": kind, "filename": filename(title, fmt),
                   "format": fmt, "source": "Hearth", "created_at": now, **(origin or {})}
            return self.save_file(row, value)

    def stage_file(self, row, value, *, raw=None):
        fmt = row["format"]
        if raw is None:
            raw = office.generate(fmt, value)
        if len(raw) > box.MAX_UPLOAD_BYTES:
            raise HearthError("Files must be at most 50 MiB.")
        revision, now = new_id(), iso()
        history = row.get("file_history", [])
        entry = {"id": revision, "number": len(history) + 1, "at": now}
        row = {**row, "structured": value, "file_revision": revision, "revision": revision, "updated_at": now,
               "size": len(raw), "sync": "local", "sync_message": None, "file_history": [*history, entry]}
        atomic_write(self.file_path(row), raw)
        return row

    def save_file(self, row, value, *, before=None):
        row = self.stage_file(row, value)
        if self.config()["auto_save"] and self.connection():
            row["sync"] = "saving"
            self.write(row)
            row = self.synchronize(row)
        self.write(row, "updated" if before else "created", before)
        return public(row)

    def update(self, fmt, identity, revision, value):
        with self.operation, self.lock:
            row = self.find(identity)
            if row["format"] != fmt or not row.get("structured"):
                raise HearthError("Choose a file of this type generated by Hearth.")
            self.check_file_revision(row, revision)
            return self.save_file(row, office.prepare(fmt, value), before=row)

    def check_file_revision(self, row, revision):
        if row["revision"] != revision:
            raise HearthError("This artifact changed. Read its latest version before editing.")
        if row.get("box_id"):
            client = self.for_row(row)
            if not client:
                raise HearthError("Connect the original Box account to change this file.")
            try:
                current = metadata(client.file(row["box_id"]))
            except ConnectorError as error:
                raise HearthError(box.error_message(error, "checking the file")) from None
            if current["etag"] != row.get("etag") or current["version_id"] != row.get("version_id"):
                raise HearthError("This file changed in Box. Open the latest Box copy before making edits.")

    def bind(self, identities, thread_id, message_id):
        if not identities:
            return
        with self.storage.lock():
            state = self.storage.load()
            for identity in dict.fromkeys(identities):
                if row := state.get("artifacts", {}).get(identity):
                    row.setdefault("message_id", message_id)
                    row.setdefault("reply_links", []).append({"thread_id": thread_id, "message_id": message_id})
            self.storage.save(state)

    def mutate(self, operation, body):
        with self.lock:
            identity = body.get("id")
            before = self.find(identity)
            if operation == "retry" and body.keys() == {"id"}:
                if before["sync"] == "synced" or not (before.get("file_revision") or "content" in before):
                    return public(before)
                row = self.synchronize(before, retry=True)
                self.write(row)
                return public(row)
            if operation == "delete" and body.keys() == {"id", "revision"}:
                revision = body["revision"]
                if before.get("box_id") and before["sync"] == "synced" and not before.get("file_revision"):
                    if revision != self.box_revision(before):
                        before = self.checked_row(before, revision)
                elif revision != before["revision"]:
                    raise HearthError("This artifact changed. Reopen it before making another change.")
                deleted = {**before, "deleted": True, "revision": new_id(),
                           "sync_message": "Moved to Hearth Trash. The Box file remains in Box."
                           if before.get("box_id") else "Moved to Hearth Trash. Restore it from Timeline."}
                self.write(deleted, "deleted", before)
                return public(deleted)
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
            elif row.get("file_revision"):
                restored = self.undo_file_update(row, before)
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

    def undo_file_update(self, row, before):
        self.check_file_revision(row, row["revision"])
        raw = self.local_bytes(before)
        restored = self.stage_file(row, before["structured"], raw=raw)
        if row["sync"] == "synced":
            restored = self.synchronize(restored)
            if restored["sync"] != "synced":
                raise HearthError(restored["sync_message"])
        return restored

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
            item = client.upload(current, content.encode("utf-8"))
        except ConnectorError as error:
            raise HearthError(box.error_message(error, "restoring the previous version")) from None
        version = metadata(item)
        return {**before, **version, "box_connection": row["box_connection"],
                "box_history": box_versions(before, row, version), "sync": "synced", "sync_message": None,
                "content": content, "size": len(content.encode("utf-8")), "updated_at": iso()}
