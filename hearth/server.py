import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .agent import Agent, require_text
from .checkpoints import LocalCheckpoints, SpriteCheckpoints
from .connections import Connections
from .connectors import Gateway, read_config
from .storage import HearthError, ROOT, Storage

STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


class Application:
    def __init__(self, storage, checkpoints, config, *, config_path=None, gateway=None):
        self.storage = storage
        self.checkpoints = checkpoints
        self.gateway = gateway or Gateway()
        self.connections = Connections(
            config, config_path or storage.live / "connectors.local.json", self.gateway, storage, checkpoints,
        )
        self.operation = threading.Lock()
        self.restore = None
        self.reload_agent()

    def reload_agent(self):
        self.agent = Agent(self.storage, self.checkpoints, self.connections.active_config(), self.gateway)
        self.brain = self.agent.models[0]["provider"] if self.agent.models else None
        self.connection_state = self.connections.report(self.brain)

    def scan_connections(self):
        if self.connections.scan():
            self.reload_agent()
        else:
            self.connection_state = self.connections.report(self.brain)

    def connection_info(self):
        return {**self.connection_state, "model": self.brain}

    def info(self):
        with self.storage.lock():
            state = self.storage.load()
        return {"messages": state["messages"], "actions": list(state["actions"].values()),
                "jobs": state["jobs"], "reminders": state["reminders"], "restore": self.restore,
                "checkpoints": self.checkpoints.mode, "model": self.brain}

    def timeline(self):
        with self.storage.lock():
            actions = self.storage.load()["actions"].values()
            known = {action["checkpoint"]["id"]: action["checkpoint"]
                     for action in actions if action.get("checkpoint")}
            return [known.get(item["id"], item) for item in self.checkpoints.list()]

    def start_restore(self, action_id):
        with self.storage.lock():
            action = self.storage.load()["actions"].get(action_id)
            if not self.agent.can_undo(action):
                raise HearthError("This action has no available Undo.")
        self.restore = {"action_id": action_id, "status": "restoring"}
        threading.Thread(target=self.restore_checkpoint, args=(action,), daemon=True).start()

    def restore_checkpoint(self, action):
        # Give the HTTP acknowledgement time to leave before the Sprite disconnects.
        time.sleep(0.35)
        with self.operation, self.storage.lock():
            try:
                self.checkpoints.restore(action["checkpoint"]["id"])
            except (HearthError, OSError):
                self.restore = {"action_id": action["id"], "status": "failed"}
            else:
                if self.checkpoints.mode == "local":
                    self.connections.reset()
                    self.reload_agent()
                    self.restore = None
                    return
        if self.restore["status"] == "restoring":
            # A successful native restore restarts the server and discards this thread.
            time.sleep(90)
            with self.operation:
                self.restore = {"action_id": action["id"], "status": "failed"}


class HTTPServer(ThreadingHTTPServer):
    def __init__(self, address, app):
        self.app = app
        super().__init__(address, Handler)

    def handle_error(self, request, client_address):
        # Requests, provider failures and CLI output may contain private data.
        pass


class Handler(BaseHTTPRequestHandler):
    @property
    def app(self):
        return self.server.app

    def log_message(self, format, *args):
        pass

    def response_headers(self, status, content_type, length=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if content_type == "text/event-stream":
            self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    def json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.response_headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def do_GET(self):
        url = urlsplit(self.path)
        try:
            if static := STATIC.get(url.path):
                filename, content_type = static
                body = (ROOT / "web" / filename).read_bytes()
                self.response_headers(200, content_type, len(body))
                self.wfile.write(body)
            elif url.path == "/health":
                self.json({"ok": True, "checkpoints": self.app.checkpoints.mode})
            elif url.path == "/api/state":
                self.json(self.app.info())
            elif url.path == "/api/connections":
                self.json(self.app.connection_info())
            elif url.path == "/api/checkpoints":
                self.json({"checkpoints": self.app.timeline()})
            elif url.path == "/api/memory":
                path = parse_qs(url.query).get("path", [None])[0]
                with self.app.storage.lock():
                    if path:
                        data = {"path": path, "content": self.app.storage.read(path)}
                    else:
                        data = {"files": self.app.storage.files()}
                self.json(data)
            else:
                self.json({"error": "Page not found."}, 404)
        except HearthError as error:
            self.json({"error": str(error)}, 400)

    def body(self):
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise HearthError("Send this request from Hearth.")
        if self.headers.get_content_type() != "application/json":
            raise HearthError("Expected a JSON request.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 24_000:
                raise ValueError
            body = json.loads(self.rfile.read(length))
        except ValueError:
            raise HearthError("Invalid or oversized request.") from None
        if not isinstance(body, dict):
            raise HearthError("Expected a JSON object.")
        return body

    def do_POST(self):
        routes = {"/api/chat", "/api/approve", "/api/undo",
                  "/api/connections/rescan", "/api/connections/test", "/api/connections/settings"}
        if self.path not in routes:
            self.json({"error": "Page not found."}, 404)
            return
        if not self.app.operation.acquire(blocking=False):
            self.json({"error": "Hearth is working on another action."}, 409)
            return
        try:
            if self.app.restore and self.app.restore["status"] == "restoring":
                self.json({"error": "A checkpoint is being restored."}, 409)
                return
            body = self.body()
            if self.path == "/api/chat":
                self.stream_chat(require_text(body.get("message"), 4_000))
            elif self.path.startswith("/api/connections/"):
                self.update_connections(body)
            else:
                action_id = require_text(body.get("id"), 40)
                if self.path == "/api/approve":
                    self.json(self.app.agent.approve(action_id))
                else:
                    self.app.start_restore(action_id)
                    self.json(self.app.restore, 202)
        except HearthError as error:
            self.json({"error": str(error)}, 400)
        finally:
            self.app.operation.release()

    def update_connections(self, body):
        if self.path == "/api/connections/rescan" and not body:
            self.app.scan_connections()
        elif self.path == "/api/connections/test" and body.keys() == {"provider"}:
            self.app.connections.test(body["provider"])
            self.app.reload_agent()
        elif self.path == "/api/connections/settings" and body.keys() == {"provider", "value"}:
            self.app.connections.save(body["provider"], body["value"])
            self.app.reload_agent()
        else:
            raise HearthError("Invalid connection request.")
        self.json(self.app.connection_info())

    def stream_chat(self, prompt):
        self.response_headers(200, "text/event-stream")
        connected = True

        def event(name, data):
            nonlocal connected
            if name == "done":
                self.app.brain = data["provider"]
            if connected:
                try:
                    self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except OSError:
                    connected = False

        try:
            self.app.agent.chat(prompt, event)
        except Exception:
            event("error", {"message": "Hearth could not finish this turn. Check Timeline for any completed actions."})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8080, type=int)
    args = parser.parse_args()
    storage = Storage()
    checkpoints = SpriteCheckpoints() if os.environ.get("HEARTH_CHECKPOINTS") == "sprite" else LocalCheckpoints(storage)
    config_path = os.environ.get("HEARTH_CONNECTOR_CONFIG")
    legacy_config = ROOT / "config/connectors.local.json"
    path = Path(config_path) if config_path else legacy_config if legacy_config.is_file() else None
    app = Application(storage, checkpoints, read_config(ROOT / "config/connectors.json"), config_path=path)
    app.scan_connections()
    with HTTPServer((args.host, args.port), app) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
