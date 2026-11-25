"""The Box API through the Sprites connector. No provider credentials enter Hearth."""

import json
import re
from http.client import HTTPException
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener

from .connectors import ConnectorError, NoRedirect
from .gateway_tools import redact_text
from .storage import HearthError, new_id

FOLDERS = {"plan": "Plans", "list": "Lists", "note": "Notes",
           "transcript": "Transcripts", "export": "Exports"}
FORMATS = {"md": "text/markdown", "txt": "text/plain", "csv": "text/csv", "json": "application/json"}
DEFAULTS = {"auto_save": True, "format": "md", "folder_name": "Hearth"}
MAX_BYTES = 128 * 1024
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
UNAVAILABLE = "Saved locally — Box upload unavailable"
FIELDS = "id,type,name,size,modified_at,created_at,file_version,version_number,etag,sha1"
BOX_ID = re.compile(r"[0-9]{1,30}")


def box_id(value):
    return isinstance(value, str) and BOX_ID.fullmatch(value) is not None


def settings(value):
    if not isinstance(value, dict) or value.keys() - DEFAULTS.keys():
        raise HearthError("Invalid artifact settings.")
    result = {**DEFAULTS, **value}
    name = result["folder_name"]
    fmt = result["format"]
    if (type(result["auto_save"]) is not bool or not isinstance(fmt, str) or fmt not in FORMATS
            or not isinstance(name, str) or not 1 <= len(name.strip()) <= 80
            or name.strip() in (".", "..") or re.search(r'[/\\\x00-\x1f\x7f]', name)):
        raise HearthError("Choose a format and a Box folder name of 1–80 characters.")
    name = redact_text(name.strip())
    if "/" in name or "\\" in name:
        raise HearthError("Choose a folder name without credentials.")
    return {**result, "folder_name": name}


def error_message(error, operation):
    if unsupported(error):
        return f"The Sprites Box connector does not support {operation}."
    if error.status in (401, 403):
        return "Box denied access. Check the authorization in Connections."
    if error.status == 404:
        return "Box could not find this file or folder."
    if error.status in (409, 412):
        return "This item changed in Box. Refresh Artifacts and try again."
    if error.status == 413:
        return "Box rejected the file size."
    if error.status == 429:
        return "Box is limiting requests. Try again shortly."
    return f"Box could not complete {operation}. Try again."


def unsupported(error):
    return error.unsupported or error.status in (405, 501)


class Box:
    def __init__(self, gateway, connection):
        self.gateway = gateway
        self.connection = connection

    def json(self, path, body=None, headers=None, **options):
        return self.gateway.json(self.connection, f"2.0/{path}", body, headers, timeout=8, **options)

    def pages(self, path, **params):
        marker = None
        seen = set()
        while True:
            query = {"limit": 100, **params}
            if marker:
                query["marker"] = marker
            data = self.json(f"{path}?{urlencode(query)}")
            entries = data.get("entries")
            if not isinstance(entries, list):
                raise ConnectorError("Box returned an invalid list.")
            yield from (entry for entry in entries if isinstance(entry, dict))
            marker = data.get("next_marker")
            if not marker:
                return
            if not isinstance(marker, str) or marker in seen or len(seen) >= 100:
                raise ConnectorError("Box returned an invalid page marker.")
            seen.add(marker)

    def items(self, folder_id):
        return self.pages(f"folders/{folder_id}/items", usemarker="true", fields=FIELDS)

    def folders(self, parent, names):
        found = {item["name"].casefold(): item["id"] for item in self.items(parent)
                 if item.get("type") == "folder" and box_id(item.get("id")) and isinstance(item.get("name"), str)}
        for name in names:
            key = name.casefold()
            if key in found:
                continue
            try:
                item = self.json("folders", {"name": name, "parent": {"id": parent}})
            except ConnectorError as error:
                if error.status != 409:
                    raise
                # Another client may have created the folder since the listing.
                item = next((entry for entry in self.items(parent) if entry.get("type") == "folder"
                             and str(entry.get("name")).casefold() == key), {})
            if not box_id(item.get("id")):
                raise ConnectorError("Box did not return a folder ID.")
            found[key] = item["id"]
        return {name: found[name.casefold()] for name in names}

    def upload(self, row, folder_id=None):
        file_id = row.get("box_id")
        attrs = {} if file_id else {"name": row["filename"], "parent": {"id": folder_id}}
        boundary = new_id()
        content_type = FORMATS[row["format"]]
        content = row["content"].encode("utf-8")
        if len(content) > MAX_UPLOAD_BYTES:
            raise HearthError("Box uploads must be at most 50 MiB.")
        multipart = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="attributes"\r\n'
            f'Content-Type: application/json\r\n\r\n{json.dumps(attrs)}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{row["filename"]}"\r\n'
            f'Content-Type: {content_type}\r\n\r\n'
        ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("ascii")
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        if file_id and row.get("etag"):
            headers["If-Match"] = row["etag"]
        path = f"upload/files/{file_id}/content" if file_id else "upload/files/content"
        data = self.gateway.json(self.connection, f"{path}?{urlencode({'fields': FIELDS})}",
                                 multipart, headers, timeout=8)
        entries = data.get("entries")
        item = entries[0] if isinstance(entries, list) and entries and isinstance(entries[0], dict) else {}
        if not box_id(item.get("id")) or (file_id and item["id"] != file_id):
            raise ConnectorError("Box did not return a file ID.")
        return item

    def file(self, identity):
        return self.json(f"files/{identity}?{urlencode({'fields': FIELDS})}")

    def versions(self, identity):
        limit = 100
        for offset in range(0, 10_001, limit):
            query = urlencode({"limit": limit, "offset": offset, "fields": "id,version_number,modified_at,created_at"})
            data = self.json(f"files/{identity}/versions?{query}")
            entries = data.get("entries")
            if not isinstance(entries, list):
                raise ConnectorError("Box returned an invalid version history.")
            yield from (entry for entry in entries if isinstance(entry, dict))
            count = data.get("total_count")
            if not isinstance(count, int) or offset + limit >= count:
                return

    def content(self, identity, version=None):
        path = f"2.0/files/{identity}/content"
        if version:
            path += "?" + urlencode({"version": version})
        try:
            response = self.gateway.open(self.connection, path, timeout=8)
        except ConnectorError as error:
            if not error.location:
                raise
            # Box returns a signed download URL. Forward no headers or credentials.
            try:
                url = urlsplit(error.location)
                if (url.scheme != "https" or not (url.hostname or "").endswith(".boxcloud.com")
                        or url.netloc.lower() != url.hostname or url.fragment):
                    raise ValueError
                response = build_opener(NoRedirect()).open(Request(error.location), timeout=8)
            except (OSError, HTTPException, ValueError):
                raise ConnectorError("Box could not open the download.") from None
        try:
            with response:
                raw = response.read(MAX_BYTES + 1)
        except (OSError, HTTPException, URLError):
            raise ConnectorError("The Box download was interrupted.") from None
        if len(raw) > MAX_BYTES:
            raise HearthError("This file is too large to preview in Hearth.")
        try:
            return redact_text(raw.decode("utf-8-sig"))
        except UnicodeError:
            raise HearthError("This file cannot be previewed as UTF-8 text.") from None
