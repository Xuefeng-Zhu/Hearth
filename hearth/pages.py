"""Private page versions, item-level undo, and explicit publishing."""

import json
import secrets
from hashlib import sha1
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import box, page_html
from .artifacts import filename
from .connectors import ConnectorError
from .gateway_tools import redact_text
from .page_policy import TOKEN
from .storage import HearthError, atomic_write, iso, new_id
from .threads import compact


class PageError(HearthError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def version_number(value):
    if type(value) is not int or not 1 <= value <= 999_999_999:
        raise PageError("Choose a page version.")
    return value


def row_for(state, identity):
    row = state.get("pages", {}).get(identity) if isinstance(identity, str) else None
    if not row or row["version"] is None:
        raise PageError("Page not found.", 404)
    return row


def can_undo(state, action):
    row = state.get("pages", {}).get(action.get("page_id"))
    return bool(row and action.get("page_version") == row["version"] and
                action.get("page_version") is not None and not action.get("undone"))


def card(row):
    return {key: row[key] for key in ("id", "title", "version", "updated_at", "thread_id")}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Pages:
    def __init__(self, storage, artifacts, operation, *, share_config=None, private_edge=False):
        self.storage = storage
        self.artifacts = artifacts
        self.operation = operation
        self.root = storage.live / "pages"
        self.share_config = Path(share_config) if share_config else None
        self.private_edge = private_edge

    def publisher(self):
        if self.share_config and self.share_config.is_file():
            try:
                config = json.loads(self.share_config.read_text())
                origin, secret = config["origin"].rstrip("/"), config["secret"]
                url = urlsplit(origin)
                if url.scheme == "https" and url.hostname and not any((url.username, url.password, url.path,
                                                                       url.query, url.fragment)) and TOKEN.fullmatch(secret):
                    return origin, secret
            except (OSError, ValueError, AttributeError, TypeError, KeyError):
                pass
            raise PageError("The public page server configuration is invalid.", 503)
        if self.private_edge:
            raise PageError("Public page sharing is unavailable on this deployment.", 503)
        return "", ""

    def listing(self):
        with self.storage.lock():
            rows = [card(row) for row in self.storage.load().get("pages", {}).values() if row["version"] is not None]
        return sorted(reversed(rows), key=lambda row: row["updated_at"], reverse=True)

    def detail(self, identity):
        with self.storage.lock():
            state = self.storage.load()
            row = row_for(state, identity)
            share = row.get("share")
            details = {**card(row), "versions": row["versions"], "box_files": row.get("box_files", {})}
            if share:
                details["share"] = {"version": share["version"], "status": share["status"]}
                if share["status"] == "active":
                    details["share"]["url"] = share["origin"] + "/p/" + share["token"]
            pending = next((action for action in state["actions"].values() if action["kind"] == "page_share"
                            and action["page_id"] == identity and action["status"] == "pending"), None)
            if pending:
                details["approval"] = pending
            return details

    def path(self, row, version):
        return self.root / row["id"] / f"v{version}" / "index.html"

    def read(self, row, version):
        if not 1 <= version <= len(row["versions"]):
            raise PageError("Page version not found.", 404)
        return self.path(row, version).read_bytes()

    def document(self, identity, version=None):
        with self.storage.lock():
            row = row_for(self.storage.load(), identity)
            version = row["version"] if version is None else version_number(version)
            return card(row), self.read(row, version)

    def recent(self, thread_id):
        with self.storage.lock():
            rows = self.storage.load().get("pages", {}).values()
            recent = next((row for row in reversed(list(rows)) if row["thread_id"] == thread_id and row["version"]), None)
            return card(recent) if recent else None

    def save(self, title, raw, note, origin, *, identity=None, previous=None):
        with self.operation, self.storage.lock():
            state = self.storage.load()
            if identity:
                row = row_for(state, identity)
                if row["version"] != previous:
                    raise PageError("This page changed while Hearth was editing it. Try the edit again.", 409)
            else:
                row = {"id": new_id(), "title": title, "version": None, "versions": [], **origin}
                state.setdefault("pages", {})[row["id"]] = row
            action = self.add_version(state, row, raw, note, "Edited" if identity else "Built")
            return card(row), action

    def add_version(self, state, row, raw, note, verb):
        before = row["version"]
        version = len(row["versions"]) + 1
        now = iso()
        atomic_write(self.path(row, version), raw)
        note = compact(redact_text(note), 160)
        row["versions"].append({"version": version, "at": now, "note": note})
        row.update(version=version, updated_at=now)
        action = {"id": new_id(), "kind": "page", "title": f"{verb} page · {row['title']}",
                  "at": now, "status": "complete", "thread_id": row["thread_id"],
                  "thread_title": row["thread_title"], "page_id": row["id"],
                  "page_version": version, "previous_version": before, "note": note}
        state["actions"][action["id"]] = action
        self.storage.save(state)
        return action

    def revert(self, identity, version, current):
        version, current = version_number(version), version_number(current)
        with self.storage.lock():
            state = self.storage.load()
            row = row_for(state, identity)
            if row["version"] != current or current == version:
                raise PageError("Choose another version from the current page history.", 409)
            self.add_version(state, row, self.read(row, version), f"Reverted to v{version}.", "Restored")
        return self.detail(identity)

    def undo(self, action_id):
        with self.storage.lock():
            state = self.storage.load()
            action = state["actions"].get(action_id, {})
            if not can_undo(state, action):
                raise PageError("Undo the newer changes to this page first.", 409)
            row = row_for(state, action["page_id"])
            removes_page = action["previous_version"] is None
        if removes_page and row.get("share"):
            self.revoke(row["id"])
        with self.storage.lock():
            state = self.storage.load()
            action = state["actions"].get(action_id, {})
            if not can_undo(state, action):
                raise PageError("Undo the newer changes to this page first.", 409)
            row = row_for(state, action["page_id"])
            row.update(version=action["previous_version"], updated_at=iso())
            action.update(undone=True, undone_at=iso())
            self.storage.save(state)
            return action

    def request_share(self, identity, version):
        self.publisher()
        version = version_number(version)
        with self.storage.lock():
            state = self.storage.load()
            row = row_for(state, identity)
            if version > len(row["versions"]):
                raise PageError("Page version not found.", 404)
            if row.get("share"):
                raise PageError("Revoke the existing link before sharing a new version.", 409)
            for pending in state["actions"].values():
                if pending["kind"] == "page_share" and pending["page_id"] == identity and pending["status"] == "pending":
                    if pending["version"] == version:
                        return pending
                    pending["status"] = "canceled"
            action = {"id": new_id(), "kind": "page_share", "title": f"Share {row['title']}?",
                      "at": iso(), "status": "pending", "thread_id": row["thread_id"],
                      "thread_title": row["thread_title"], "page_id": identity, "version": version}
            state["actions"][action["id"]] = action
            self.storage.save(state)
            return action

    def publish_request(self, origin, token, method, raw=None):
        current, secret = self.publisher()
        if current != origin:
            raise PageError("The publishing endpoint changed. Restore its configuration to manage this link.", 503)
        if not origin:
            return
        request = Request(origin + "/_publish/" + token, data=raw, method=method,
                          headers={"Authorization": "Bearer " + secret, "Content-Type": "text/html; charset=utf-8"})
        try:
            with build_opener(NoRedirect()).open(request, timeout=15) as response:
                if response.status != 204:
                    raise PageError("The public page server could not complete the request.", 502)
        except (URLError, TimeoutError, OSError):
            raise PageError("The public page server could not complete the request. Try again.", 502) from None

    def approve_share(self, action_id):
        origin, _ = self.publisher()
        with self.storage.lock():
            state = self.storage.load()
            action = state["actions"].get(action_id, {})
            if action.get("kind") != "page_share":
                raise PageError("This approval does not exist.", 404)
            row = row_for(state, action["page_id"])
            share = row.get("share")
            if share and share["action_id"] == action_id and share["status"] == "active":
                return action
            if action["status"] != "pending" or (share and share["action_id"] != action_id):
                raise PageError("This approval is no longer available.", 409)
            raw = self.read(row, action["version"])
            if not share:
                share = {"version": action["version"], "action_id": action_id, "origin": origin,
                         "status": "publishing", "token": secrets.token_urlsafe(32)}
                row["share"] = share
                self.storage.save(state)
        self.publish_request(share["origin"], share["token"], "PUT", raw)
        with self.storage.lock():
            state = self.storage.load()
            state["pages"][row["id"]]["share"]["status"] = "active"
            action = state["actions"][action_id]
            action.update(status="complete", title=f"Shared page · {row['title']}", updated_at=iso())
            self.storage.save(state)
            return action

    def revoke(self, identity):
        with self.storage.lock():
            state = self.storage.load()
            row = row_for(state, identity)
            share = row.get("share")
        if share:
            self.publish_request(share["origin"], share["token"], "DELETE")
        with self.storage.lock():
            state = self.storage.load()
            row = row_for(state, identity)
            row.pop("share", None)
            for action in state["actions"].values():
                if action.get("kind") == "page_share" and action.get("page_id") == identity and action["status"] in {"pending", "complete"}:
                    action.update(status="revoked", title=f"Share link revoked · {row['title']}", updated_at=iso())
            self.storage.save(state)
        return self.detail(identity)

    def shared(self, token):
        if self.private_edge or not TOKEN.fullmatch(token):
            raise PageError("Page not found.", 404)
        with self.storage.lock():
            for row in self.storage.load().get("pages", {}).values():
                share = row.get("share", {})
                if share.get("token") == token and share["status"] == "active" and row["version"] is not None:
                    return self.read(row, share["version"])
        raise PageError("Page not found.", 404)

    def save_box(self, identity, version):
        version = version_number(version)
        with self.storage.lock():
            row = row_for(self.storage.load(), identity)
            previous = row.get("box_files", {}).get(str(version))
            raw = self.read(row, version)
        if previous:
            return previous
        if not (client := self.artifacts.client()):
            raise PageError("Connect Box to save this page.", 409)
        name = filename(row["title"], "html", f" (v{version} · {identity[:12]})")
        try:
            root = self.artifacts.bootstrap(client)["root"]
            folder = client.folders(root, ["Pages"])["Pages"]
            try:
                saved = client.upload({"filename": name, "mime": "text/html; charset=utf-8"}, raw, folder)
            except ConnectorError as error:
                if error.status != 409:
                    raise
                digest = sha1(raw).hexdigest()
                saved = next((item for item in client.items(folder) if item.get("name") == name and
                              item.get("sha1") == digest and box.box_id(item.get("id"))), None)
                if not saved:
                    raise
        except ConnectorError as error:
            raise PageError(box.error_message(error, "saving the page"), 502) from None
        result = {"url": f"https://app.box.com/file/{saved['id']}", "filename": name}
        with self.storage.lock():
            state = self.storage.load()
            row_for(state, identity).setdefault("box_files", {})[str(version)] = result
            self.storage.save(state)
        return result
