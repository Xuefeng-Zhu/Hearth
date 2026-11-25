import argparse
import json
import os
import re
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, SimpleQueue
from urllib.parse import parse_qs, urlsplit

from .agent import Agent, require_text
from .checkpoints import LocalCheckpoints, SpriteCheckpoints
from .connections import Connections
from .connectors import Gateway, read_config
from .gateway_tools import redact_text
from .storage import HearthError, ROOT, Storage
from .threads import MAIN, Threads, compact

STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
SIDE_COMMAND = re.compile(r"/(?:side|btw)(?:\s+(.+))?", re.I | re.S)


class Application:
    def __init__(self, storage, checkpoints, config, *, config_path=None, gateway=None):
        self.storage = storage
        self.threads = Threads(storage)
        self.checkpoints = checkpoints
        self.gateway = gateway or Gateway()
        self.connections = Connections(
            config, config_path or storage.live / "connectors.local.json", self.gateway, storage, checkpoints,
        )
        self.operation = threading.Lock()
        self.turn_lock = threading.Lock()
        self.turns = {}
        self.restore = None
        self.reload_agent()

    def reload_agent(self, *, reset_brain=True):
        self.agent = Agent(self.storage, self.checkpoints, self.connections.active_config(), self.gateway)
        if reset_brain:
            self.brain = self.agent.models[0]["provider"] if self.agent.models else None
        self.connection_state = self.connections.report()

    def scan_connections(self):
        if self.connections.scan():
            previous_models = self.agent.models
            self.reload_agent(reset_brain=False)
            if self.agent.models != previous_models:
                self.brain = self.agent.models[0]["provider"] if self.agent.models else None
        else:
            self.connection_state = self.connections.report()

    def connection_info(self):
        return {**self.connection_state, **self.brain_status()}

    def brain_status(self):
        model = next((entry["model"] for entry in self.agent.models if entry["provider"] == self.brain), "")
        return {"model": self.brain, "model_id": model}

    def brain_info(self):
        return {**self.connections.brain_info(), **self.brain_status(), "scan_error": self.connections.scan_error}

    def info(self, thread_id=MAIN):
        with self.turn_lock:
            active = set(self.turns)
        with self.storage.lock():
            state = self.storage.load()
            threads = self.threads.list()
            if not any(thread["id"] == thread_id for thread in threads):
                thread_id = MAIN
            messages = self.threads.messages(thread_id)
        return {"thread_id": thread_id, "threads": [{**thread, "busy": thread["id"] in active} for thread in threads],
                "messages": messages, "actions": list(state["actions"].values()),
                "jobs": state["jobs"], "reminders": state["reminders"], "restore": self.restore,
                "checkpoints": self.checkpoints.mode, **self.brain_status()}

    def timeline(self):
        with self.storage.lock():
            actions = self.storage.load()["actions"].values()
            known = {action["checkpoint"]["id"]: {**action["checkpoint"],
                     "thread_id": action.get("thread_id", MAIN), "thread_title": action.get("thread_title", "Main")}
                     for action in actions if action.get("checkpoint")}
        return [known.get(item["id"], item) for item in self.checkpoints.list()]

    def enqueue(self, thread_id, prompt):
        command = SIDE_COMMAND.fullmatch(prompt) if thread_id == MAIN else None
        if command:
            prompt = require_text(command[1], 4_000)
        with self.storage.lock():
            thread = self.threads.create() if command else self.threads.describe(thread_id)
        thread_id = thread["id"]
        events = SimpleQueue()
        events.put(("queued", {"thread": thread, "prompt": redact_text(prompt)}))
        with self.turn_lock:
            pending = self.turns.get(thread_id)
            if pending is not None:
                pending.append((prompt, events))
            else:
                self.turns[thread_id] = deque([(prompt, events)])
                threading.Thread(target=self.run_turns, args=(thread_id,), daemon=True).start()
        return events

    def run_turns(self, thread_id):
        while True:
            with self.turn_lock:
                prompt, events = self.turns[thread_id][0]
            agent = self.agent

            def event(name, data):
                if name == "done" and self.agent is agent:
                    self.brain = data["provider"]
                events.put((name, data))

            try:
                agent.chat(prompt, event, thread_id)
            except Exception:
                event("error", {"message": "Hearth could not finish this turn. Check Timeline for any completed actions."})
            finally:
                with self.turn_lock:
                    pending = self.turns[thread_id]
                    pending.popleft()
                    if not pending:
                        del self.turns[thread_id]
                events.put(None)
            if not pending:
                return

    def update_thread(self, operation, body):
        if operation == "create" and not body:
            with self.storage.lock():
                return self.threads.create()
        thread_id = body.get("thread_id")
        if operation == "delete":
            with self.turn_lock:
                if isinstance(thread_id, str) and thread_id in self.turns:
                    raise HearthError("Wait for this chat to finish before deleting it.")
        with self.storage.lock():
            self.threads.require_side(thread_id)
            if operation == "rename" and body.keys() == {"thread_id", "title"}:
                title = " ".join(redact_text(require_text(body["title"], 80)).split())
                return self.threads.rename(thread_id, title)
            if operation == "delete" and body.keys() == {"thread_id"}:
                thread = self.threads.describe(thread_id)
                try:
                    checkpoint = self.checkpoints.create("Before deleting a Hearth side chat")
                    self.threads.delete(thread_id)
                except OSError:
                    raise HearthError("Hearth could not checkpoint and delete this chat.") from None
                return self.agent.add_action("thread", "Side chat deleted", status="complete", checkpoint=checkpoint,
                                             thread_id=thread_id, thread_title=thread["title"])
            if operation == "share" and body.keys() == {"thread_id", "message_id"}:
                messages = self.threads.messages(thread_id)
                message = next((item for item in messages if item["id"] == body["message_id"]), None)
                if not message:
                    raise HearthError("That message no longer exists.")
                thread = self.threads.describe(thread_id)
                quote = compact(redact_text(message["content"]), 500)
                text = f"Shared from {thread['title']}\n\n> {quote}"
                return self.threads.append(MAIN, "user", text, shared_from=thread_id)
        raise HearthError("Invalid chat request.")

    def start_restore(self, action_id):
        with self.turn_lock:
            if self.turns:
                raise HearthError("Wait for active chats to finish before restoring a checkpoint.")
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
                thread_id = parse_qs(url.query).get("thread", [MAIN])[0]
                self.json(self.app.info(thread_id))
            elif url.path == "/api/connections":
                self.json(self.app.connection_info())
            elif url.path == "/api/brain":
                self.json(self.app.brain_info())
            elif url.path == "/api/brain/models":
                provider = parse_qs(url.query).get("provider", [None])[0]
                self.json(self.app.connections.brain_models(provider))
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
                  "/api/connections/rescan", "/api/connections/test", "/api/connections/settings",
                  "/api/brain/test", "/api/brain/settings", "/api/threads/create", "/api/threads/rename",
                  "/api/threads/delete", "/api/threads/share"}
        if self.path not in routes:
            self.json({"error": "Page not found."}, 404)
            return
        try:
            body = self.body()
        except HearthError as error:
            self.json({"error": str(error)}, 400)
            return
        if self.app.restore and self.app.restore["status"] == "restoring":
            self.json({"error": "A checkpoint is being restored."}, 409)
            return
        accepting_chat = self.path == "/api/chat" or self.path.startswith("/api/threads/")
        if not self.app.operation.acquire(blocking=accepting_chat):
            self.json({"error": "Hearth is working on another action."}, 409)
            return
        status = 200
        stream = None
        try:
            if self.app.restore and self.app.restore["status"] == "restoring":
                result, status = {"error": "A checkpoint is being restored."}, 409
            else:
                if self.path == "/api/chat":
                    stream = self.app.enqueue(body.get("thread_id", MAIN), require_text(body.get("message"), 4_000))
                elif self.path.startswith("/api/threads/"):
                    result = self.app.update_thread(self.path.rsplit("/", 1)[-1], body)
                elif self.path.startswith("/api/connections/"):
                    result = self.update_connections(body)
                elif self.path.startswith("/api/brain/"):
                    result = self.update_brain(body)
                else:
                    action_id = require_text(body.get("id"), 40)
                    if self.path == "/api/approve":
                        result = self.app.agent.approve(action_id)
                    else:
                        self.app.start_restore(action_id)
                        result, status = self.app.restore, 202
        except HearthError as error:
            result, status = {"error": str(error)}, 400
        finally:
            self.app.operation.release()
        if stream is not None:
            self.stream_chat(stream)
        else:
            self.json(result, status)

    def update_connections(self, body):
        if self.path == "/api/connections/rescan" and not body:
            self.app.scan_connections()
        elif self.path == "/api/connections/test" and body.keys() == {"provider"}:
            self.app.connections.test(body["provider"])
            self.app.connection_state = self.app.connections.report()
        elif self.path == "/api/connections/settings" and body.keys() == {"provider", "value"}:
            self.app.connections.save(body["provider"], body["value"])
            self.app.reload_agent(reset_brain=False)
        else:
            raise HearthError("Invalid connection request.")
        return self.app.connection_info()

    def update_brain(self, body):
        if body.keys() != {"provider", "model"}:
            raise HearthError("Invalid brain settings.")
        provider, model = body["provider"], body["model"]
        if self.path == "/api/brain/test":
            entry = self.app.connections.brain_entry(provider, model)
            return self.app.agent.test_brain(entry)
        self.app.connections.save_brain(provider, model)
        self.app.reload_agent()
        return self.app.brain_info()

    def stream_chat(self, events):
        try:
            self.response_headers(200, "text/event-stream")
            while True:
                try:
                    packet = events.get(timeout=12)
                except Empty:
                    self.wfile.write(b": Hearth is working\n\n")
                else:
                    if packet is None:
                        return
                    name, data = packet
                    self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode("utf-8"))
                self.wfile.flush()
        except OSError:
            # The worker still finishes and persists the reply if the browser disconnects.
            return


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
