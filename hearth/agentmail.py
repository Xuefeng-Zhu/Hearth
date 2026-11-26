import hashlib
import re
from time import monotonic
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request

from .connectors import ConnectorError
from .reminder_config import address
from .storage import HearthError

LIMIT = 64 * 1024


class AgentMail:
    def __init__(self, gateway, config, *, deadline=None):
        self.gateway, self.config = gateway, config
        self.deadline = deadline

    def call(self, path, data=None, key=None):
        timeout = 8 if self.deadline is None else min(8, self.deadline - monotonic())
        if timeout <= 0:
            raise ConnectorError("The AgentMail delivery timed out.", 504)
        return self.gateway.json(self.config, f"v0/inboxes{path}", data,
                                 {"Idempotency-Key": key} if key else None, timeout=timeout)

    def ensure_inbox(self):
        configured = self.config.get("inbox_id")
        client = "hearth-" + hashlib.sha256(self.config["connection_id"].encode()).hexdigest()[:16]
        if configured:
            result = self.call("/" + quote(configured, safe=""))
        else:
            page = {}
            result = None
            for _ in range(20):
                page = self.call("?" + urlencode({"limit": 100, **({"page_token": page["next_page_token"]}
                                                                   if page.get("next_page_token") else {})}))
                result = next((item for item in page.get("inboxes", []) if item.get("client_id") == client
                               and item.get("status") != "deactivated"), None)
                if result or not page.get("next_page_token"):
                    break
            if result is None:
                # AgentMail treats client_id as idempotent. A connection-specific username avoids
                # adopting an unrelated inbox with a popular name.
                result = self.call("", {"username": client, "display_name": "Hearth", "client_id": client})
        identity = result.get("inbox_id")
        email = address(result.get("email") or identity)
        if not email or not isinstance(identity, str) or len(identity) > 254:
            raise ConnectorError("AgentMail returned an unreadable inbox.")
        return {"id": identity, "address": email}

    @staticmethod
    def path(inbox, identity=None):
        base = f"/{quote(inbox['id'], safe='')}/messages"
        return f"{base}/{quote(identity, safe='')}" if identity else base

    def send(self, inbox, payload, key):
        return self.call(self.path(inbox) + "/send", payload, key)

    def reply(self, inbox, identity, sender, text, key):
        return self.call(self.path(inbox, identity) + "/reply", {"to": [sender], "reply_all": False, "text": text, "labels": ["hearth-ack"]}, key)

    def page(self, inbox, cursor, token):
        query = {"limit": 25, "ascending": "true"}
        if cursor:
            # The list API requires UTC with a Z suffix. Existing cursors store +00:00.
            query["after"] = cursor[:-6] + "Z" if cursor.endswith("+00:00") else cursor
        if token:
            query["page_token"] = token
        return self.call(self.path(inbox) + "?" + urlencode(query))

    def message(self, inbox, identity):
        return self.call(self.path(inbox, identity))

    def attachment_info(self, inbox, message, item):
        return self.call(self.path(inbox, message) + "/attachments/" + quote(item, safe=""))

    def attachment(self, inbox, message, item, *, pdf=False):
        info = self.attachment_info(inbox, message, item)
        if isinstance(info.get("text"), str):
            return info["text"][:LIMIT]
        url = info.get("text_url" if pdf else "download_url")
        if not url:
            return ""
        return self.download_attachment(url, LIMIT).decode("utf-8-sig", errors="replace")

    def attachment_bytes(self, inbox, message, item):
        info = self.attachment_info(inbox, message, item)
        if not info.get("download_url"):
            raise HearthError("AgentMail did not return an attachment download.")
        limit = 20 * 1024 * 1024
        raw = self.download_attachment(info["download_url"], limit + 1)
        if len(raw) > limit:
            raise HearthError("Email attachments must be at most 20 MiB.")
        return raw

    def download_attachment(self, url, limit):
        target = urlsplit(url)
        # URLs come only from the authenticated attachment metadata endpoint.
        host = target.hostname or ""
        if (target.scheme != "https" or target.netloc != host or not
                (host.endswith(".agentmail.to") or re.fullmatch(r"agentmail[-a-z0-9.]*\.amazonaws\.com", host)
                 or re.fullmatch(r"s3(?:[.-][a-z0-9-]+)?\.amazonaws\.com", host))):
            raise HearthError("Attachment download host is unavailable.")
        with self.gateway.opener.open(Request(url), timeout=5) as response:
            return response.read(limit)
