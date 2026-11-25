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

from . import recall, router, search, timeline, voice, voice_call
from .agent import Agent, require_text
from .checkpoints import LocalCheckpoints, SpriteCheckpoints
from .connections import Connections, catalog_entry, validate_pool
from .connectors import Gateway, read_config
from .gateway_tools import redact_text, scrub
from .storage import HearthError, ROOT, Storage, iso
from .threads import MAIN, Threads, compact

STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/avatar.js": ("avatar.js", "text/javascript; charset=utf-8"),
    "/avatar-state.js": ("avatar-state.js", "text/javascript; charset=utf-8"),
    "/voice.js": ("voice.js", "text/javascript; charset=utf-8"),
    "/voice-call.js": ("voice-call.js", "text/javascript; charset=utf-8"),
    "/vendor/vocalbridge.mjs": ("vendor/vocalbridge.mjs", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/timeline.js": ("timeline.js", "text/javascript; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/icons/icon.svg": ("icons/icon.svg", "image/svg+xml"),
    "/icons/favicon.svg": ("icons/favicon.svg", "image/svg+xml"),
    "/icons/apple-touch-icon.png": ("icons/apple-touch-icon.png", "image/png"),
    "/icons/icon-512.png": ("icons/icon-512.png", "image/png"),
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
        self.activity = timeline.ActivityStream(
            storage.live, storage.state, self.threads.root, self.connections.path,
            *((checkpoints.root,) if checkpoints.mode == "local" else ()),
        )
        self.operation = threading.Lock()
        self.turn_lock = threading.Lock()
        self.turns = {}
        self.turn_activity = {}
        self.restore = None
        self.reindex = None
        self.call_check = None
        self.memory_index = recall.Recall(storage, self.gateway)
        self.reload_agent()

    def reload_agent(self, *, reset_brain=True):
        self.agent = Agent(self.storage, self.checkpoints, self.connections.active_config(), self.gateway, self.memory_index)
        if reset_brain:
            self.reset_brain_status()
        self.connection_state = self.connections.report()

    def reset_brain_status(self):
        agent = self.agent
        stats = agent.brain_stats.snapshot() if agent.brain_mode == "smart" else {}
        ordered, _ = router.order_models(agent.models, "quick", agent.brain_mode, stats)
        model = ordered[0]
        self.brain = model["provider"]
        self.brain_reply = (self.brain, model["model"])

    def scan_connections(self):
        if self.connections.scan():
            previous_models = self.agent.models
            if self.connections.active_config() != self.agent.config:
                self.reload_agent(reset_brain=False)
            if self.agent.models != previous_models:
                self.reset_brain_status()
        self.connection_state = self.connections.report()

    def connection_info(self):
        return {**self.connection_state, **self.brain_status()}

    def brain_status(self):
        provider, model = self.brain_reply
        if provider != self.brain:
            model = next((entry["model"] for entry in self.agent.models if entry["provider"] == self.brain), "")
        return {"model": self.brain, "model_id": model}

    def brain_info(self):
        agent = self.agent
        stats = agent.brain_stats.snapshot()
        preview = self.routing_preview(agent.brain_mode, agent.models, stats)
        return {**self.connections.brain_info(), **self.brain_status(), **preview,
                "scan_error": self.connections.scan_error}

    def routing_preview(self, mode, models, stats, prompt=None):
        plans = [self.agent.routing_plan(turn_type, mode, models, stats)[1] for turn_type in router.TURN_TYPES]
        result = {"mode": mode, "preview": plans, "stats": stats}
        if prompt is not None:
            result["test"] = self.agent.routing_plan(router.classify(prompt), mode, models, stats)[1]
        return result

    def memory_info(self):
        agent = self.agent
        return {"selection": agent.memory, "models": recall.MODELS, "folders": recall.FOLDERS,
                "available": self.memory_index.available(agent.config), "reindex": self.reindex}

    def search_info(self):
        agent = self.agent
        connected = search.connected(agent.config)
        return {"selection": agent.search_settings, "providers": [
            {"provider": provider, "name": catalog_entry(provider)["name"], "connected": provider in connected,
             "native_safe": provider in search.NATIVE_SAFE}
            for provider in search.PROVIDERS
        ], "active": [entry["provider"] for entry in search.candidates(agent.config, agent.search_settings)]}

    def reindex_running(self):
        return self.reindex is not None and self.reindex["status"] == "running"

    def start_reindex(self):
        if self.reindex_running():
            return self.reindex
        self.reindex = {"status": "running", "phase": "checkpoint", "total": 0, "embedded": 0, "reused": 0}
        threading.Thread(target=self.run_reindex, args=(self.agent,), daemon=True).start()
        return self.reindex

    def run_reindex(self, agent):
        def progress(**fields):
            self.reindex = {**self.reindex, **fields}

        try:
            checkpoint = agent.memory_sync_checkpoint("Before rebuilding Hearth memory")
            progress(phase="indexing", checkpoint=checkpoint)
            result = self.memory_index.run(agent.config, agent.memory, progress=progress, rebuild=True)
        except (HearthError, OSError):
            progress(status="failed", error="Hearth could not checkpoint and rebuild the index.")
        else:
            result.pop("results")
            progress(status="complete", **result)

    def chat_memory(self, thread_id, message_id):
        with self.storage.lock():
            if message_id in self.storage.load().get("forgotten_chat", []):
                raise HearthError("This message was forgotten from memory recall.")
            return self.find_chat_memory(thread_id, message_id)

    def find_chat_memory(self, thread_id, message_id):
        thread = self.threads.describe(thread_id)
        for line, message in enumerate(self.threads.messages(thread_id), 1):
            identity = message.get("id") or f"{thread_id}:{line}"
            if identity == message_id and message["role"] != "call":
                return recall.chunk(f"chat/{thread_id}", line, line, message["content"], thread["title"],
                                    thread_id=thread_id, message_id=identity)
        raise HearthError("That chat memory no longer exists.")

    def forget_memory(self, body):
        path = require_text(body.get("path"), 120)
        # The index takes its corpus snapshot under the same lock order.
        with self.memory_index.lock, self.storage.lock():
            if path.startswith("chat/"):
                thread_id = path.removeprefix("chat/")
                message_id = require_text(body.get("message_id"), 80)
                item = self.find_chat_memory(thread_id, message_id)
                removed = [item]
                state = self.storage.load()
                forgotten = state.setdefault("forgotten_chat", [])
                if message_id in forgotten:
                    raise HearthError("This chat memory is already forgotten.")
                checkpoint = self.checkpoints.create("Before forgetting a Hearth chat memory")
                forgotten.append(message_id)
                self.storage.save(state)
            else:
                content = self.storage.read(path)
                item_id = body.get("item_id")
                removed = [item for item in recall.note_chunks(path, content)
                           if item_id is None or item["id"] == item_id]
                if item_id is not None and not removed:
                    raise HearthError("This excerpt changed. Search again before forgetting it.")
                checkpoint = self.checkpoints.create("Before forgetting Hearth memory")
                if item_id is None:
                    self.storage.memory_path(path).unlink()
                else:
                    lines = content.splitlines(keepends=True)
                    item, = removed
                    del lines[item["line"] - 1:item["end_line"]]
                    self.storage.write(path, "".join(lines))
            self.memory_index.forget_vectors(removed)
            return self.agent.add_action("memory", "Memory forgotten", status="complete",
                                         checkpoint=checkpoint, paths=[path])

    def info(self, thread_id=MAIN):
        with self.turn_lock:
            active = {thread: self.turn_activity.get(thread) for thread in self.turns}
        with self.storage.lock():
            state = self.storage.load()
            threads = self.threads.list()
            if not any(thread["id"] == thread_id for thread in threads):
                thread_id = MAIN
            messages = self.threads.messages(thread_id)
        return {"thread_id": thread_id, "threads": [
                    {**thread, "busy": thread["id"] in active,
                     **({"activity": active[thread["id"]]} if active.get(thread["id"]) else {})}
                    for thread in threads],
                "messages": messages, "actions": list(state["actions"].values()),
                "jobs": state["jobs"], "reminders": state["reminders"], "routing": state.get("routing", [])[-50:],
                "whisper_available": bool(self.memory_index.hf_entry(self.agent.config)),
                "voice_call_available": voice_call.PROVIDER in self.connections.selected,
                "restore": self.restore,
                "checkpoints": self.checkpoints.mode, **self.brain_status()}

    def timeline(self):
        with self.storage.lock():
            actions = self.storage.load()["actions"].values()
            known = {action["checkpoint"]["id"]: {**action["checkpoint"],
                     "thread_id": action.get("thread_id", MAIN), "thread_title": action.get("thread_title", "Main")}
                     for action in actions if action.get("checkpoint")}
        return [known.get(item["id"], item) for item in self.checkpoints.list()]

    def timeline_info(self):
        entries = timeline.entries(self.storage, self.threads, self.agent.can_undo)
        represented = {row["data"]["checkpoint"]["id"] for row in entries
                       if row.get("action_id") and row["data"].get("checkpoint")}
        try:
            checkpoints = self.timeline()
        except HearthError as error:
            return {"entries": scrub(entries), "checkpoint_notice": str(error)}
        entries.extend(timeline.entry(
            "checkpoint", redact_text(item["comment"]), {**item, "thread_id": item.get("thread_id", ""),
                                                          "thread_title": item.get("thread_title", "Workspace")},
            id=f"checkpoint:{item['id']}", at=item["created_at"], data={"checkpoint": item},
        ) for item in checkpoints if item["id"] not in represented)
        return {"entries": scrub(entries)}

    def call_status(self):
        provider = voice_call.PROVIDER
        connection_id = self.connections.selected.get(provider)
        checks = []
        if self.connections.last_scan:
            status = "configured" if connection_id else "missing"
            checks.append({"at": self.connections.last_scan, "status": status, "kind": "discovery"})
        test = self.connections.checks.get(provider)
        if test and (at := self.connections.check_times.get(provider)):
            status, detail = test
            checks.append({"at": at, "status": status, "detail": detail, "kind": "authorization"})
        check = self.call_check
        if connection_id and check and check[0] == connection_id:
            checks.append(check[1])
        last = max(reversed(checks), key=lambda item: item["at"], default=None)
        return {"configured": bool(connection_id), "last_check": last,
                **({"participant_name": voice_call.participant_name(self.storage)} if connection_id else {})}

    def call_token(self):
        provider = voice_call.PROVIDER
        connection_id = self.connections.selected.get(provider)
        if not connection_id:
            raise voice.VoiceError(voice_call.SETUP, 409)
        connection = self.connections.gateway_entry(provider, connection_id)
        try:
            reply = voice_call.mint(self.gateway, connection, voice_call.participant_name(self.storage))
        except voice.VoiceError as error:
            self.call_check = (connection_id, {"at": iso(), "status": "failed", "kind": "token", "detail": str(error)})
            raise
        self.call_check = (connection_id, {"at": iso(), "status": "passed", "kind": "token"})
        return reply

    def enqueue(self, thread_id, prompt, *, source=None):
        command = SIDE_COMMAND.fullmatch(prompt) if thread_id == MAIN and source is None else None
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
                pending.append((prompt, events, source))
            else:
                self.turns[thread_id] = deque([(prompt, events, source)])
                threading.Thread(target=self.run_turns, args=(thread_id,), daemon=True).start()
        return events

    def run_turns(self, thread_id):
        while True:
            with self.turn_lock:
                prompt, events, source = self.turns[thread_id][0]
            agent = self.agent

            def event(name, data):
                phase = {"started": "thinking", "tool_started": "working", "tool_finished": "thinking",
                         "token": "thinking" if source == voice_call.SOURCE else "speaking",
                         "reset": "thinking"}.get(name)
                if phase:
                    with self.turn_lock:
                        self.turn_activity[thread_id] = {"pose": phase, "detail": data.get("title")}
                if name == "done" and self.agent is agent:
                    self.brain = data["provider"]
                    self.brain_reply = (self.brain, data["model"])
                if name == "error":
                    try:
                        timeline.record(self.storage, "tool", "Chat interrupted",
                                        {"thread_id": thread_id, "source": source},
                                        error=True, data={"detail": data["message"]})
                    except OSError:
                        pass
                events.put((name, data))

            try:
                agent.chat(prompt, event, thread_id, source=source)
            except Exception:
                event("error", {"message": "Hearth could not finish this turn. Check Timeline for any completed actions."})
            finally:
                with self.turn_lock:
                    pending = self.turns[thread_id]
                    pending.popleft()
                    self.turn_activity.pop(thread_id, None)
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
        if self.reindex_running():
            raise HearthError("Wait for memory reindexing to finish before restoring a checkpoint.")
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
                    self.reindex = None
                    self.call_check = None
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
                         "default-src 'self'; connect-src 'self' wss://*.livekit.cloud https://*.livekit.cloud; "
                         "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
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
            elif url.path == "/api/voice/call/status":
                self.json(self.app.call_status())
            elif url.path == "/api/brain":
                self.json(self.app.brain_info())
            elif url.path == "/api/brain/models":
                provider = parse_qs(url.query).get("provider", [None])[0]
                self.json(self.app.connections.brain_models(provider))
            elif url.path == "/api/checkpoints":
                self.json({"checkpoints": self.app.timeline()})
            elif url.path == "/api/timeline":
                self.json(self.app.timeline_info())
            elif url.path == "/api/timeline/events":
                origin = self.headers.get("Origin")
                if self.headers.get("Sec-Fetch-Site") not in (None, "none", "same-origin") or (
                    origin and not self.same_origin(origin)
                ):
                    raise HearthError("Open Timeline from Hearth.")
                with self.app.activity.subscribe() as events:
                    self.stream_events(events)
            elif url.path == "/api/memory/settings":
                self.json(self.app.memory_info())
            elif url.path == "/api/search/settings":
                self.json(self.app.search_info())
            elif url.path == "/api/memory/reindex":
                self.json({"reindex": self.app.reindex})
            elif url.path == "/api/memory/chat":
                params = parse_qs(url.query)
                thread = params.get("thread", [None])[0]
                message = params.get("message", [None])[0]
                self.json(self.app.chat_memory(thread, message))
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

    def body(self, limit=24_000):
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise HearthError("Send this request from Hearth.")
        if self.headers.get_content_type() != "application/json":
            raise HearthError("Expected a JSON request.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= limit:
                raise ValueError
            body = json.loads(self.rfile.read(length))
        except ValueError:
            raise HearthError("Invalid or oversized request.") from None
        if not isinstance(body, dict):
            raise HearthError("Expected a JSON object.")
        return body

    def do_POST(self):
        if self.path.startswith("/api/voice/call/"):
            self.post_call()
            return
        if urlsplit(self.path).path in {"/api/voice/transcribe", "/api/voice/redact"}:
            self.post_voice()
            return
        routes = {"/api/chat", "/api/approve", "/api/undo",
                  "/api/connections/rescan", "/api/connections/test", "/api/connections/settings",
                  "/api/brain/test", "/api/brain/settings", "/api/brain/route", "/api/threads/create", "/api/threads/rename",
                  "/api/threads/delete", "/api/threads/share", "/api/memory/settings", "/api/memory/test",
                  "/api/memory/search", "/api/memory/reindex", "/api/memory/forget",
                  "/api/search/settings", "/api/search/test"}
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
        if self.path == "/api/brain/route":
            try:
                self.json(self.update_brain(body))
            except HearthError as error:
                self.json({"error": str(error)}, 400)
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
                elif self.path.startswith(("/api/memory/", "/api/search/")):
                    result = self.update_preferences(body)
                else:
                    action_id = require_text(body.get("id"), 40)
                    if self.path == "/api/approve":
                        result = self.app.agent.approve(action_id)
                    else:
                        self.app.start_restore(action_id)
                        result, status = self.app.restore, 202
        except HearthError as error:
            result, status = {"error": str(error)}, 400
        except OSError:
            result, status = {"error": "Hearth could not update workspace data."}, 500
        finally:
            self.app.operation.release()
        if stream is not None:
            self.stream_chat(stream)
        else:
            self.json(result, status)

    def post_call(self):
        operation = self.path.removeprefix("/api/voice/call/")
        if operation not in ("token", "query", "report"):
            self.json({"error": "Page not found."}, 404)
            return
        try:
            origin = self.headers.get("Origin")
            fetch_site = self.headers.get("Sec-Fetch-Site")
            if fetch_site not in (None, "none", "same-origin") or (origin and not self.same_origin(origin)):
                raise voice.VoiceError("Send this request from Hearth.", 403)
            body = self.body(voice_call.MAX_REPORT_BYTES if operation == "report" else 24_000)
            if operation == "token":
                if body:
                    raise HearthError("Invalid call token request.")
                result = self.app.call_token()
            else:
                with self.app.operation:
                    if self.app.restore and self.app.restore["status"] == "restoring":
                        raise voice.VoiceError("A checkpoint is being restored.", 409)
                    if operation == "report":
                        result = voice_call.save_report(self.app.threads, body)
                    else:
                        if body.keys() != {"thread_id", "query"}:
                            raise HearthError("Invalid call query.")
                        events = self.app.enqueue(body["thread_id"], require_text(body["query"], 4_000),
                                                  source=voice_call.SOURCE)
                if operation == "query":
                    result = self.call_reply(events)
        except voice.VoiceError as error:
            self.json({"error": str(error)}, error.status)
        except HearthError as error:
            self.json({"error": str(error)}, 400)
        except OSError:
            self.json({"error": "Hearth could not update workspace data."}, 500)
        else:
            self.json(result)

    def same_origin(self, origin):
        try:
            parts = urlsplit(origin)
        except ValueError:
            return False
        scheme = self.headers.get("X-Forwarded-Proto", "http")
        return (parts.scheme in ("http", "https") and parts.scheme == scheme
                and bool(parts.netloc) and parts.netloc.lower() == self.headers.get("Host", "").lower()
                and not (parts.path or parts.query or parts.fragment or parts.username or parts.password))

    @staticmethod
    def call_reply(events):
        deadline = time.monotonic() + 115
        try:
            while (remaining := deadline - time.monotonic()) > 0:
                packet = events.get(timeout=remaining)
                if packet is None or packet[0] == "error":
                    raise voice.VoiceError("Hearth could not answer. Check Timeline for any completed actions.", 502)
                if packet[0] == "done":
                    return {"reply": packet[1]["message"]["content"]}
        except Empty:
            pass
        raise voice.VoiceError("Hearth is still working. Check the thread for the reply.", 504)

    def post_voice(self):
        url = urlsplit(self.path)
        params = parse_qs(url.query)
        thread_id = params.get("thread", [None])[0]
        whisper = url.path == "/api/voice/transcribe"
        try:
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise voice.VoiceError("Send this request from Hearth.", 403)
            if not whisper:
                body = self.body()
                text = voice.clean_transcript(require_text(body.get("text"), 4000))
            else:
                content_type = self.headers.get_content_type()
                if content_type not in voice.AUDIO_TYPES:
                    raise voice.VoiceError("Use a WebM, Ogg, MP4, or WAV audio recording.", 415)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if length > voice.MAX_AUDIO:
                    raise voice.VoiceError("The recording exceeds the 8 MiB limit.", 413)
                if length <= 0:
                    raise voice.VoiceError("No audio recording was received.")
                connection = self.app.memory_index.hf_entry(self.app.agent.config)
                language = params.get("language", ["auto"])[0]
                self.connection.settimeout(15)
                try:
                    data = self.rfile.read(length)
                except TimeoutError:
                    raise voice.VoiceError("The audio upload timed out.", 408) from None
                if len(data) != length:
                    raise voice.VoiceError("The audio upload was interrupted.")
                text = voice.transcribe(self.app.gateway, connection, data, content_type, language)
        except voice.VoiceError as error:
            self.json({"error": str(error)}, error.status)
        except HearthError as error:
            self.json({"error": str(error)}, 400)
        else:
            if thread_id is not None:
                try:
                    with self.app.storage.lock():
                        thread = self.app.threads.describe(thread_id)
                    timeline.record(self.app.storage, "voice", "Voice input transcribed",
                                    {"thread_id": thread["id"], "thread_title": thread["title"]},
                                    provider="huggingface" if whisper else None,
                                    data={"engine": "Whisper" if whisper else "Browser"})
                except (HearthError, OSError):
                    # Dictation still returns text if its chat was removed or logging failed.
                    pass
            self.json({"text": text})

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
        operation = self.path.rsplit("/", 1)[-1]
        allowed = {"provider", "model", "pool"}
        if operation == "route":
            allowed.add("prompt")
        if body.keys() - allowed or not {"provider", "model"} <= body.keys():
            raise HearthError("Invalid brain settings.")
        connections = self.app.connections
        selection = connections.brain_selection(body["provider"], body["model"])
        pool = validate_pool(body["pool"]) if "pool" in body else None
        if operation == "settings":
            connections.save_brain(selection, pool)
            self.app.reload_agent()
            return self.app.brain_info()
        agent = self.app.agent
        mode, models, _ = router.setup(agent.config, selection, pool)
        stats = agent.brain_stats.snapshot()
        if operation == "test":
            ordered, _ = router.order_models(models, "quick", mode, stats)
            return agent.test_brain(ordered[0])
        prompt = require_text(body["prompt"], 4_000) if "prompt" in body else None
        return self.app.routing_preview(mode, models, stats, prompt)

    def update_preferences(self, body):
        _, _, feature, operation = self.path.split("/")
        agent = self.app.agent
        if feature == "memory":
            if operation == "search":
                if body.keys() != {"query"}:
                    raise HearthError("Enter a memory query.")
                if self.app.reindex_running():
                    raise HearthError("Wait for memory reindexing to finish, then try your query.")
                return agent.memory_search(body["query"])
            if operation == "reindex" and not body:
                return self.app.start_reindex()
            if operation == "forget":
                if self.app.reindex_running():
                    raise HearthError("Wait for memory reindexing to finish before forgetting a memory.")
                return self.app.forget_memory(body)
        if operation == "test" and body.keys() == {"selection", "query"}:
            if feature == "search":
                return agent.run_search(body["query"], search.settings(body["selection"]))
            if self.app.reindex_running():
                raise HearthError("Wait for memory reindexing to finish, then test recall.")
            query = redact_text(require_text(body["query"], 1_000))
            return self.app.memory_index.run(agent.config, recall.settings(body["selection"]), query,
                                             checkpoint=agent.memory_sync_checkpoint)
        if operation == "settings":
            if feature == "memory" and self.app.reindex_running():
                raise HearthError("Wait for memory reindexing to finish before saving settings.")
            selection = (recall if feature == "memory" else search).settings(body)
            self.app.connections.save_preferences(feature, selection)
            self.app.reload_agent(reset_brain=False)
            return self.app.memory_info() if feature == "memory" else self.app.search_info()
        raise HearthError("Invalid settings request.")

    def stream_chat(self, events):
        def packets():
            while True:
                try:
                    packet = events.get(timeout=12)
                except Empty:
                    yield None
                else:
                    if packet is None:
                        return
                    yield packet

        self.stream_events(packets())

    def stream_events(self, packets):
        try:
            self.response_headers(200, "text/event-stream")
            self.wfile.flush()
            for packet in packets:
                if packet is None:
                    self.wfile.write(b": Hearth is working\n\n")
                else:
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
