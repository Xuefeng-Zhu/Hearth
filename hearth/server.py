import argparse
import json
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, SimpleQueue
from urllib.parse import parse_qs, urlsplit

from . import artifacts, box, inbox, memory_edits, recall, reminders, router, scheduler, search, timeline, voice, voice_call
from .agent import Agent, require_text
from .checkpoints import LocalCheckpoints, SpriteCheckpoints
from .connections import Connections, catalog_entry, validate_pool
from .connectors import Gateway, read_config
from .gateway_tools import redact_text, scrub
from .memory_sync import MemorySync
from .reminder_config import equal
from .storage import HearthError, ROOT, Storage, iso
from .threads import MAIN, Threads, compact

STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/reminders.js": ("reminders.js", "text/javascript; charset=utf-8"),
    "/reminder-action": ("reminder-action.html", "text/html; charset=utf-8"),
    "/reminder-action.js": ("reminder-action.js", "text/javascript; charset=utf-8"),
    "/avatar.js": ("avatar.js", "text/javascript; charset=utf-8"),
    "/avatar-state.js": ("avatar-state.js", "text/javascript; charset=utf-8"),
    "/voice.js": ("voice.js", "text/javascript; charset=utf-8"),
    "/voice-call.js": ("voice-call.js", "text/javascript; charset=utf-8"),
    "/vendor/vocalbridge.mjs": ("vendor/vocalbridge.mjs", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/timeline.js": ("timeline.js", "text/javascript; charset=utf-8"),
    "/artifacts.js": ("artifacts.js", "text/javascript; charset=utf-8"),
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
        self.operation = threading.RLock()
        self.artifacts = artifacts.Artifacts(storage, self.threads, self.connections, self.operation)
        self.turn_lock = threading.Lock()
        self.turns = {}
        self.turn_activity = {}
        self.restore = None
        self.reindex = None
        self.call_check = None
        self.memory_index = recall.Recall(storage, self.gateway)
        self.reload_agent()
        self.memory_sync = MemorySync(self)
        self.memory_index.on_change = self.memory_sync.request
        self.artifacts.on_memory_change = self.memory_sync.request
        self.reminders = reminders.Reminders(self)
        self.inbox = inbox.Inbox(self)

    def scheduler_tick(self):
        fired = scheduler.run_due(self.storage, tick=True)
        self.reminders.deliver(wait=True)
        polled = self.inbox.poll(force=True)
        info = self.reminders.info()
        return {"fired": fired, "processed": polled, "last_tick": info["last_tick"], "next_due": info["next_due"]}

    def background_reminders(self):
        previous = None
        while True:
            now = time.time()
            woke = previous is None or now - previous > 20
            try:
                if not self.restore or self.restore["status"] != "restoring":
                    scheduler.run_due(self.storage, tick=woke)
                    if woke:
                        threading.Thread(target=self.inbox.poll, kwargs={"force": True}, daemon=True).start()
                    self.reminders.deliver()
            except (HearthError, OSError):
                pass
            previous = time.time()
            time.sleep(2)

    def reload_agent(self, *, reset_brain=True):
        self.agent = Agent(self.storage, self.checkpoints, self.connections.active_config(), self.gateway,
                           self.memory_index, self.artifacts)
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

    def scan_connections(self, *, sync_memory=False):
        previous_target = self.memory_index.target(self.agent.config)
        if self.connections.scan():
            previous_models = self.agent.models
            if self.connections.active_config() != self.agent.config:
                self.reload_agent(reset_brain=False)
            if self.agent.models != previous_models:
                self.reset_brain_status()
            if sync_memory and previous_target != self.memory_index.target(self.agent.config):
                self.memory_sync.request("startup")
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
                "available": self.memory_index.available(agent.config), "kinds": recall.KINDS,
                **self.memory_sync_info()}

    def memory_sync_info(self):
        return {"reindex": self.reindex, "sync": self.memory_sync.job,
                "pinecone": self.memory_index.pinecone_status(self.agent.config)}

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
            if identity == message_id:
                return recall.chunk(f"chat/{thread_id}", line, line, recall.chat_text(message), thread["title"],
                                    thread_id=thread_id, message_id=identity)
        raise HearthError("That chat memory no longer exists.")

    def forget_memory(self, body):
        path = require_text(body.get("path"), 120)
        # The index takes its corpus snapshot under the same lock order.
        with self.memory_index.lock, self.storage.lock():
            state = self.storage.load()
            message_id = None
            if path.startswith("chat/"):
                thread_id = path.removeprefix("chat/")
                message_id = require_text(body.get("message_id"), 80)
                item = self.find_chat_memory(thread_id, message_id)
                removed = [item]
                before = memory_edits.snapshot(self.storage, state, message_id=message_id)
                forgotten = state.setdefault("forgotten_chat", [])
                if message_id in forgotten:
                    raise HearthError("This chat memory is already forgotten.")
                checkpoint = self.checkpoints.create("Before forgetting a Hearth chat memory")
                forgotten.append(message_id)
                self.storage.save(state)
            else:
                content = self.storage.read(path)
                before = memory_edits.snapshot(self.storage, state, [path])
                item_id = body.get("item_id")
                removed = [item for item in recall.note_chunks(path, redact_text(content))
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
                                         checkpoint=checkpoint, paths=[path], memory_before=before,
                                         forgotten_id=message_id)

    def info(self, thread_id=MAIN):
        with self.turn_lock:
            active = {thread: self.turn_activity.get(thread) for thread in self.turns}
        with self.storage.lock():
            state = self.storage.load()
            threads = self.threads.list()
            if not any(thread["id"] == thread_id for thread in threads):
                thread_id = MAIN
            messages = self.threads.messages(thread_id)
        jobs = {job["id"]: job for job in state["jobs"]}
        actions = []
        for action in state["actions"].values():
            if (job := jobs.get(action.get("job", {}).get("id"))) is not None:
                action = {**action, "job": {**job, "cancelable": reminders.can_cancel(state, job)}}
            actions.append(action)
        recent = datetime.now(timezone.utc) - timedelta(seconds=4)
        sending = set()
        for item in scheduler.email_records(state):
            email = item.get("delivery", {}).get("email", {})
            if email.get("sending") or (email.get("at") and datetime.fromisoformat(email["at"]) > recent):
                sending.add(item["thread_id"])
        return {"thread_id": thread_id, "threads": [
                    {**thread, "busy": thread["id"] in active,
                     **({"activity": active[thread["id"]]} if active.get(thread["id"]) else {})}
                    for thread in threads],
                "messages": messages, "actions": actions,
                "message_artifacts": artifacts.message_artifacts(state, thread_id),
                "jobs": state["jobs"], "reminders": [reminders.public_item(item) for item in state["reminders"]],
                "reminder_sending": sorted(sending),
                "routing": state.get("routing", [])[-50:],
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
                         "reset": "thinking", "remembered": "remembering"}.get(name)
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
                thread = self.threads.rename(thread_id, title)
                if self.agent.memory["include_chat"]:
                    self.memory_sync.request()
                return thread
            if operation == "delete" and body.keys() == {"thread_id"}:
                thread = self.threads.describe(thread_id)
                try:
                    checkpoint = self.checkpoints.create("Before deleting a Hearth side chat")
                    self.threads.delete(thread_id)
                    if self.agent.memory["include_chat"]:
                        self.memory_sync.request()
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
                message = self.threads.append(MAIN, "user", text, shared_from=thread_id)
                if self.agent.memory["include_chat"]:
                    self.memory_sync.request()
                return message
        raise HearthError("Invalid chat request.")

    def replay_memory(self, action_id, *, redo=False):
        action = memory_edits.restore(self.storage, action_id, redo=redo)
        self.memory_sync.request()
        return action

    def undo_action(self, action_id):
        with self.storage.lock():
            action = self.storage.load()["actions"].get(action_id)
        if action and action["kind"] == "reminder":
            return self.reminders.cancel(action["job"]["id"]), 200
        if action and action.get("memory_change"):
            return self.replay_memory(action_id), 200
        self.start_restore(action_id)
        return self.restore, 202

    def start_restore(self, action_id):
        if self.reindex_running() or self.memory_sync.running:
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
                    selected = self.connections.selected
                    self.connections.reset()
                    self.connections.selected = selected
                    self.reindex = None
                    self.call_check = None
                    self.reload_agent()
                    self.restore = None
                    self.memory_sync.request("startup")
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

    def response_headers(self, status, content_type, length=None, *, email_preview=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; connect-src 'self' wss://*.livekit.cloud https://*.livekit.cloud; "
                         "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
                         + ("; style-src 'unsafe-inline'; script-src 'none'" if email_preview else ""))
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
            elif url.path == "/api/reminders/settings":
                self.json(self.app.reminders.info())
            elif url.path == "/api/reminders":
                self.json(self.app.reminders.list())
            elif url.path == "/api/inbox":
                self.json(self.app.inbox.list())
            elif url.path == "/api/reminders/outbox":
                identity = parse_qs(url.query).get("id", [""])[0]
                email = self.app.reminders.outbox(identity)
                body = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                        '<meta name="viewport" content="width=device-width,initial-scale=1">'
                        '<title>Hearth reminder email</title></head><body style="margin:0">'
                        + email["html"] + "</body></html>").encode("utf-8")
                self.response_headers(200, "text/html; charset=utf-8", len(body), email_preview=True)
                self.wfile.write(body)
            elif url.path == "/api/artifacts":
                self.json(self.app.artifacts.list())
            elif url.path == "/api/artifacts/settings":
                self.json(self.app.artifacts.info())
            elif url.path == "/api/artifacts/detail":
                identity = parse_qs(url.query).get("id", [None])[0]
                self.json(self.app.artifacts.detail(identity))
            elif url.path == "/api/memory/reindex":
                self.json(self.app.memory_sync_info())
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
        except OSError:
            self.json({"error": "Hearth could not read workspace data."}, 500)

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
        if self.path == "/api/scheduler/tick":
            if not equal(self.headers.get("X-Hearth-Tick-Token"), self.app.reminders.tick_token):
                self.json({"error": "Scheduler token required."}, 401)
            elif self.app.restore and self.app.restore["status"] == "restoring":
                self.json({"error": "A checkpoint is being restored."}, 409)
            else:
                try:
                    self.json(self.app.scheduler_tick())
                except (HearthError, OSError):
                    self.json({"error": "Hearth could not run the scheduler tick."}, 500)
            return
        if self.path.startswith(("/api/reminders/", "/api/inbox/")):
            self.post_reminders()
            return
        if self.path.startswith("/api/artifacts/"):
            self.post_artifact()
            return
        if self.path.startswith("/api/voice/call/"):
            self.post_call()
            return
        if urlsplit(self.path).path in {"/api/voice/transcribe", "/api/voice/redact"}:
            self.post_voice()
            return
        routes = {"/api/chat", "/api/approve", "/api/undo", "/api/redo",
                  "/api/connections/rescan", "/api/connections/test", "/api/connections/settings",
                  "/api/brain/test", "/api/brain/settings", "/api/brain/route", "/api/threads/create", "/api/threads/rename",
                  "/api/threads/delete", "/api/threads/share", "/api/memory/settings", "/api/memory/test",
                  "/api/memory/search", "/api/memory/reindex", "/api/memory/sync", "/api/memory/forget",
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
                    elif self.path == "/api/redo":
                        result = self.app.replay_memory(action_id, redo=True)
                    else:
                        result, status = self.app.undo_action(action_id)
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

    def post_reminders(self):
        try:
            origin = self.headers.get("Origin")
            if self.headers.get("Sec-Fetch-Site") not in (None, "none", "same-origin") or (
                origin and not self.same_origin(origin)
            ):
                raise HearthError("Send this request from Hearth.")
            body = self.body()
            if self.app.restore and self.app.restore["status"] == "restoring":
                self.json({"error": "A checkpoint is being restored."}, 409)
                return
            operation = self.path.rsplit("/", 1)[-1]
            if self.path.startswith("/api/inbox/"):
                if operation == "poll" and not body:
                    result = {"processed": self.app.inbox.poll()}
                elif operation in {"accept", "edit", "dismiss", "undo"}:
                    result = self.app.inbox.update(operation, body)
                else:
                    raise HearthError("Invalid inbox request.")
            elif operation == "settings":
                result = self.app.reminders.save(body)
            elif operation == "test":
                result = self.app.reminders.test(body.get("channel"))
            elif operation in ("inspect", "action") and body.keys() == {"token"}:
                result = self.app.reminders.use_token(body["token"], apply=operation == "action")
            elif operation == "cancel":
                result = self.app.reminders.cancel(body.get("id"))
            elif operation == "create":
                allowed = {"message", "at", "cron", "note", "channel", "urgent"}
                if "message" not in body or not body.keys() <= allowed:
                    raise HearthError("Enter a reminder title and a time.")
                with self.app.storage.lock():
                    state = self.app.storage.load()
                    result = scheduler.add_job(state, **body)
                    self.app.storage.save(state)
            else:
                raise HearthError("Invalid reminder request.")
            self.json(result)
        except HearthError as error:
            self.json({"error": str(error)}, 400)
        except OSError:
            self.json({"error": "Hearth could not update workspace data."}, 500)

    def post_artifact(self):
        operation = self.path.removeprefix("/api/artifacts/")
        if operation not in {"settings", "create", "save-message", "update", "retry", "delete", "undo"}:
            self.json({"error": "Page not found."}, 404)
            return
        origin = self.headers.get("Origin")
        if self.headers.get("Sec-Fetch-Site") not in (None, "none", "same-origin") or (
            origin and not self.same_origin(origin)
        ):
            self.json({"error": "Send this request from Hearth."}, 403)
            return
        try:
            self.connection.settimeout(15)
            body = self.body(8 * box.MAX_BYTES)
            with self.app.operation:
                if self.app.restore and self.app.restore["status"] == "restoring":
                    self.json({"error": "A checkpoint is being restored."}, 409)
                    return
                result = self.update_artifacts(operation, body)
        except HearthError as error:
            self.json({"error": str(error)}, 400)
        except TimeoutError:
            self.json({"error": "The request timed out."}, 408)
        except OSError:
            self.json({"error": "Hearth could not update workspace data."}, 500)
        else:
            self.json(result, 201 if operation in {"create", "save-message"} else 200)

    def update_artifacts(self, operation, body):
        service = self.app.artifacts
        if operation == "settings":
            self.app.connections.save_preferences("artifacts", box.settings(body))
            self.app.reload_agent(reset_brain=False)
            self.app.memory_sync.request("startup")
            return service.info()
        if operation == "save-message" and body.keys() == {"thread_id", "message_id"}:
            return service.save_message(body["thread_id"], require_text(body["message_id"], 90))
        if operation == "undo" and body.keys() == {"id"}:
            return service.undo(require_text(body["id"], 40))
        if operation == "create" and {"title", "content"} <= body.keys() <= {"title", "content", "kind", "format", "thread_id"}:
            thread_id = body.pop("thread_id", None)
            origin = None
            if thread_id is not None:
                with self.app.storage.lock():
                    thread = self.app.threads.describe(thread_id)
                origin = {"thread_id": thread["id"], "thread_title": thread["title"]}
            return service.create(**body, origin=origin)
        return service.mutate(operation, body)

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
                        if self.app.agent.memory["include_chat"]:
                            self.app.memory_sync.request()
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
            self.app.scan_connections(sync_memory=True)
        elif self.path == "/api/connections/test" and body.keys() == {"provider"}:
            self.app.connections.test(body["provider"])
            self.app.connection_state = self.app.connections.report()
        elif self.path == "/api/connections/settings" and body.keys() == {"provider", "value"}:
            previous = self.app.memory_index.target(self.app.agent.config)
            self.app.connections.save(body["provider"], body["value"])
            self.app.reload_agent(reset_brain=False)
            if previous != self.app.memory_index.target(self.app.agent.config):
                self.app.memory_sync.request("startup")
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
            if operation == "search" and "query" in body and body.keys() <= {"query", "kind", "thread_id"}:
                return agent.memory_search(**body)
            if operation == "sync" and not body:
                return self.app.memory_sync.request("sync")
            if operation == "reindex" and not body:
                if self.app.memory_index.available(agent.config)["pinecone"]:
                    return self.app.memory_sync.request("rebuild")
                return self.app.start_reindex()
            if operation == "forget":
                return self.app.forget_memory(body)
        if operation == "test" and {"selection", "query"} <= body.keys():
            if feature == "search" and body.keys() == {"selection", "query"}:
                return agent.run_search(body["query"], search.settings(body["selection"]))
            if feature == "memory" and body.keys() <= {"selection", "query", "kind", "thread_id"}:
                query = redact_text(require_text(body["query"], 1_000))
                filters = {key: body[key] for key in ("kind", "thread_id") if key in body}
                return self.app.memory_index.run(agent.config, recall.settings(body["selection"]), query,
                                                 filters=filters, budget=10)
        if operation == "settings":
            if feature == "memory" and self.app.reindex_running():
                raise HearthError("Wait for memory reindexing to finish before saving settings.")
            selection = (recall if feature == "memory" else search).settings(body)
            self.app.connections.save_preferences(feature, selection)
            self.app.reload_agent(reset_brain=False)
            if feature == "memory":
                self.app.memory_sync.request()
                return self.app.memory_info()
            return self.app.search_info()
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
    app.scan_connections(sync_memory=True)
    with HTTPServer((args.host, args.port), app) as server:
        threading.Thread(target=app.background_reminders, daemon=True).start()
        server.serve_forever()


if __name__ == "__main__":
    main()
