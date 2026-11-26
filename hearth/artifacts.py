"""Local artifact copies, Box synchronization, and item-level Timeline undo."""

import hashlib
import re
import threading
import time
import unicodedata
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from datetime import datetime

from . import box, office, timeline
from .connectors import ConnectorError
from .gateway_tools import redact_text
from .storage import HearthError, atomic_write, iso, new_id
from .threads import compact

BOX_FRESH_SECONDS = 30
BOX_RETRY_SECONDS = 5
QUESTION_FORMATS = {*office.MIME_TYPES, "txt", "md", "csv"}
BINDING_FIELDS = {"message_id", "reply_links"}


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


def public(row, *, content=False):
    hidden = {"content", "box_connection", "box_history", "etag", "deleted", "folder_id", "folder_connection",
              "source_tag", "from_message", "file_revision", "file_history", "structured", "reply_links", "box_filename"}
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
        self.refresh = None
        self.refreshed_at = None
        self.refresh_after = 0
        self.box_error = None
        self.writes = set()
        self.epoch = 0
        self.restoring = lambda: False

    def config(self):
        return self.connections.config.get("artifacts", box.DEFAULTS)

    def connection(self):
        return self.connections.selected.get("box")

    def box_scope(self):
        return self.connection(), self.config()["folder_name"]

    def client(self, identity=None):
        if identity is None:
            identity = self.connection()
        return box.Box(self.connections.gateway, self.connections.gateway_entry("box", identity)) if identity else None

    def info(self):
        return {"settings": self.config(), "connected": bool(self.connection())}

    def bootstrap(self, client, scope=None, epoch=None, *, rebuild=False):
        connection, name = scope or self.box_scope()
        epoch = self.epoch if epoch is None else epoch
        cache = self.connections.config.get("box_folders", {})
        if not rebuild and cache.get("name") == name and cache.get("connection") == connection:
            return cache
        root = client.folders("0", [name])[name]
        subfolders = client.folders(root, box.FOLDERS.values())
        cache = {"name": name, "connection": connection, "root": root,
                 "kinds": {kind: subfolders[label] for kind, label in box.FOLDERS.items()}}
        with self.operation:
            self.check_workspace(epoch)
            if self.box_scope() != (connection, name):
                raise HearthError("The Artifacts Box folder changed. Refresh Artifacts and try again.")
            self.connections.save_box_folders(cache)
        return cache

    def walk(self, client, scope):
        connection, name = scope
        cache = self.connections.config.get("box_folders", {})
        root = cache.get("root") if cache.get("name") == name and cache.get("connection") == connection else None
        if root:
            try:
                return self.walk_tree(client, root, connection)
            except ConnectorError as error:
                if error.status != 404:
                    raise
        root = next((item["id"] for item in client.items("0") if item.get("type") == "folder"
                     and str(item.get("name")).casefold() == name.casefold() and box.box_id(item.get("id"))), None)
        if root is None:
            return {}
        return self.walk_tree(client, root, connection)

    def walk_tree(self, client, root, connection):
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
                            row = self.box_row(item, kind, connection)
                            rows[row["id"]] = row
                pending = next_level
        return rows

    def box_row(self, item, kind, connection):
        label = redact_text(item["name"])
        stem, sep, ext = label.rpartition(".")
        fmt = re.sub(r"[^a-z0-9]", "", ext.lower())[:12] if sep else ""
        title = stem if sep and stem else label
        row = {**metadata(item), "id": f"box-{item['id']}", "title": title[:160], "filename": filename(title, fmt),
               "box_filename": label[:255],
               "box_connection": connection, "kind": kind, "format": fmt, "source": "Box",
               "sync": "synced", "size": item.get("size"), "created_at": when(item.get("created_at")),
               "updated_at": when(item.get("modified_at"))}
        return {**row, "revision": self.box_revision(row)}

    @staticmethod
    def box_revision(row):
        return f"box:{row.get('etag') or row.get('version_id') or row.get('box_updated_at')}"

    def reset(self):
        with self.lock:
            self.epoch += 1
            self.clear_listing(None)

    def clear_listing(self, scope):
        self.scope, self.remote = scope, {}
        self.refresh = self.refreshed_at = self.box_error = None
        self.refresh_after = 0

    def listing_cache(self, *, force=False):
        # Call with the artifact lock held. The worker does the walk outside it.
        scope = self.box_scope()
        if self.scope != scope:
            self.clear_listing(scope)
        client = self.client(scope[0]) if scope[0] else None
        if (client and not self.restoring() and (self.refresh is None or self.refresh.done())
                and (force or time.monotonic() >= self.refresh_after)):
            self.refresh = Future()
            threading.Thread(target=self.refresh_listing, args=(client, scope, self.refresh),
                             name="box-artifact-list", daemon=True).start()
        return scope, client, self.refresh, self.epoch

    def refresh_for_read(self):
        with self.lock:
            return self.listing_cache(force=True)

    def refresh_listing(self, client, scope, refresh):
        try:
            remote, error = self.walk(client, scope), None
        except ConnectorError as exc:
            remote, error = {}, box.error_message(exc, "listing the folder")
        except HearthError as exc:
            remote, error = {}, str(exc)
        except Exception:
            remote, error = {}, "Box could not complete listing the folder. Try again."
        with self.lock:
            if self.refresh is refresh and scope == self.box_scope():
                if error is None:
                    self.remote = remote
                    self.refreshed_at = iso()
                self.box_error = error
                self.refresh_after = time.monotonic() + (BOX_RETRY_SECONDS if error else BOX_FRESH_SECONDS)
            refresh.set_result((remote, error))

    def list(self, *, force=False):
        with self.lock:
            scope, _, refresh, _ = self.listing_cache(force=force)
            settings = self.config()
            remote, error, refreshed_at = self.remote, self.box_error, self.refreshed_at
            if refresh and not refresh.done():
                status = "refreshing"
            else:
                status = "stale" if error or not refreshed_at else "fresh"
        with self.storage.lock():
            state = self.storage.load()
        rows = self.list_rows(state, scope[0], remote, error)
        return {"settings": settings, "connected": bool(scope[0]), "artifacts": [*rows, *page_artifacts(state)],
                "box_error": error, "box_status": status, "box_refreshed_at": refreshed_at}

    @staticmethod
    def list_rows(state, connection, remote, error):
        local = state.get("artifacts", {})
        represented = {row["box_id"] for row in local.values()
                       if row.get("box_id") and row.get("box_connection") == connection}
        represented.update(saved["url"].removeprefix("https://app.box.com/file/")
                           for page in state.get("pages", {}).values()
                           for saved in page.get("box_files", {}).values())
        rows = [row for row in remote.values() if row["box_id"] not in represented]
        rows.extend(row for row in local.values() if not row.get("deleted"))
        for row in rows:
            current = None
            if row.get("box_id") and row.get("box_connection") == connection and row["sync"] == "synced":
                current = remote.get(f"box-{row['box_id']}")
            if current and not row.get("file_revision"):
                row = {**row, "updated_at": current["updated_at"], "size": current["size"]}
            item = public(row)
            if current and not error and current["format"] in QUESTION_FORMATS:
                item["ask_filename"] = current["box_filename"]
            yield item

    def question_files(self):
        scope, client, refresh, epoch = self.refresh_for_read()
        if not client:
            raise HearthError("Connect Box in Settings to ask about your files.")
        if refresh is None:
            raise HearthError("The workspace is being restored. Try again.")
        remote, error = refresh.result()
        if error:
            raise HearthError(error)
        if scope != self.box_scope() or epoch != self.epoch:
            raise HearthError("The Artifacts Box folder changed. Refresh Artifacts and try again.")
        with self.storage.lock():
            state = self.storage.load()
        rows = {item["id"]: {**remote[f"box-{item['box_id']}"], "id": item["id"], "title": item["title"]}
                for item in self.list_rows(state, scope[0], remote, error) if item.get("ask_filename")}
        return client, scope, rows

    def memory_rows(self, previous):
        scope, client, refresh, epoch = self.refresh_for_read()
        if refresh is None:
            return None, False
        remote, error = refresh.result()
        if scope != self.box_scope() or epoch != self.epoch or self.restoring():
            return None, False
        if error:
            return None, True
        with self.storage.lock():
            local = self.storage.load().get("artifacts", {})
        represented = {row["box_id"]: row for row in local.values()
                       if row.get("box_id") and row.get("box_connection") == scope[0]}
        rows = {}
        incomplete = False
        for row in remote.values():
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
            except HearthError:
                incomplete = True
                if old:
                    rows[key] = old
            else:
                rows[key] = {**row, "id": key, "content": content}
        if scope != self.box_scope() or epoch != self.epoch or self.restoring():
            return None, False
        return rows, incomplete

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
            with self.lock:
                scope, _, refresh, epoch = self.listing_cache()
                remote = self.remote
            if identity not in remote and refresh:
                # Direct links can wait for the first scoped listing.
                refreshed, error = refresh.result()
                if not error:
                    remote = refreshed
            if scope == self.box_scope() and epoch == self.epoch:
                row = remote.get(identity)
        if row is None or row.get("deleted"):
            raise HearthError("This artifact is no longer available.")
        return row

    def for_row(self, row):
        connection = self.connection()
        return self.client(connection) if connection and row.get("box_connection") == connection else None

    def detail(self, identity, *, versions=True):
        from .pages import page_detail

        with self.storage.lock():
            state = self.storage.load()
            if isinstance(identity, str) and (row := state.get("pages", {}).get(identity)) and row["version"] is not None:
                return {**page_artifact(row), **page_detail(state, row)}
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
                "warnings": warnings, "download_available": bool(row.get("file_revision")),
                "box_connected": bool(self.connection())}

    def file_path(self, row):
        return self.storage.live / "artifacts" / row["id"] / f"{row['file_revision']}.{row['format']}"

    @contextmanager
    def download(self, identity, *, inline=False):
        from .pages import page_bytes

        with self.storage.lock():
            state = self.storage.load()
            row = state.get("pages", {}).get(identity) if isinstance(identity, str) else None
            if row and row["version"] is not None:
                if inline:
                    raise HearthError("Inline preview requires a local PDF.")
                page = page_artifact(row)
                raw = page_bytes(self.storage, row, row["version"])
            else:
                page = None
        if page:
            with BytesIO(raw) as stream:
                yield page, stream
            return
        row = self.find(identity)
        if inline and (row["format"] != "pdf" or not row.get("file_revision")):
            raise HearthError("Inline preview requires a local PDF.")
        if row.get("file_revision") or "content" in row:
            with self.open_local(row) as stream:
                yield row, stream
            return
        if client := self.for_row(row):
            try:
                stream = client.download_file(row["box_id"])
            except ConnectorError as error:
                raise HearthError(box.error_message(error, "downloading the file")) from None
            with stream:
                yield row, stream
            return
        raise HearthError("Connect the original Box account to download this file.")

    def open_local(self, row):
        if row.get("file_revision"):
            return self.file_path(row).open("rb")
        if "content" in row:
            return BytesIO(row["content"].encode("utf-8"))
        raise HearthError("This artifact has no saved local copy.")

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
                with self.download(row["id"]) as (_, stream):
                    result["preview"] = office.preview(row["format"], stream)
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
        row = self.find(identity)
        if not row.get("structured"):
            raise HearthError("This file was imported. Hearth can edit files it generated.")
        return {"id": identity, "format": row["format"], "revision": row["revision"], **row["structured"]}

    def check_workspace(self, epoch):
        if epoch != self.epoch or self.restoring():
            raise HearthError("The workspace changed while saving this artifact. Try again.")

    @contextmanager
    def commit(self, identity, epoch, expected, *, snapshot=None, reserved=False):
        with self.operation, self.lock, self.storage.lock():
            self.check_workspace(epoch)
            state = self.storage.load()
            current = state.get("artifacts", {}).get(identity)
            revision = current["revision"] if current else None
            if revision != expected or (identity in self.writes) != reserved:
                raise HearthError("This artifact changed. Reopen it before making another change.")
            if snapshot is not None and any(current.get(key) != snapshot.get(key)
                                            for key in (current.keys() | snapshot.keys()) - BINDING_FIELDS):
                raise HearthError("This artifact changed. Reopen it before making another change.")
            yield state

    def write(self, state, row, operation=None, before=None):
        current = state.get("artifacts", {}).get(row["id"], {})
        for key in BINDING_FIELDS:
            if key in current:
                row = {**row, key: current[key]}
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

    def synchronize(self, row, client, scope, epoch, content, *, retry=False, progress=lambda row: None):
        if client is None:
            return {**row, "sync": "local", "sync_message": "Box is disconnected."}
        connection = scope[0]
        try:
            folder = row.get("folder_id") if row.get("folder_connection") == connection else None
            if not row.get("box_id") and not folder:
                folder = self.bootstrap(client, scope, epoch)["kinds"][row["kind"]]
                row = {**row, "folder_id": folder, "folder_connection": connection}
                progress(row)
            checksum = None
            if retry:
                checksum = hashlib.file_digest(content, "sha1").hexdigest()
            current = None
            if retry and row.get("box_id"):
                current = client.file(row["box_id"])
                if current.get("sha1") != checksum:
                    current = None
            if current is None:
                def upload():
                    self.check_workspace(epoch)
                    if self.connection() != connection or (not row.get("box_id") and self.box_scope() != scope):
                        raise HearthError("The Artifacts Box folder changed. Refresh Artifacts and try again.")
                    content.seek(0)
                    return client.upload(row, content, folder)

                try:
                    current = upload()
                except ConnectorError as error:
                    if error.status == 404 and not row.get("box_id"):
                        folder = self.bootstrap(client, scope, epoch, rebuild=True)["kinds"][row["kind"]]
                        row = {**row, "folder_id": folder}
                        progress(row)
                        current = upload()
                    elif error.status == 409 and not row.get("box_id"):
                        if retry:
                            current = next((item for item in client.items(folder) if item.get("type") == "file"
                                            and item.get("name") == row["filename"] and box.box_id(item.get("id"))
                                            and item.get("sha1") == checksum), None)
                        if current is None:
                            title, fmt = row["title"], row["format"]
                            if fmt == "file":
                                stem, dot, ext = row["filename"].rpartition(".")
                                title, fmt = (stem, ext) if dot else (row["filename"], "")
                            name = filename(title, fmt, f" - {row['id'][:8]}")
                            if name == row["filename"]:
                                raise
                            row = {**row, "filename": name}
                            progress(row)
                            current = upload()
                    else:
                        raise
        except ConnectorError as error:
            if box.unsupported(error):
                return {**row, "sync": "local", "sync_message": box.UNAVAILABLE}
            return {**row, "sync": "error", "sync_message": box.error_message(error, "saving the file")}
        except (HearthError, OSError):
            return {**row, "sync": "error",
                    "sync_message": "Hearth could not confirm the Box upload. A local copy is available."}
        version = metadata(current)
        if row.get("file_history"):
            last = {**row["file_history"][-1], "box_version_id": version["version_id"],
                    "box_version_number": version["version_number"]}
            row = {**row, "file_history": [*row["file_history"][:-1], last]}
        return {**row, **version, "box_history": box_versions(row, version), "box_connection": connection,
                "sync": "synced", "sync_message": None}

    def create(self, fmt, value, *, kind="note", origin=None):
        epoch = self.epoch
        if not isinstance(kind, str) or kind not in box.FOLDERS:
            raise HearthError("Choose a valid artifact kind.")
        value = office.prepare(fmt, value)
        title = compact(value["title"], 160) or "Artifact"
        if title.casefold().endswith("." + fmt):
            title = title[:-(len(fmt) + 1)].rstrip() or "Artifact"
        row = {"id": new_id(), "title": title, "kind": kind, "filename": filename(title, fmt),
               "format": fmt, "source": "Hearth", "created_at": iso(), **(origin or {})}
        return self.save_file(row, value, epoch)

    @staticmethod
    def file_version(row, value, size):
        if size > box.MAX_UPLOAD_BYTES:
            raise HearthError("Files must be at most 50 MiB.")
        revision, now = new_id(), iso()
        history = row.get("file_history", [])
        entry = {"id": revision, "number": len(history) + 1, "at": now}
        return {**row, "structured": value, "file_revision": revision, "revision": revision, "updated_at": now,
                "size": size, "sync": "local", "sync_message": None, "file_history": [*history, entry]}

    def stage_file(self, row, value, *, raw=None, path=None):
        if raw is None:
            raw = office.generate(row["format"], value)
        row = self.file_version(row, value, len(raw))
        atomic_write(path or self.file_path(row), raw)
        return row

    def install_file(self, row, path):
        target = self.file_path(row)
        target.parent.mkdir(parents=True, exist_ok=True)
        path.replace(target)

    def import_mail(self, name, raw, *, origin, sync):
        from .uploads import safe_filename

        epoch = self.epoch
        name = safe_filename(name)
        row = {"id": new_id(), "title": name, "filename": name, "kind": "export", "format": "file",
               "mime": "application/octet-stream", "source": "Email", "source_tag": "event-automation",
               "created_at": iso(), **origin}
        return self.save_file(row, None, epoch, raw=raw, sync=sync)

    def save_file(self, row, value, epoch, *, before=None, raw=None, sync=None):
        identity = row["id"]
        operation = "updated" if before else "created"
        expected = before["revision"] if before else None
        with TemporaryDirectory(dir=self.storage.root) as staging:
            path = Path(staging) / "file"
            row = self.stage_file(row, value, raw=raw, path=path)
            if before:
                self.require_revision(self.find(identity), expected)
                self.check_file_revision(before, expected)
            with self.commit(identity, epoch, expected, snapshot=before) as state:
                scope = self.box_scope()
                if before and before.get("box_id") and before.get("box_connection") != scope[0]:
                    raise HearthError("Connect the original Box account to change this file.")
                if sync is None:
                    sync = self.config()["auto_save"] and bool(scope[0])
                client = self.client(scope[0]) if sync and scope[0] else None
                self.install_file(row, path)
                if sync:
                    row["sync"] = "saving"
                    self.write(state, row)
                    self.writes.add(identity)
                else:
                    self.write(state, row, operation, before)
        if sync:
            return self.finish_sync(row, client, scope, epoch, operation=operation, before=before)
        self.on_memory_change()
        return public(row)

    def finish_sync(self, row, client, scope, epoch, *, operation=None, before=None, retry=False):
        identity, expected = row["id"], row["revision"]

        def progress(pending):
            with self.commit(identity, epoch, expected, reserved=True) as state:
                self.write(state, pending)

        try:
            try:
                with self.open_local(row) as content:
                    row = self.synchronize(row, client, scope, epoch, content, retry=retry, progress=progress)
            except OSError:
                row = {**row, "sync": "error", "sync_message": "Hearth could not read the saved local copy."}
            with self.commit(identity, epoch, expected, reserved=True) as state:
                self.write(state, row, operation, before)
        finally:
            with self.lock:
                self.writes.remove(identity)
        self.on_memory_change()
        return public(row)

    def update(self, fmt, identity, revision, value):
        epoch = self.epoch
        row = self.find(identity)
        if row["format"] != fmt or not row.get("structured"):
            raise HearthError("Choose a file of this type generated by Hearth.")
        self.require_revision(row, revision)
        return self.save_file(row, office.prepare(fmt, value), epoch, before=row)

    @staticmethod
    def require_revision(row, revision):
        if row["revision"] != revision:
            raise HearthError("This artifact changed. Read its latest version before editing.")

    def check_file_revision(self, row, revision):
        self.require_revision(row, revision)
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
        epoch = self.epoch
        identity = body.get("id")
        before = self.find(identity)
        if operation == "retry" and body.keys() == {"id"}:
            if before["sync"] == "synced" or not (before.get("file_revision") or "content" in before):
                return public(before)
            with self.commit(identity, epoch, before["revision"], snapshot=before) as state:
                scope = self.box_scope()
                client = None
                if scope[0] and (not before.get("box_id") or before.get("box_connection") == scope[0]):
                    client = self.client(scope[0])
                row = {**before, "sync": "saving"}
                self.write(state, row)
                self.writes.add(identity)
            return self.finish_sync(row, client, scope, epoch, retry=True)
        if operation == "delete" and body.keys() == {"id", "revision"}:
            scope = self.box_scope()
            revision = body["revision"]
            with self.storage.lock():
                current = self.storage.load().get("artifacts", {}).get(identity)
            snapshot = before if current else None
            expected = before["revision"] if current else None
            legacy = before.get("box_id") and before["sync"] == "synced" and not before.get("file_revision")
            if legacy and before.get("box_connection") == scope[0]:
                before = self.checked_row(before, revision)
            elif revision != (self.box_revision(before) if legacy else before["revision"]):
                raise HearthError("This artifact changed. Reopen it before making another change.")
            deleted = {**before, "deleted": True, "revision": new_id(),
                       "sync_message": "Moved to Hearth Trash. The Box file remains in Box."
                       if before.get("box_id") else "Moved to Hearth Trash. Restore it from Timeline."}
            with self.commit(identity, epoch, expected, snapshot=snapshot) as state:
                if identity.startswith("box-") and (scope != self.box_scope() or before["box_connection"] != scope[0]):
                    raise HearthError("The Artifacts Box folder changed. Refresh Artifacts and try again.")
                self.write(state, deleted, "deleted", before)
            self.on_memory_change()
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
        epoch = self.epoch
        with self.storage.lock():
            state = self.storage.load()
            action = state.get("artifact_undo", {}).get(action_id)
            row = state.get("artifacts", {}).get(action["id"]) if action else None
        if not row or row["revision"] != action["revision"]:
            raise HearthError("This artifact changed after that action. Undo the most recent change first.")
        identity, expected = row["id"], row["revision"]
        with self.commit(identity, epoch, expected, snapshot=row):
            scope = self.box_scope()
            client = self.for_row(row)
            self.writes.add(identity)
        try:
            with TemporaryDirectory(dir=self.storage.root) as staging:
                path = Path(staging) / "file"
                operation, before = action["operation"], action["before"]
                if operation == "created":
                    restored = {**row, "deleted": True}
                elif operation == "deleted":
                    restored = before
                elif row.get("file_revision"):
                    self.check_file_revision(row, expected)
                    copyfile(self.file_path(before), path)
                    restored = self.file_version(row, before["structured"], path.stat().st_size)
                    if row["sync"] == "synced":
                        with path.open("rb") as content:
                            restored = self.synchronize(restored, client, scope, epoch, content)
                        if restored["sync"] != "synced":
                            raise HearthError(restored["sync_message"])
                else:
                    restored = self.undo_update(row, before)
                with self.commit(identity, epoch, expected, reserved=True) as state:
                    if path.is_file():
                        self.install_file(restored, path)
                    del state["artifact_undo"][action_id]
                    event = next(event for event in state["activity"] if event["id"] == action_id)
                    event.update(undone=True, undoable=False, undone_at=iso())
                    self.write(state, restored)
        finally:
            with self.lock:
                self.writes.remove(identity)
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
            item = client.upload(current, content.encode("utf-8"))
        except ConnectorError as error:
            raise HearthError(box.error_message(error, "restoring the previous version")) from None
        version = metadata(item)
        return {**before, **version, "box_connection": row["box_connection"],
                "box_history": box_versions(before, row, version), "sync": "synced", "sync_message": None,
                "content": content, "size": len(content.encode("utf-8")), "updated_at": iso()}
