import argparse
import json
import os
import re
import shutil
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, SimpleQueue
from urllib.parse import parse_qs, quote, urlsplit

from . import approvals, artifacts, box, browserbase, event_automations, feed, home, inbox, memory, memory_edits, memory_purge, memory_review, page_policy, pages, proactivity, proactive_context, recall, reminders, router, scheduler, search, skills, tasks, timeline, uploads, voice, voice_call, workers
from . import file_questions, goals, ideas
from .agent import Agent, require_text
from .checkpoints import LocalCheckpoints, SpriteCheckpoints
from .connections import Connections, catalog_entry, validate_pool
from .connectors import Gateway, read_config
from .gateway_tools import redact_text, scrub
from .memory_sync import MemorySync
from .reminder_config import equal, saved
from .storage import HearthError, ROOT, Storage, iso, new_id
from .threads import MAIN, Threads, compact


class ChatStopped(Exception):
    pass


@dataclass
class ReplyControl:
    id: str = field(default_factory=new_id)
    stopped: threading.Event = field(default_factory=threading.Event)
    message_id: str | None = None
    committing: bool = False

    def check(self):
        if self.stopped.is_set():
            raise ChatStopped

STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/memory.js": ("memory.js", "text/javascript; charset=utf-8"),
    "/memory-review.js": ("memory-review.js", "text/javascript; charset=utf-8"),
    "/memory.css": ("memory.css", "text/css; charset=utf-8"),
    "/feed.js": ("feed.js", "text/javascript; charset=utf-8"),
    "/proactivity.js": ("proactivity.js", "text/javascript; charset=utf-8"),
    "/goals.js": ("goals.js", "text/javascript; charset=utf-8"),
    "/home.js": ("home.js", "text/javascript; charset=utf-8"),
    "/home.css": ("home.css", "text/css; charset=utf-8"),
    "/workers.js": ("workers.js", "text/javascript; charset=utf-8"),
    "/workers.css": ("workers.css", "text/css; charset=utf-8"),
    "/pages.js": ("pages.js", "text/javascript; charset=utf-8"),
    "/pages.css": ("pages.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/mobile.js": ("mobile.js", "text/javascript; charset=utf-8"),
    "/dom.js": ("dom.js", "text/javascript; charset=utf-8"),
    "/icons.js": ("icons.js", "text/javascript; charset=utf-8"),
    "/time.js": ("time.js", "text/javascript; charset=utf-8"),
    "/attachments.js": ("attachments.js", "text/javascript; charset=utf-8"),
    "/reminders.js": ("reminders.js", "text/javascript; charset=utf-8"),
    "/automation.js": ("automation.js", "text/javascript; charset=utf-8"),
    "/automation.css": ("automation.css", "text/css; charset=utf-8"),
    "/skills.js": ("skills.js", "text/javascript; charset=utf-8"),
    "/skills.css": ("skills.css", "text/css; charset=utf-8"),
    "/reminder-action": ("reminder-action.html", "text/html; charset=utf-8"),
    "/reminder-action.js": ("reminder-action.js", "text/javascript; charset=utf-8"),
    "/avatar.js": ("avatar.js", "text/javascript; charset=utf-8"),
    "/avatar-state.js": ("avatar-state.js", "text/javascript; charset=utf-8"),
    "/voice.js": ("voice.js", "text/javascript; charset=utf-8"),
    "/voice-call.js": ("voice-call.js", "text/javascript; charset=utf-8"),
    "/vendor/vocalbridge.mjs": ("vendor/vocalbridge.mjs", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/mobile.css": ("mobile.css", "text/css; charset=utf-8"),
    "/theme.css": ("theme.css", "text/css; charset=utf-8"),
    "/timeline.js": ("timeline.js", "text/javascript; charset=utf-8"),
    "/artifacts.js": ("artifacts.js", "text/javascript; charset=utf-8"),
    "/file-questions.js": ("file-questions.js", "text/javascript; charset=utf-8"),
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
        self.workers = workers.Pool(storage)
        self.workers.recover()
        self.browser_slots = browserbase.SessionSlots()
        self.artifacts = artifacts.Artifacts(storage, self.connections, self.operation)
        self.uploads = uploads.Uploads(self)
        self.pages = pages.Pages(storage, self.artifacts, self.operation,
                                 share_config=os.environ.get("HEARTH_SHARE_CONFIG"),
                                 private_edge=checkpoints.mode == "sprite")
        self.turn_lock = threading.Lock()
        self.turns = {}
        self.turn_activity = {}
        self.restore = None
        self.artifacts.restoring = self.restoring
        self.reindex = None
        self.call_check = None
        self.memory_index = recall.Recall(storage, self.gateway)
        self.reload_agent()
        self.memory_sync = MemorySync(self)
        self.memory_index.on_change = self.memory_sync.request
        self.artifacts.on_memory_change = self.memory_sync.request
        self.reminders = reminders.Reminders(self)
        self.inbox = inbox.Inbox(self)
        self.home = home.Home(self)
        self.proactivity = proactivity.Proactivity(self)
        self.feed = feed.Feed(self)
        self.ideas = ideas.Ideas(self)
        self.memory_review = memory_review.MemoryReview(self)
        self.task_runner = tasks.Runner(self)
        self.event_runner = event_automations.Runner(self)
        approvals.upgrade_legacy(self.agent)

    def scheduler_tick(self):
        fired = scheduler.run_due(self.storage, tick=True)
        self.reminders.deliver(wait=True)
        polled = self.inbox.poll(force=True)
        self.proactivity.kick()
        self.feed.kick()
        self.ideas.kick()
        self.memory_review.kick()
        task_runs = self.task_runner.tick()
        self.event_runner.kick()
        info = self.reminders.info()
        return {"fired": fired, "processed": polled, "last_tick": info["last_tick"], "next_due": info["next_due"],
                "panels_refreshed": self.home.run_due(), "task_runs": task_runs}

    def restoring(self):
        return bool(self.restore and self.restore["status"] == "restoring")

    def background_reminders(self):
        previous = None
        next_home = 0
        next_inbox = 0
        while True:
            now = time.time()
            woke = previous is None or now - previous > 20
            try:
                if not self.restore or self.restore["status"] != "restoring":
                    scheduler.run_due(self.storage, tick=woke)
                    if woke or now >= next_inbox:
                        threading.Thread(target=self.inbox.poll, kwargs={"force": woke}, daemon=True).start()
                        next_inbox = now + 60
                    self.reminders.deliver()
                    self.task_runner.kick()
                    self.event_runner.kick()
                    if woke or now >= next_home:
                        self.home.kick()
                        self.proactivity.kick()
                        self.feed.kick()
                        self.ideas.kick()
                        self.memory_review.kick()
                        next_home = now + 10
            except (HearthError, OSError):
                pass
            previous = time.time()
            time.sleep(2)

    def reload_agent(self, *, reset_brain=True):
        self.agent = Agent(self.storage, self.checkpoints, self.connections.active_config(), self.gateway,
                           self.memory_index, self.artifacts, self.uploads, self.pages,
                           worker_pool=self.workers, browser_slots=self.browser_slots)
        self.workers.configure(self.agent.config.get("parallel_workers", workers.DEFAULT_CAP))
        self.agent.application = self
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
            if sync_memory:
                status = self.memory_index.pinecone_status(self.agent.config)
                if (previous_target != self.memory_index.target(self.agent.config)
                        or (status["state"] != "Ready" and not self.memory_sync.running)):
                    self.memory_sync.request("startup")
        self.connection_state = self.connections.report()

    def connection_info(self, pinecone=None):
        if pinecone is None:
            pinecone = self.memory_index.pinecone_status(self.agent.config)
        report = {**self.connection_state, **self.brain_status()}
        if pinecone["connected"]:
            providers = report["providers"]
            entry = {**providers["pinecone"], "index_state": pinecone["state"],
                     "index_error": pinecone.get("error")}
            report["providers"] = {**providers, "pinecone": entry}
        return report

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
        ], "active": [entry["provider"] for entry in search.candidates(agent.config, agent.search_settings)],
            "browsing": agent.browsing}

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

    def purge_memory(self, matches, message_id):
        return memory_purge.purge(self, matches, message_id)

    def forget_memory(self, body):
        path = require_text(body.get("path"), 120)
        if path in memory.PINNED and body.get("item_id") is None:
            raise HearthError("Edit the profile or approval preferences in their settings.")
        # Keep index updates and workspace writes in the same lock order.
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
                if "revision" in body and body["revision"] != memory.revision(content):
                    raise HearthError("The note changed. Reload it before deleting.")
                item_id = body.get("item_id")
                changes = memory.related_changes(self.storage, path) if item_id is None else {}
                before = memory_edits.snapshot(self.storage, state, [path, *changes])
                removed = [item for item in recall.section_chunks(path, redact_text(content))
                           if item_id is None or item["id"] == item_id]
                if item_id is not None and not removed:
                    raise HearthError("This excerpt changed. Search again before forgetting it.")
                if path == memory.APPROVAL_NOTE or any(item.get("profile_fields") for item in removed) and item_id:
                    raise HearthError("Edit these fields directly in the profile or approval settings.")
                checkpoint = self.checkpoints.create("Before forgetting Hearth memory")
                if item_id is None:
                    memory_edits.write_notes(self.storage, {path: None, **changes})
                else:
                    lines = content.splitlines(keepends=True)
                    item, = removed
                    del lines[item["line"] - 1:item["end_line"]]
                    self.storage.write(path, "".join(lines))
                memory.catalog(self.storage)
            self.memory_index.forget_vectors(removed)
            self.memory_index.clear_sources()
            self.uploads.clear_extractions()
            action = self.agent.add_action("memory", "Memory forgotten", status="complete",
                                           checkpoint=checkpoint, paths=[path], memory_before=before,
                                           forgotten_id=message_id)
            state = self.storage.load()
            proactive_context.record_forget(state, action["id"], removed)
            self.storage.save(state)
            return action

    def info(self, thread_id=MAIN):
        with self.turn_lock:
            active = {thread: self.turn_activity.get(thread) for thread in self.turns}
        with self.storage.lock():
            state = self.storage.load()
            threads = self.threads.list()
            for thread in threads:
                legacy = state.get("messages", []) if thread["id"] == MAIN else ()
                thread["last_reply"] = self.threads.last_reply(thread["id"], legacy)
            if not any(thread["id"] == thread_id for thread in threads):
                thread_id = MAIN
            if approvals.expire(state, datetime.now(timezone.utc)):
                self.storage.save(state)
            messages = self.threads.messages(thread_id)
            message_uploads = self.uploads.for_messages(thread_id, messages)
        jobs = {job["id"]: job for job in state["jobs"]}
        actions = []
        for action in state["actions"].values():
            if action["kind"] == "skill":
                action = {**action, "undoable": skills.can_undo(state, action)}
            if (job := jobs.get(action.get("job", {}).get("id"))) is not None:
                action = {**action, "job": {**job, "cancelable": reminders.can_cancel(state, job)}}
            if effect := state["actions"].get(action.get("effect_action")):
                action = {**action, "effect_undone": bool(effect.get("undone"))}
            actions.append(action)
        sending = {item["thread_id"] for item in scheduler.email_records(state)
                   if item.get("delivery", {}).get("email", {}).get("sending")}
        return {"thread_id": thread_id, "threads": [
                    {**thread, "busy": thread["id"] in active,
                     **({"activity": active[thread["id"]]} if active.get(thread["id"]) else {})}
                    for thread in threads],
                "messages": messages, "actions": actions,
                "workers": [row for row in state.get("workers", {}).values() if row["thread_id"] == thread_id],
                "message_artifacts": artifacts.message_artifacts(state, thread_id),
                "message_uploads": message_uploads, "timezone": saved(state)["timezone"],
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

    def timeline_info(self, pinecone=None):
        with self.storage.lock():
            state = self.storage.load()
            if approvals.expire(state, datetime.now(timezone.utc)):
                self.storage.save(state)
            zone = saved(state)["timezone"]
        if pinecone is None:
            pinecone = self.memory_index.pinecone_status(self.agent.config)
        entries = timeline.entries(self.storage, self.threads, self.agent.can_undo,
                                   pinecone=pinecone,
                                   mail_connected=bool(self.agent.config.get("agentmail", {}).get("connection_id")))
        represented = {row["data"]["checkpoint"]["id"] for row in entries
                       if row.get("action_id") and row["data"].get("checkpoint")}
        try:
            checkpoints = self.timeline()
        except HearthError as error:
            return {"entries": scrub(entries), "checkpoint_notice": str(error), "timezone": zone}
        entries.extend(timeline.entry(
            "checkpoint", redact_text(item["comment"]), {**item, "thread_id": item.get("thread_id", ""),
                                                          "thread_title": item.get("thread_title", "Workspace")},
            id=f"checkpoint:{item['id']}", at=item["created_at"], data={"checkpoint": item},
        ) for item in checkpoints if item["id"] not in represented)
        return {"entries": scrub(entries), "timezone": zone}

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
        timeline.record(self.storage, "voice", "Call token issued", {"thread_id": "", "thread_title": "Workspace"},
                        provider=provider)
        return reply

    def enqueue(self, thread_id, prompt, *, source=None, approval=None, attachment_ids=None, task_run=None,
                stoppable=False):
        command = (SIDE_COMMAND.fullmatch(prompt)
                   if thread_id == MAIN and source is None and not approval and not attachment_ids else None)
        if command:
            prompt = require_text(command[1], 4_000)
        with self.storage.lock():
            thread = self.threads.create() if command else self.threads.describe(thread_id)
            attachments = self.uploads.validate(thread["id"], attachment_ids) if attachment_ids is not None else []
        thread_id = thread["id"]
        events = SimpleQueue()
        control = ReplyControl() if stoppable else None
        events.put(("queued", {"thread": thread, "prompt": redact_text(prompt),
                               **({"reply_id": control.id} if control else {}),
                               **({"attachments": attachments} if attachments else {})}))
        with self.turn_lock:
            pending = self.turns.get(thread_id)
            queued = (prompt, events, source, approval, attachments, task_run, control)
            if pending is not None:
                pending.append(queued)
            else:
                self.turns[thread_id] = deque([queued])
                threading.Thread(target=self.run_turns, args=(thread_id,), daemon=True).start()
        return events

    def stop_reply(self, thread_id, reply_id):
        with self.turn_lock:
            control = next((row[-1] for row in self.turns.get(thread_id, ())
                            if row[-1] and row[-1].id == reply_id), None)
            if not control or control.committing:
                return {"stopped": False}
            control.stopped.set()
            message_id = control.message_id
        if message_id:
            self.workers.stop(message_id)
        return {"stopped": True}

    def run_turns(self, thread_id):
        while True:
            with self.turn_lock:
                prompt, events, source, approval, attachments, task_run, control = self.turns[thread_id][0]
            agent = self.agent

            def event(name, data):
                if control and name not in {"worker", "error"}:
                    control.check()
                    if name in {"started", "committing"}:
                        with self.turn_lock:
                            control.check()
                            if name == "started":
                                control.message_id = data["message"]["id"]
                            else:
                                control.committing = True
                if name == "committing":
                    return
                phase = {"started": "thinking", "tool_started": "working", "tool_finished": "thinking",
                         "token": "thinking" if source == voice_call.SOURCE else "speaking",
                         "reset": "thinking", "remembered": "remembering"}.get(name)
                if phase or name in {"browse_active", "browse_finished", "skill_loaded"}:
                    with self.turn_lock:
                        activity = self.turn_activity.get(thread_id, {})
                        if name == "browse_active":
                            activity = {**activity, "browse": data, "pose": "working"}
                        elif name == "browse_finished":
                            activity = {key: value for key, value in activity.items() if key != "browse"}
                        elif name == "skill_loaded":
                            activity = {**activity, "skill": data}
                        else:
                            activity = {**activity, "pose": phase, "detail": data.get("title")}
                        self.turn_activity[thread_id] = activity
                if name == "done" and "provider" in data and self.agent is agent:
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
                if control:
                    control.check()
                if approval:
                    agent.run_browse_approval(approval, thread_id, event)
                else:
                    agent.chat(prompt, event, thread_id, source=source,
                               **({"task_run": task_run} if task_run else {}),
                               **({"attachments": attachments} if attachments else {}),
                               **({"check": control.check} if control else {}))
                    if source is None and not task_run:
                        self.ideas.after_chat(thread_id)
            except Exception as error:
                if control and control.stopped.is_set():
                    self.workers.stop(control.message_id)
                    try:
                        timeline.record(self.storage, "tool", "Chat reply stopped", {"thread_id": thread_id})
                    except OSError:
                        pass
                    events.put(("stopped", {}))
                else:
                    detail = str(error) if isinstance(error, HearthError) else (
                        "Hearth could not finish this turn. Check Timeline for any completed actions.")
                    event("error", {"message": detail})
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
            if operation == "reset" and body.keys() == {"thread_id"}:
                thread = self.threads.describe(thread_id)
                checkpoint = self.checkpoints.create("Before resetting a Hearth chat summary")
                self.threads.reset_summary(thread_id)
                action = self.agent.add_action("memory", "Thread summary reset", status="complete", checkpoint=checkpoint,
                                               thread_id=thread_id, thread_title=thread["title"])
                return {"summary": "", "action": action}
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
                text = message["content"]
                if not text and message.get("attachment_ids"):
                    names = [item["filename"] for item in self.uploads.for_messages(thread_id, [message]).values()]
                    text = ", ".join(names)
                quote = compact(redact_text(text), 500)
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
            state = self.storage.load()
            action = state["actions"].get(action_id)
            event_run = action_id in state.get("event_runs", {})
        if event_run:
            return event_automations.undo_run(self, action_id), 200
        if action and action.get("undo_automation"):
            return event_automations.undo_delete(self, action_id), 200
        if action and action.get("undo_task"):
            return tasks.undo_delete(self.storage, action_id), 200
        if action and action["kind"] == "goal":
            return goals.undo(self.storage, action_id), 200
        if action and action["kind"] == "page":
            return self.pages.undo(action_id), 200
        if action and action["kind"] == "skill":
            return self.agent.skills.undo(action_id), 200
        if action and action["kind"] == "reminder":
            return self.reminders.cancel(action["job"]["id"]), 200
        if action and action.get("memory_change"):
            return self.replay_memory(action_id), 200
        self.start_restore(action_id)
        return self.restore, 202

    def start_restore(self, action_id):
        if self.workers.busy():
            raise HearthError("Wait for worker tools to finish before restoring a checkpoint.")
        if self.event_runner.worker.locked():
            raise HearthError("Wait for automation processing to finish before restoring a checkpoint.")
        if self.task_runner.worker.locked():
            raise HearthError("Wait for recurring task processing to finish before restoring a checkpoint.")
        if self.reindex_running() or self.memory_sync.running:
            raise HearthError("Wait for memory reindexing to finish before restoring a checkpoint.")
        with self.turn_lock:
            if self.turns:
                raise HearthError("Wait for active chats to finish before restoring a checkpoint.")
        with self.storage.lock():
            action = self.storage.load()["actions"].get(action_id)
            if not self.agent.can_undo(action):
                raise HearthError("This action has no available Undo.")
            if self.checkpoints.mode == "sprite" and any(
                rule["at"] >= action["checkpoint"]["created_at"] for rule in memory.standing_rules(self.storage)
            ):
                raise HearthError("This checkpoint predates a permanent forget request and cannot be restored.")
        self.restore = {"action_id": action_id, "status": "restoring"}
        self.artifacts.reset()
        threading.Thread(target=self.restore_checkpoint, args=(action,), daemon=True).start()

    def restore_checkpoint(self, action):
        # Give the HTTP acknowledgement time to leave before the Sprite disconnects.
        time.sleep(0.35)
        with self.operation:
            try:
                with self.storage.lock():
                    self.checkpoints.restore(action["checkpoint"]["id"])
                    self.memory_index.clear_sources()
                    self.uploads.clear_extractions()
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
                    with self.storage.lock():
                        memory.catalog(self.storage)
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

    def response_headers(self, status, content_type, length=None, *, email_preview=False, etag=None,
                         disposition=None, inline_pdf=False, page_csp=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if length is not None:
            self.send_header("Content-Length", str(length))
        if etag is not None:
            self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.send_header("Content-Security-Policy",
                         page_csp or ("default-src 'self'; connect-src 'self' wss://*.livekit.cloud https://*.livekit.cloud; "
                         "frame-src 'self' https://browserbase.com https://*.browserbase.com "
                         "https://browserbase.live https://*.browserbase.live; "
                         "img-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors "
                         + ("'self'" if inline_pdf else "'none'")
                         + ("; style-src 'unsafe-inline'; script-src 'none'" if email_preview else "")))
        if content_type == "text/event-stream":
            self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    def json(self, data, status=200, *, conditional=False):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        etag = f'"{sha256(body).hexdigest()}"' if conditional else None
        content_type = "application/json; charset=utf-8"
        if etag is not None and self.headers.get("If-None-Match") == etag:
            self.response_headers(304, content_type, etag=etag)
            return
        self.response_headers(status, content_type, len(body), etag=etag)
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
                self.json(self.app.info(thread_id), conditional=True)
            elif url.path == "/api/threads/summary":
                thread_id = parse_qs(url.query).get("thread", [MAIN])[0]
                with self.app.storage.lock():
                    summary = self.app.threads.summary(thread_id)
                self.json({"summary": summary})
            elif url.path == "/api/home":
                self.json({**self.app.home.snapshot(), "checkpoints": self.app.checkpoints.mode})
            elif url.path == "/api/goals/links":
                self.json({"items": goals.link_options(self.app.storage.load())})
            elif url.path == "/api/feed":
                query = parse_qs(url.query)
                try:
                    limit = int(query.get("limit", ["4"])[0])
                except ValueError:
                    raise HearthError("Choose a valid Feed page size.") from None
                self.json(self.app.feed.list(cursor=query.get("cursor", [""])[0], limit=limit,
                                             saved=query.get("saved", ["0"])[0] == "1"))
            elif url.path == "/api/feed/settings":
                self.json(self.app.feed.get_settings())
            elif url.path == "/api/proactivity/settings":
                self.json(self.app.proactivity.get_settings())
            elif url.path == "/api/proactivity/pass":
                if not equal(self.headers.get("X-Hearth-Tick-Token"), self.app.reminders.tick_token):
                    self.json({"error": "Scheduler token required."}, 401)
                else:
                    self.json(self.app.proactivity.last())
            elif url.path == "/api/home/settings":
                self.json(self.app.home.settings())
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
            elif url.path == "/api/skills":
                self.json({"skills": self.app.agent.skills.list()})
            elif url.path == "/api/skills/detail":
                params = parse_qs(url.query)
                self.json(self.app.agent.skills.detail(params.get("id", [None])[0], params.get("version", [None])[0]))
            elif url.path == "/api/memory/settings":
                self.json(self.app.memory_info())
            elif url.path == "/api/memory/review":
                self.json(self.app.memory_review.get())
            elif url.path == "/api/search/settings":
                self.json(self.app.search_info())
            elif url.path.startswith("/api/browse/screenshots/"):
                name = url.path.removeprefix("/api/browse/screenshots/")
                try:
                    domain = parse_qs(url.query).get("domain", ["fly.io"])[0][:253]
                    body = (browserbase.demo_image(domain) if name == "demo.png"
                            else browserbase.screenshot_path(self.app.storage, name).read_bytes())
                except (FileNotFoundError, HearthError):
                    self.json({"error": "Browser screenshot not found."}, 404)
                else:
                    self.response_headers(200, "image/png", len(body))
                    self.wfile.write(body)
            elif url.path == "/api/approvals":
                self.json({"approvals": approvals.records(self.app.storage)})
            elif url.path == "/api/approvals/settings":
                self.json(approvals.policy(self.app.storage.load()))
            elif url.path == "/api/event-automations":
                with self.app.storage.lock():
                    state = self.app.storage.load()
                    result = {"automations": event_automations.describe(state),
                              "threads": self.app.threads.list(),
                              "reminders": [{"id": row["id"], "message": row["message"]} for row in state["jobs"]
                                            if row["status"] == "scheduled"],
                              "timezone": saved(state)["timezone"], "feed_kinds": event_automations.FEED_KINDS}
                self.json(result)
            elif url.path == "/api/tasks":
                self.json(tasks.mutate(self.app.storage, "list", {}))
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
            elif url.path == "/api/pages":
                with self.app.storage.lock():
                    zone = saved(self.app.storage.load())["timezone"]
                self.json({"pages": self.app.pages.listing(), "timezone": zone})
            elif url.path == "/api/pages/detail":
                self.json(self.app.pages.detail(parse_qs(url.query).get("id", [None])[0]))
            elif url.path.startswith(("/pages/", "/p/")):
                self.get_page(url)
            elif url.path == "/api/artifacts":
                force = parse_qs(url.query).get("refresh") == ["1"]
                self.json(self.artifact_times(self.app.artifacts.list(force=force)))
            elif url.path in {"/api/uploads/detail", "/api/uploads/file"}:
                self.get_upload(url)
            elif url.path == "/api/artifacts/settings":
                self.json(self.app.artifacts.info())
            elif url.path == "/api/artifacts/detail":
                identity = parse_qs(url.query).get("id", [None])[0]
                self.json(self.artifact_times(self.app.artifacts.detail(identity)))
            elif url.path == "/api/artifacts/file":
                params = parse_qs(url.query)
                identity = params.get("id", [None])[0]
                inline = params.get("inline") == ["1"]
                with self.app.artifacts.download(identity, inline=inline) as (item, stream):
                    page = item["kind"] == "page"
                    content_type = "text/html; charset=utf-8" if page else box.FORMATS.get(
                        item["format"], "application/octet-stream")
                    mode = "inline" if inline else "attachment"
                    filename = quote(item["filename"], safe="")
                    size = stream.seek(0, 2)
                    stream.seek(0)
                    self.response_headers(200, content_type, size, inline_pdf=inline,
                                          disposition=f"{mode}; filename*=UTF-8''{filename}",
                                          page_csp=page_policy.CSP if page else None)
                    shutil.copyfileobj(stream, self.wfile, box.TRANSFER_CHUNK)
            elif url.path == "/api/memory/reindex":
                self.json(self.app.memory_sync_info())
            elif url.path == "/api/memory/chat":
                params = parse_qs(url.query)
                thread = params.get("thread", [None])[0]
                message = params.get("message", [None])[0]
                self.json(self.app.chat_memory(thread, message))
            elif url.path == "/api/memory":
                params = parse_qs(url.query)
                path, identity = (params.get(key, [None])[0] for key in ("path", "id"))
                storage = self.app.storage
                with storage.lock():
                    if path or identity:
                        path = memory.resolve(storage, path=path, id=identity)
                        raw = storage.read(path)
                        content = redact_text(raw)
                        meta, note, header = memory.parse(path, content)
                        data = {"path": path, "content": content, "body": note, "header_lines": header,
                                "meta": meta, "revision": memory.revision(raw)}
                    else:
                        rows = memory.catalog(storage)
                        data = {"files": [row["path"] for row in rows], "index": rows,
                                **memory.profile_record(storage),
                                "forget_rules": len(memory.standing_rules(storage))}
                self.json(data)
            else:
                self.json({"error": "Page not found."}, 404)
        except HearthError as error:
            self.json({"error": str(error)}, error.status if isinstance(error, pages.PageError) else 400)
        except OSError:
            self.json({"error": "Hearth could not read workspace data."}, 500)

    def body(self, limit=24_000):
        if self.headers.get_content_type() != "application/json":
            raise HearthError("Expected a JSON request.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= limit:
                raise ValueError
            self.connection.settimeout(15)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError
            body = json.loads(raw)
            # JSON escapes can represent lone surrogates, which Hearth cannot store as UTF-8.
            json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except TimeoutError:
            raise HearthError("The request timed out.") from None
        except (ValueError, RecursionError):
            raise HearthError("Invalid or oversized request.") from None
        if not isinstance(body, dict):
            raise HearthError("Expected a JSON object.")
        return body

    def artifact_times(self, result):
        with self.app.storage.lock():
            return {**result, "timezone": saved(self.app.storage.load())["timezone"]}

    def do_POST(self):
        origin = self.headers.get("Origin")
        if self.headers.get("Sec-Fetch-Site") not in (None, "none", "same-origin") or (
            origin is not None and not self.same_origin(origin)
        ):
            self.json({"error": "Send this request from Hearth."}, 403)
            return
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
        if self.path.startswith(("/api/approvals/", "/api/tasks/", "/api/event-automations/")):
            self.post_automation()
            return
        if self.path == "/api/workers/stop":
            try:
                body = self.body()
                if body.keys() - {"turn_id", "id"}:
                    raise HearthError("Choose a worker or a batch to stop.")
                turn_id = require_text(body.get("turn_id"), 40)
                identity = require_text(body["id"], 40) if "id" in body else None
                self.json(self.app.workers.stop(turn_id, identity))
            except HearthError as error:
                self.json({"error": str(error)}, 400)
            except OSError:
                self.json({"error": "Hearth could not stop the worker."}, 500)
            return
        if self.path == "/api/chat/stop":
            try:
                body = self.body()
                thread = require_text(body.get("thread_id"), 40)
                reply = require_text(body.get("reply_id"), 40)
                self.json(self.app.stop_reply(thread, reply))
            except HearthError as error:
                self.json({"error": str(error)}, 400)
            return
        if self.path.startswith("/api/goals/"):
            self.post_goal()
            return
        if self.path.startswith("/api/feed/"):
            self.post_feed()
            return
        if self.path.startswith("/api/memory/review/"):
            self.post_memory_review()
            return
        if self.path.startswith("/api/proactivity/"):
            self.post_proactivity()
            return
        if self.path.startswith("/api/home/"):
            self.post_home()
            return
        if self.path.startswith(("/api/reminders/", "/api/inbox/")):
            self.post_reminders()
            return
        if self.path.startswith("/api/pages/"):
            self.post_pages()
            return
        if self.path.startswith("/api/artifacts/"):
            self.post_artifact()
            return
        if urlsplit(self.path).path in {"/api/uploads", "/api/uploads/box"}:
            self.post_upload(urlsplit(self.path))
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
                  "/api/threads/delete", "/api/threads/share", "/api/threads/summary/reset",
                  "/api/memory/settings", "/api/memory/test",
                  "/api/memory/search", "/api/memory/reindex", "/api/memory/sync", "/api/memory/forget",
                  "/api/memory/write", "/api/memory/move", "/api/memory/profile",
                  "/api/search/settings", "/api/search/test", "/api/browse/settings", "/api/browse/approve",
                  "/api/skills/create", "/api/skills/save", "/api/skills/delete", "/api/skills/duplicate", "/api/skills/try"}
        if self.path not in routes:
            self.json({"error": "Page not found."}, 404)
            return
        try:
            large = self.path.startswith(("/api/skills/", "/api/memory/"))
            body = self.body(limit=160_000 if large else 24_000)
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
        accepting_chat = self.path in {"/api/chat", "/api/browse/approve"} or self.path.startswith("/api/threads/")
        if self.path in {"/api/connections/rescan", "/api/connections/test", "/api/memory/search"}:
            # Background discovery can overlap with a connector test or memory search.
            acquired = self.app.operation.acquire(timeout=5)
        else:
            acquired = self.app.operation.acquire(blocking=accepting_chat)
        if not acquired:
            self.json({"error": "Hearth is working on another action."}, 409)
            return
        status = 200
        stream = None
        try:
            if self.app.restore and self.app.restore["status"] == "restoring":
                result, status = {"error": "A checkpoint is being restored."}, 409
            else:
                if self.path == "/api/chat":
                    identities = body.get("attachment_ids", [])
                    prompt = body.get("message", "")
                    prompt = "" if identities and isinstance(prompt, str) and not prompt.strip() else require_text(prompt, 4_000)
                    stream = self.app.enqueue(body.get("thread_id", MAIN), prompt, attachment_ids=identities,
                                              stoppable=True)
                elif self.path == "/api/browse/approve" and body.keys() == {"id", "thread_id"}:
                    stream = self.app.enqueue(body["thread_id"], "", approval=require_text(body["id"], 40))
                elif self.path == "/api/browse/settings":
                    self.app.connections.save_preferences("browsing", browserbase.settings(body))
                    self.app.reload_agent(reset_brain=False)
                    result = self.app.agent.browsing
                elif self.path == "/api/browse/approve":
                    raise HearthError("Invalid browser approval.")
                elif self.path.startswith("/api/threads/"):
                    result = self.app.update_thread(self.path.rsplit("/", 1)[-1], body)
                elif self.path.startswith("/api/skills/"):
                    operation = self.path.rsplit("/", 1)[-1]
                    library = self.app.agent.skills
                    if operation == "try":
                        if body.keys() != {"id"}:
                            raise HearthError("Choose a skill to try.")
                        with self.app.storage.lock():
                            skill = library.require(self.app.storage.load(), identity=body["id"])
                            result = self.app.threads.create(title=skill["name"], skill={key: skill[key] for key in ("id", "name")})
                    else:
                        result, _ = library.mutate(operation, body)
                elif self.path.startswith("/api/connections/"):
                    result = self.update_connections(body)
                elif self.path.startswith("/api/brain/"):
                    result = self.update_brain(body)
                elif self.path.startswith(("/api/memory/", "/api/search/")):
                    result = self.update_preferences(body)
                else:
                    action_id = require_text(body.get("id"), 40)
                    if self.path == "/api/approve":
                        with self.app.storage.lock():
                            action = self.app.storage.load()["actions"].get(action_id, {})
                        result = (self.app.pages.approve_share(action_id) if action.get("kind") == "page_share"
                                  else self.app.agent.approve(action_id))
                    elif self.path == "/api/redo":
                        result = self.app.replay_memory(action_id, redo=True)
                    else:
                        result, status = self.app.undo_action(action_id)
        except HearthError as error:
            result, status = {"error": str(error)}, error.status if isinstance(error, pages.PageError) else 400
        except OSError:
            result, status = {"error": "Hearth could not update workspace data."}, 500
        finally:
            self.app.operation.release()
        if stream is not None:
            self.stream_chat(stream)
        else:
            self.json(result, status)

    def get_page(self, url):
        disposition = None
        csp = page_policy.CSP
        if url.path.startswith("/p/"):
            raw = self.app.pages.shared(url.path.removeprefix("/p/"))
            csp = page_policy.PUBLIC_CSP
        else:
            match = re.fullmatch(r"/pages/([a-f0-9]{32})(?:/v/([1-9][0-9]{0,8}))?", url.path)
            if not match:
                raise pages.PageError("Page not found.", 404)
            row, raw = self.app.pages.document(match[1], int(match[2]) if match[2] else None)
            if parse_qs(url.query).get("download") == ["1"]:
                name = quote(artifacts.filename(row["title"], "html"), safe="")
                disposition = f"attachment; filename*=UTF-8''{name}"
        self.response_headers(200, "text/html; charset=utf-8", len(raw), disposition=disposition,
                              page_csp=csp)
        self.wfile.write(raw)

    def post_pages(self):
        try:
            body = self.body()
            identity = require_text(body.get("id"), 32)
            with self.app.operation:
                if self.app.restoring():
                    raise pages.PageError("A checkpoint is being restored.", 409)
                if self.path == "/api/pages/revert":
                    result = self.app.pages.revert(identity, body.get("version"), body.get("current"))
                elif self.path == "/api/pages/share":
                    result = self.app.pages.request_share(identity, body.get("version"))
                elif self.path == "/api/pages/revoke":
                    result = self.app.pages.revoke(identity)
                elif self.path == "/api/pages/box":
                    result = self.app.pages.save_box(identity, body.get("version"))
                else:
                    raise pages.PageError("Page not found.", 404)
            self.json(result)
        except HearthError as error:
            self.json({"error": str(error)}, error.status if isinstance(error, pages.PageError) else 400)
        except OSError:
            self.json({"error": "Hearth could not update the page."}, 500)

    def post_memory_review(self):
        review = self.app.memory_review
        try:
            body = self.body()
            with self.app.operation:
                if self.app.restoring():
                    self.json({"error": "A checkpoint is being restored."}, 409)
                    return
                if self.path == "/api/memory/review/settings":
                    result = review.configure(body)
                elif self.path == "/api/memory/review/decision":
                    result = review.decide(body)
                elif self.path == "/api/memory/review/run" and not body:
                    result = review.kick(force=True)
                else:
                    raise HearthError("Invalid Memory review request.")
            self.json(result)
        except HearthError as error:
            self.json({"error": str(error)}, 400)
        except OSError:
            self.json({"error": "Hearth could not update Memory review."}, 500)

    def post_feed(self):
        operations = {"/api/feed/settings": self.app.feed.save_settings, "/api/feed/feedback": self.app.feed.feedback,
                      "/api/feed/chat": self.app.feed.chat, "/api/feed/idea": self.app.ideas.respond}
        try:
            if self.path == "/api/feed/refresh":
                if self.body():
                    raise HearthError("A Feed refresh takes no settings.")
                self.app.ideas.kick()
                result = self.app.feed.tick(force=True)
                timeline.record(self.app.storage, "feed", "Feed refresh requested",
                                {"thread_id": "", "thread_title": "Workspace"},
                                data={"detail": result["status"], "card_count": len(result["cards"])})
                self.json(result)
            elif handler := operations.get(self.path):
                with self.app.operation:
                    if self.app.restoring():
                        self.json({"error": "A checkpoint is being restored."}, 409)
                        return
                    result = handler(self.body())
                self.json(result)
            else:
                self.json({"error": "Page not found."}, 404)
        except HearthError as error:
            self.json({"error": str(error)}, 400)
        except OSError:
            self.json({"error": "Hearth could not update the Feed."}, 500)

    def post_proactivity(self):
        operation = self.path.rsplit("/", 1)[-1]
        if operation not in {"pass", "settings", "do", "dismiss", "snooze", "block"}:
            self.json({"error": "Page not found."}, 404)
            return
        if operation == "pass" and not equal(self.headers.get("X-Hearth-Tick-Token"), self.app.reminders.tick_token):
            self.json({"error": "Scheduler token required."}, 401)
            return
        stream = None
        try:
            body = self.body()
            if operation == "pass":
                if body:
                    raise HearthError("A proactive pass takes no settings.")
                result = self.app.proactivity.tick(force=True)
            else:
                with self.app.operation:
                    if self.app.restoring():
                        self.json({"error": "A checkpoint is being restored."}, 409)
                        return
                    if operation == "settings":
                        result = self.app.proactivity.save_settings(body)
                    elif operation == "do":
                        result, prompt = self.app.proactivity.update(operation, body)
                        if prompt is not None:
                            stream = self.app.enqueue(result["id"], prompt, source=proactivity.SOURCE)
                    else:
                        result = self.app.proactivity.update(operation, body)
            if stream is not None:
                self.stream_chat(stream)
            else:
                self.json(result)
        except HearthError as error:
            self.json({"error": str(error)}, 400)
        except OSError:
            self.json({"error": "Hearth could not update Proactivity."}, 500)

    def post_goal(self):
        try:
            body = self.body()
            operation = self.path.rsplit("/", 1)[-1]
            if operation not in {"create", "update", "checkin", "delete"}:
                raise HearthError("Choose a goal action.")
            if "delete" in body:
                raise HearthError("Choose a goal action using its dedicated route.")
            with self.app.operation:
                if self.app.restoring():
                    self.json({"error": "A checkpoint is being restored."}, 409)
                    return
                tool = "goal_" + ("update" if operation == "delete" else operation)
                result = self.app.agent.execute(tool, {**body, **({"delete": True} if operation == "delete" else {})})
            self.json(result)
        except HearthError as error:
            self.json({"error": str(error)}, 400)

    def post_home(self):
        actions = {
            "/api/home/layout": self.app.home.adjust,
            "/api/home/checklist": self.app.home.toggle,
            "/api/home/settings": self.app.home.save_settings,
            "/api/home/chat": lambda body: self.app.home.panel_chat(body.get("id")),
        }
        try:
            if self.app.restoring():
                self.json({"error": "A checkpoint is being restored."}, 409)
                return
            body = self.body()
            if self.path == "/api/home/refresh":
                identity = body.get("id")
                if identity == "weather":
                    self.app.home.refresh_weather()
                    result = self.app.home.settings()
                else:
                    result, _ = self.app.home.panels.refresh(identity)
                self.json(result)
            elif self.path in actions:
                with self.app.operation:
                    if self.app.restoring():
                        self.json({"error": "A checkpoint is being restored."}, 409)
                        return
                    result = actions[self.path](body)
                self.json(result)
            else:
                self.json({"error": "Page not found."}, 404)
        except HearthError as error:
            self.json({"error": str(error)}, 400)
        except OSError:
            self.json({"error": "Hearth could not update the Home panel."}, 500)

    def post_upload(self, url):
        try:
            if self.app.restore and self.app.restore["status"] == "restoring":
                raise uploads.UploadError("A checkpoint is being restored.", 409)
            if url.path == "/api/uploads/box":
                body = self.body()
                result = self.app.uploads.save_box(body.get("thread_id"), body.get("id"))
                self.json(result)
            else:
                thread_id = parse_qs(url.query).get("thread", [MAIN])[0]
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                self.connection.settimeout(30)
                result = self.app.uploads.stage(thread_id, self.rfile, length, self.headers.get("Content-Type", ""))
                self.json(result, 201)
        except uploads.UploadError as error:
            self.json({"error": str(error)}, error.status)
        except HearthError as error:
            self.json({"error": str(error)}, 400)
        except OSError:
            self.json({"error": "Hearth could not save the attachment."}, 500)

    def get_upload(self, url):
        params = parse_qs(url.query)
        thread_id = params.get("thread", [MAIN])[0]
        identity = params.get("id", [""])[0]
        try:
            if url.path.endswith("/detail"):
                self.json(self.app.uploads.detail(thread_id, identity))
                return
            row, directory = self.app.uploads.get(thread_id, identity)
            mime = row["mime"]
            thumbnail = params.get("thumbnail") == ["1"] and mime.startswith("image/")
            inline = thumbnail or (params.get("inline") == ["1"]
                                   and (mime.startswith(("image/", "audio/")) or row["format"] == "pdf"))
            heif = inline and mime == "image/heic"
            path = directory / ("thumbnail.jpg" if thumbnail else "preview.jpg" if heif else "file")
            with path.open("rb") as stream:
                if thumbnail or heif:
                    mime = "image/jpeg"
                mode = "inline" if inline else "attachment"
                name = quote(row["filename"], safe="")
                self.response_headers(200, mime, os.fstat(stream.fileno()).st_size,
                                      inline_pdf=inline and row["format"] == "pdf",
                                      disposition=f"{mode}; filename*=UTF-8''{name}")
                shutil.copyfileobj(stream, self.wfile)
        except uploads.UploadError as error:
            self.json({"error": str(error)}, error.status)
        except FileNotFoundError:
            self.json({"error": "Attachment not found in this chat."}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def post_automation(self):
        try:
            body = self.body(limit=48_000 if self.path.startswith("/api/event-automations/") else 24_000)
            operation = self.path.rsplit("/", 1)[-1]
            with self.app.operation:
                if self.app.restoring():
                    self.json({"error": "A checkpoint is being restored."}, 409)
                    return
                if self.path.startswith("/api/approvals/"):
                    if operation == "settings":
                        result = approvals.settings(self.app.storage, body)
                        self.app.memory_index.changed()
                    elif operation in {"approve", "edit", "decline"}:
                        result = approvals.decide(self.app.agent, require_text(body.get("id"), 40), operation,
                                                  body.get("changes"))
                    else:
                        raise HearthError("Choose an approval action.")
                elif self.path.startswith("/api/event-automations/"):
                    if operation == "delete" and body.keys() == {"id"}:
                        result = self.app.agent.execute("delete_event_automation", body)
                    elif operation in {"create", "update"}:
                        result = event_automations.mutate(self.app, operation, body)
                    else:
                        raise HearthError("Choose an automation action.")
                elif operation == "delete" and body.keys() == {"id"}:
                    result = self.app.agent.execute("delete_recurring_task", body)
                    action = result["action"]
                    if action["status"] == "pending":
                        with self.app.storage.lock():
                            self.app.threads.append(MAIN, "assistant", action["title"] + "?", action_ids=[action["id"]])
                elif operation in {"preview", "create", "update", "pause", "run"}:
                    result = tasks.mutate(self.app.storage, operation, body)
                    if operation == "run":
                        self.app.task_runner.kick()
                else:
                    raise HearthError("Choose a recurring task action.")
            self.json(result)
        except HearthError as error:
            self.json({"error": str(error)}, 400)
        except (OSError, TypeError, ValueError):
            self.json({"error": "Hearth could not update automation data."}, 400)

    def post_reminders(self):
        try:
            body = self.body()
            if self.app.restore and self.app.restore["status"] == "restoring":
                self.json({"error": "A checkpoint is being restored."}, 409)
                return
            operation = self.path.rsplit("/", 1)[-1]
            if self.path.startswith("/api/inbox/"):
                if operation == "poll" and (not body or (body.keys() == {"force"} and body["force"] is True)):
                    result = {"processed": self.app.inbox.poll(force=bool(body), manual=bool(body))}
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
        if operation not in {"settings", "retry", "delete", "undo", "ask"}:
            self.json({"error": "Page not found."}, 404)
            return
        try:
            body = self.body(24_000 if operation == "ask" else 8 * box.MAX_BYTES)
            if operation == "ask":
                if self.app.restore and self.app.restore["status"] == "restoring":
                    self.json({"error": "A checkpoint is being restored."}, 409)
                    return
                result = file_questions.ask(self.app.agent, body)
                if result.get("source"):
                    timeline.record(self.app.storage, "artifact", "Answered a question about Box files",
                                    {"thread_id": "", "thread_title": "Workspace"},
                                    provider="box", data={"citation_count": len(result["citations"])})
            elif operation == "settings":
                with self.app.operation:
                    if self.app.restore and self.app.restore["status"] == "restoring":
                        self.json({"error": "A checkpoint is being restored."}, 409)
                        return
                    result = self.update_artifacts(operation, body)
            elif self.app.restoring():
                self.json({"error": "A checkpoint is being restored."}, 409)
                return
            else:
                result = self.update_artifacts(operation, body)
        except HearthError as error:
            self.json({"error": str(error)}, 400)
        except TimeoutError:
            self.json({"error": "The request timed out."}, 408)
        except OSError:
            self.json({"error": "Hearth could not update workspace data."}, 500)
        else:
            self.json(result)

    def update_artifacts(self, operation, body):
        service = self.app.artifacts
        if operation == "settings":
            self.app.connections.save_preferences("artifacts", box.settings(body))
            self.app.reload_agent(reset_brain=False)
            self.app.memory_sync.request("startup")
            return service.info()
        if operation == "undo" and body.keys() == {"id"}:
            return service.undo(require_text(body["id"], 40))
        return service.mutate(operation, body)

    def post_call(self):
        operation = self.path.removeprefix("/api/voice/call/")
        if operation not in ("token", "query", "report"):
            self.json({"error": "Page not found."}, 404)
            return
        try:
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
                    message = packet[1]["message"]
                    reply = message["content"] or ("Your file is ready in the chat." if message.get("artifacts") else "")
                    return {"reply": reply}
        except Empty:
            pass
        raise voice.VoiceError("Hearth is still working. Check the thread for the reply.", 504)

    def post_voice(self):
        url = urlsplit(self.path)
        params = parse_qs(url.query)
        thread_id = params.get("thread", [None])[0]
        whisper = url.path == "/api/voice/transcribe"
        try:
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
        if operation == "settings":
            allowed.add("parallel_workers")
        if body.keys() - allowed or not {"provider", "model"} <= body.keys():
            raise HearthError("Invalid brain settings.")
        connections = self.app.connections
        selection = connections.brain_selection(body["provider"], body["model"])
        pool = validate_pool(body["pool"]) if "pool" in body else None
        if operation == "settings":
            cap = workers.validate_cap(body["parallel_workers"]) if "parallel_workers" in body else None
            connections.save_brain(selection, pool, cap)
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
            storage = self.app.storage
            if operation == "profile" and body.keys() == {"profile", "notes", "revision"}:
                with storage.lock():
                    current = memory.profile_record(storage)
                    if body["revision"] != current["revision"]:
                        raise HearthError("The profile changed. Reload Memory before saving.")
                    profile = memory.normalize_profile(body["profile"])
                    if not isinstance(body["notes"], str):
                        raise HearthError("Enter the profile notes as text.")
                    data, _, _ = memory.parse(memory.PROFILE_NOTE, storage.read(memory.PROFILE_NOTE)
                                              if current["revision"] else "")
                    data["profile"] = profile
                    note = memory.render(data, "\n" + body["notes"].strip() + "\n")
                    return agent.write_memory_notes([{"path": memory.PROFILE_NOTE, "content": note}])
            if operation in {"write", "move"} and body.keys() == {"path", "revision", "content" if operation == "write" else "target"}:
                with storage.lock():
                    path = memory.resolve(storage, path=body["path"])
                    if body["revision"] != memory.revision(storage.read(path)):
                        raise HearthError("The note changed. Reload it before saving.")
                    if operation == "write":
                        return agent.write_memory_notes([{"path": path, "content": body["content"]}])
                    return agent.move_memory_note(body["target"], path=path)
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
