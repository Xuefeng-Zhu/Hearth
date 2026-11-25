"""Public-facing server for explicitly published page snapshots."""

import argparse
import hashlib
import hmac
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .page_policy import MAX_PAGE, PUBLIC_CSP, TOKEN
from .storage import atomic_write


def page_key(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class ShareServer(ThreadingHTTPServer):
    def __init__(self, address, directory, secret):
        self.directory = directory
        self.secret = "Bearer " + secret
        self.operation = threading.Lock()
        super().__init__(address, ShareHandler)


class ShareHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def respond(self, status, body=b""):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", PUBLIC_CSP)
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def snapshot(self, prefix):
        if not self.path.startswith(prefix):
            return None
        token = self.path[len(prefix):]
        if TOKEN.fullmatch(token):
            return self.server.directory / page_key(token)
        return None

    def do_GET(self):
        if path := self.snapshot("/p/"):
            try:
                raw = path.read_bytes()
            except FileNotFoundError:
                raw = b""
            if raw:
                return self.respond(200, raw)
        self.respond(404)

    do_HEAD = do_GET

    def write_path(self):
        path = self.snapshot("/_publish/")
        credential = self.headers.get("Authorization", "").encode("utf-8")
        if path and hmac.compare_digest(credential, self.server.secret.encode("utf-8")):
            return path
        self.respond(404)
        return None

    def do_PUT(self):
        if not (path := self.write_path()):
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_PAGE:
                return self.respond(400)
            self.connection.settimeout(15)
            raw = self.rfile.read(length)
            if len(raw) != length:
                return self.respond(400)
        except (ValueError, socket.timeout):
            return self.respond(400)
        with self.server.operation:
            if path.is_file():
                return self.respond(204 if path.read_bytes() == raw else 409)
            atomic_write(path, raw)
        self.respond(204)

    def do_DELETE(self):
        if path := self.write_path():
            with self.server.operation:
                # Keep a tombstone so a delayed publishing retry cannot resurrect the link.
                atomic_write(path, b"")
            self.respond(204)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    root = Path(os.environ["HEARTH_SHARE_DATA"])
    secret = (root / "secret").read_text().strip()
    if not TOKEN.fullmatch(secret):
        raise SystemExit("Invalid Hearth page publishing key.")
    with ShareServer(("0.0.0.0", args.port), root / "snapshots", secret) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
