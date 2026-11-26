import argparse
import json
import os
import re
import shutil
import sys
import threading
import time
from collections import OrderedDict, deque
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, SimpleQueue
from urllib.parse import parse_qs, quote, urlsplit

from . import approvals, artifacts, box, browserbase, event_automations, feed, home, inbox, memory, memory_edits, memory_purge, memory_review, page_policy, pages, proactivity, proactive_context, recall, reminders, router, scheduler, search, skills, tasks, timeline, uploads, voice, voice_call, workers
from . import file_questions, goals, ideas, self_update
from .agent import Agent, require_text
from .checkpoints import LocalCheckpoints, RestoreInProgress, SpriteCheckpoints
from .connections import Connections, catalog_entry, validate_pool
from .connectors import Gateway, read_config
from .gateway_tools import redact_text, scrub
from .http_requests import Request, RequestError, body_length, read_json, receive_multipart
from .http_routes import route_for
from .memory_sync import MemorySync
from .reminder_config import equal, saved
from .storage import HearthError, ROOT, Storage, iso, new_id, revision
from .subsystem_status import SubsystemStatus
from .threads import MAIN, Threads, compact


class ChatStopped(Exception):
    pass


@dataclass(frozen=True)
class HTTPResult:
    data: dict
    status: int


@dataclass(frozen=True)
class ChatStream:
    events: SimpleQueue


class PollCache:
    def __init__(self, limit):
        self.limit = limit
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def get(self, variant, signature, build):
        with self.lock:
            stamp = signature()
            now = datetime.now(timezone.utc)
            cached = self.entries.get(variant)
            if cached is None or cached[0] != stamp or (cached[1] and now >= cached[1]):
                data, expires = build(now)
                cached = stamp, expires, (data, f'"{new_id()}"')
                self.entries[variant] = cached
                if len(self.entries) > self.limit:
                    self.entries.popitem(last=False)
            self.entries.move_to_end(variant)
            return cached[2]


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
    "/thread-menu.js": ("thread-menu.js", "text/javascript; charset=utf-8"),
    "/combobox.js": ("combobox.js", "text/javascript; charset=utf-8"),
    "/combobox.css": ("combobox.css", "text/css; charset=utf-8"),
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
    "/chat-state.js": ("chat-state.js", "text/javascript; charset=utf-8"),
    "/self-update.js": ("self-update.js", "text/javascript; charset=utf-8"),
    "/self-update.css": ("self-update.css", "text/css; charset=utf-8"),
    "/sse.js": ("sse.js", "text/javascript; charset=utf-8"),
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
    "/icons/chevron.svg": ("icons/chevron.svg", "image/svg+xml"),
    "/icons/icon.svg": ("icons/icon.svg", "image/svg+xml"),
    "/icons/favicon.svg": ("icons/favicon.svg", "image/svg+xml"),
    "/icons/apple-touch-icon.png": ("icons/apple-touch-icon.png", "image/png"),
    "/icons/icon-512.png": ("icons/icon-512.png", "image/png"),
}
SIDE_COMMAND = re.compile(r"/(?:side|btw)(?:\s+(.+))?", re.I | re.S)
CLIENT_DISCONNECT = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)


class Application:
    def __init__(self, storage, checkpoints, config, *, config_path=None, gateway=None):
        self.storage = storage
        self.version = self_update.deployed_version()
        self.self_updates = self_update.SelfUpdates(self)
        self.subsystem_status = SubsystemStatus()
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
        self.state_cache = PollCache(8)
        self.home_cache = PollCache(1)
        self.reindex = None
        self.call_check = None
        self.memory_index = recall.Recall(storage, self.gateway)
        self.reload_agent()
        self.memory_sync = MemorySync(self)
        self.memory_index.on_change = self.memory_sync.request
        self.artifacts.on_memory_change = self.memory_sync.request
        self.reminders = reminders.Reminders(self)
        self.reminders.recover()
        self.inbox = inbox.Inbox(self)
        self.scheduler_inbox = threading.Lock()
        self.home = home.Home(self)
        self.proactivity = proactivity.Proactivity(self)
        self.feed = feed.Feed(self)
        self.ideas = ideas.Ideas(self)
        self.memory_review = memory_review.MemoryReview(self)
        self.task_runner = tasks.Runner(self)
        self.event_runner = event_automations.Runner(self)
        approvals.upgrade_legacy(self.agent)

    def scheduler_tick(self):
        result = scheduler.claim_due(self.storage, tick=True)
        if result["last_tick"] is None:
            return result
        if result["queued_deliveries"]:
            self.reminders.kick()
        self.kick_scheduler_inbox(force=True)
        self.proactivity.kick()
        self.feed.kick()
        self.ideas.kick()
        self.memory_review.kick()
        self.task_runner.kick()
        self.event_runner.kick()
        self.home.kick()
        return result

    def kick_scheduler_inbox(self, *, force):
        if not self.scheduler_inbox.acquire(blocking=False):
            return

        def poll():
            try:
                self.inbox.poll(force=force)
            finally:
                self.scheduler_inbox.release()

        try:
            threading.Thread(target=poll, name="hearth-scheduled-inbox", daemon=True).start()
        except RuntimeError:
            self.scheduler_inbox.release()
            raise

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
                if not self.restoring():
                    claimed = scheduler.claim_due(self.storage, tick=woke)
                    if claimed["queued_deliveries"]:
                        self.reminders.kick()
                    if woke or now >= next_inbox:
                        self.kick_scheduler_inbox(force=woke)
                        next_inbox = now + 60
                    self.task_runner.kick()
                    self.event_runner.kick()
                    self.self_updates.kick()
                    if woke or now >= next_home:
                        self.home.kick()
                        self.proactivity.kick()
                        self.feed.kick()
                        self.ideas.kick()
                        self.memory_review.kick()
                        next_home = now + 10
                    if claimed["last_tick"] is not None:
                        self.subsystem_status.success("scheduler")
                        previous = time.time()
            except (HearthError, OSError):
                self.subsystem_status.failure("scheduler", "storage_error")
            except Exception:
                self.subsystem_status.failure("scheduler", "loop_error")
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
        report["self_update"] = self.self_updates.settings()
        github = report["providers"]["github"]
        report["providers"] = {**report["providers"], "github": {**github, "uses": ["Hearth updates"]}}
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

    def active_turns(self):
        with self.turn_lock:
            return {thread: self.turn_activity.get(thread) for thread in self.turns}

    def history_revision(self):
        live, rules = revision(self.storage.live, self.storage.root / "memory-forget.json")
        return sha256(repr((live and live[0], rules)).encode()).hexdigest()[:24]

    def sidebar_revision(self):
        stamp = self.storage.revisions()[1], revision(self.threads.root, self.threads.index)
        return sha256(repr((stamp, self.history_revision())).encode()).hexdigest()[:24]

    def thread_page(self, offset):
        active = self.active_turns()
        with self.storage.lock():
            index = self.threads.load_index()
            threads, following = self.threads.sidebar(index, active, (), offset)
            return {"threads": threads, "next_thread_offset": following,
                    "thread_revision": self.sidebar_revision()}

    def state_signature(self):
        return (self.storage.revisions()[0], revision(*self.activity.paths, self.threads.index),
                self.history_revision(), self.active_turns(), self.brain_status(),
                self.restore, bool(self.memory_index.hf_entry(self.agent.config)),
                voice_call.PROVIDER in self.connections.selected)

    def state_poll(self, thread_id, action_id):
        return self.state_cache.get((thread_id, action_id), self.state_signature,
                                    lambda now: self.state_snapshot(thread_id, action_id, now))

    def home_poll(self):
        def build(now):
            snapshot, expires = self.home.build_snapshot(now)
            return {**snapshot, "checkpoints": self.checkpoints.mode}, expires

        return self.home_cache.get(None, self.home.signature, build)

    def info(self, thread_id=MAIN):
        return self.state_snapshot(thread_id, None, datetime.now(timezone.utc))[0]

    def state_snapshot(self, thread_id, action_id, now):
        active = self.active_turns()
        with self.storage.lock():
            state = self.storage.load()
            index = self.threads.load_index()
            selected = thread_id if thread_id in index else MAIN
            threads, following = self.threads.sidebar(index, active, state.get("messages", ()), selected=selected)
            if approvals.expire(state, now):
                self.storage.save(state)
            transcript = self.transcript(state, selected, extra_action=action_id, include_recent=True)
            thread_revision = self.sidebar_revision()
        sending = {item["thread_id"] for item in scheduler.email_records(state)
                   if item.get("delivery", {}).get("email", {}).get("sending")}
        pending = [action for action in state["actions"].values() if action["status"] in {"pending", "changing"}]
        expires = min((datetime.fromisoformat(row["expires_at"]) for row in pending
                       if row.get("tool") and row["status"] == "pending"), default=None)
        active_work = bool(active or pending or sending or any(
            row["thread_id"] == selected and row["status"] in self_update.TRANSIENT
            for row in state.get("self_updates", {}).values()) or any(
            row["status"] in workers.ACTIVE for row in state.get("workers", {}).values()))
        return ({"threads": threads, "next_thread_offset": following, "thread_revision": thread_revision,
                 "thread_activity": active,
                 **transcript, "timezone": saved(state)["timezone"],
                 "jobs": state["jobs"][-25:], "reminders": [reminders.public_item(item) for item in state["reminders"][-25:]],
                 "reminder_sending": sorted(sending), "active_work": active_work,
                 "routing": state.get("routing", [])[-50:],
                 "whisper_available": bool(self.memory_index.hf_entry(self.agent.config)),
                 "voice_call_available": voice_call.PROVIDER in self.connections.selected,
                 "restore": self.restore, "checkpoints": self.checkpoints.mode, **self.brain_status()}, expires)

    def transcript_page(self, thread_id, before):
        with self.storage.lock():
            self.threads.require(thread_id)
            return self.transcript(self.storage.load(), thread_id, before)

    def transcript(self, state, thread_id, before=None, *, extra_action=None, include_recent=False):
        messages, cursor, prompt = self.threads.page(thread_id, state, before)
        message_ids = {row["id"] for row in messages}
        turn_ids = message_ids | {row["worker_turn_id"] for row in messages if row.get("worker_turn_id")}
        worker_rows = [row for row in state.get("workers", {}).values() if row["thread_id"] == thread_id
                       and (row["turn_id"] in turn_ids or (before is None and row["status"] in workers.ACTIVE))]
        worker_turns = {row["turn_id"] for row in worker_rows}
        records = state["actions"]
        linked = {identity for row in messages for identity in row.get("action_ids", ())}
        linked.update(action["id"] for action in records.values() if action.get("worker_turn_id") in worker_turns)
        if include_recent:
            # Retain recent actions for consumers of /api/state, including actions without a chat card.
            linked.update(list(records)[-32:])
        if extra_action:
            linked.add(extra_action)
        linked.update(records[identity].get("effect_action") for identity in list(linked) if identity in records)
        jobs = {job["id"]: job for job in state["jobs"]}
        actions = []
        for identity, action in records.items():
            if identity not in linked:
                continue
            if action["kind"] == "skill":
                action = {**action, "undoable": skills.can_undo(state, action)}
            if (job := jobs.get(action.get("job", {}).get("id"))) is not None:
                action = {**action, "job": {**job, "cancelable": reminders.can_cancel(state, job)}}
            if effect := records.get(action.get("effect_action")):
                action = {**action, "effect_undone": bool(effect.get("undone"))}
            actions.append(action)
        uploads_from = [*messages, prompt] if prompt else messages
        return {"thread_id": thread_id, "messages": messages, "before": cursor, "actions": actions,
                "self_updates": self_update.in_transcript(state, messages, thread_id),
                "workers": worker_rows, "history_revision": self.history_revision(),
                "record_revision": sha256(repr(revision(self.storage.state)).encode()).hexdigest()[:24],
                "previous_prompt": {"content": prompt["content"], "attachment_ids": prompt.get("attachment_ids", [])}
                if prompt else None,
                "message_artifacts": {identity: rows for identity, rows in artifacts.message_artifacts(state, thread_id).items()
                                      if identity in message_ids},
                "message_uploads": self.uploads.for_messages(thread_id, [
                    {"attachment_ids": [*row.get("attachment_ids", ()), *row.get("attachment_citations", ())]}
                    for row in uploads_from
                    if row.get("attachment_ids") or row.get("attachment_citations")
                ])}

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

    def update_thread(self, operation, thread_id, *, title=None, message_id=None):
        if operation == "create":
            with self.storage.lock():
                return self.threads.create()
        if operation == "delete":
            with self.turn_lock:
                if isinstance(thread_id, str) and thread_id in self.turns:
                    raise HearthError("Wait for this chat to finish before deleting it.")
        with self.storage.lock():
            if operation == "reset":
                thread = self.threads.describe(thread_id)
                checkpoint = self.checkpoints.create("Before resetting a Hearth chat summary")
                self.threads.reset_summary(thread_id)
                action = self.agent.add_action("memory", "Thread summary reset", status="complete", checkpoint=checkpoint,
                                               thread_id=thread_id, thread_title=thread["title"])
                return {"summary": "", "action": action}
            self.threads.require_side(thread_id)
            if operation == "rename":
                title = " ".join(redact_text(title).split())
                thread = self.threads.rename(thread_id, title)
                if self.agent.memory["include_chat"]:
                    self.memory_sync.request()
                return thread
            if operation == "delete":
                thread = self.threads.describe(thread_id)
                checkpoint = self.checkpoints.create("Before deleting a Hearth side chat")
                self.threads.delete(thread_id)
                if self.agent.memory["include_chat"]:
                    self.memory_sync.request()
                return self.agent.add_action("thread", "Side chat deleted", status="complete", checkpoint=checkpoint,
                                             thread_id=thread_id, thread_title=thread["title"])
            if operation == "share":
                messages = self.threads.messages(thread_id)
                message = next((item for item in messages if item["id"] == message_id), None)
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
            return event_automations.undo_run(self, action_id)
        if action and action.get("undo_automation"):
            return event_automations.undo_delete(self, action_id)
        if action and action.get("undo_task"):
            return tasks.undo_delete(self.storage, action_id)
        if action and action["kind"] == "goal":
            return goals.undo(self.storage, action_id)
        if action and action["kind"] == "page":
            return self.pages.undo(action_id)
        if action and action["kind"] == "skill":
            return self.agent.skills.undo(action_id)
        if action and action["kind"] == "reminder":
            return self.reminders.cancel(action["job"]["id"])
        if action and action.get("memory_change"):
            return self.replay_memory(action_id)
        return self.start_restore(action_id)

    def start_restore(self, action_id):
        if self.restoring():
            raise RestoreInProgress("A checkpoint is being restored.")
        if self.workers.busy():
            raise HearthError("Wait for worker tools to finish before restoring a checkpoint.")
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
        with ExitStack() as stack:
            if not stack.enter_context(scheduler.workspace_lock(self.storage, "scheduler-restore", timeout=0.25)):
                raise HearthError("The scheduler is busy. Try restoring again.")
            barrier = stack.pop_all()
        self.restore = restore = {"action_id": action_id, "status": "restoring"}
        try:
            self.artifacts.reset()
            threading.Thread(target=self.restore_checkpoint, args=(action, barrier), daemon=True).start()
        except RuntimeError:
            barrier.close()
            self.restore = {"action_id": action_id, "status": "failed"}
            raise
        return restore

    def restore_checkpoint(self, action, barrier):
        with barrier:
            # Give the HTTP acknowledgement time to leave before the Sprite disconnects.
            time.sleep(0.35)
            try:
                self.reminders.drain_for_restore()
                with self.operation:
                    with self.storage.lock():
                        rows = self.reminders.reconcile_locked(unfinished=True)
                        checkpoint = action["checkpoint"]
                        if self.checkpoints.mode == "sprite" and any(
                            row["written_at"] >= checkpoint["created_at"] or row["email"].get("pending_reconcile")
                            for row in rows.values()
                        ):
                            raise HearthError("This Sprite checkpoint can roll back reminder delivery records.")
                        # Publish the restore revision under the same lock as the live swap.
                        self.storage.bump_revision(threads=True)
                        self.checkpoints.restore(checkpoint["id"])
                        self.memory_index.clear_sources()
                        self.uploads.clear_extractions()
                        if self.checkpoints.mode == "local":
                            self.reminders.reconcile_locked()
                            memory.catalog(self.storage)
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
                # A successful native restore restarts the server and discards this thread.
                time.sleep(90)
                raise HearthError("The Sprite did not restart after restore.")
            except (HearthError, OSError):
                self.restore = {"action_id": action["id"], "status": "failed"}


class HTTPServer(ThreadingHTTPServer):
    def __init__(self, address, app):
        self.app = app
        super().__init__(address, Handler)

    def handle_error(self, request, client_address):
        if not isinstance(sys.exception(), CLIENT_DISCONNECT):
            self.app.subsystem_status.failure("http", "handler_error")


class Handler(BaseHTTPRequestHandler):
    @property
    def app(self):
        return self.server.app

    def log_message(self, format, *args):
        pass

    def response_headers(self, status, content_type, length=None, *, email_preview=False, etag=None,
                         disposition=None, inline_pdf=False, page_csp=None, headers=None):
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
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.response_status = status
        self.end_headers()

    def json(self, data, status=200, *, etag=None, headers=None):
        content_type = "application/json; charset=utf-8"
        candidates = self.headers.get("If-None-Match", "").split(",")
        if etag is not None and any(tag.strip().removeprefix("W/") in (etag, "*") for tag in candidates):
            self.response_headers(304, content_type, etag=etag)
            return
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.response_headers(status, content_type, len(body), etag=etag, headers=headers)
        if self.command != "HEAD":
            self.wfile.write(body)

    def get_static(self, request):
        filename, content_type = STATIC[request.path]
        body = (ROOT / "web" / filename).read_bytes()
        self.response_headers(200, content_type, len(body))
        self.wfile.write(body)

    def get_health(self, request):
        self.json({"ok": True, "checkpoints": self.app.checkpoints.mode, "version": self.app.version})

    def get_status(self, request):
        self.json({"subsystems": self.app.subsystem_status.snapshot()})

    def get_state(self, request):
        query = request.query
        thread_id = query.get("thread", [MAIN])[0]
        data, etag = self.app.state_poll(thread_id, query.get("action", [None])[0])
        self.json(data, etag=etag)

    def get_transcript(self, request):
        query = request.query
        self.json(self.app.transcript_page(query.get("thread", [MAIN])[0], query.get("before", [None])[0]))

    def get_threads(self, request):
        offset = request.query.get("offset", ["0"])[0]
        if not offset.isascii() or not offset.isdigit() or len(offset) > 9:
            raise HearthError("Choose a valid thread list offset.")
        self.json(self.app.thread_page(int(offset)))

    def get_threads_summary(self, request):
        thread_id = request.query.get("thread", [MAIN])[0]
        with self.app.storage.lock():
            summary = self.app.threads.summary(thread_id)
        self.json({"summary": summary})

    def get_home(self, request):
        data, etag = self.app.home_poll()
        self.json(data, etag=etag)

    def get_goals_links(self, request):
        self.json({"items": goals.link_options(self.app.storage.load())})

    def get_feed(self, request):
        query = request.query
        try:
            limit = int(query.get("limit", ["4"])[0])
        except ValueError:
            raise HearthError("Choose a valid Feed page size.") from None
        self.json(self.app.feed.list(cursor=query.get("cursor", [""])[0], limit=limit,
                                     saved=query.get("saved", ["0"])[0] == "1"))

    def get_feed_settings(self, request):
        self.json(self.app.feed.get_settings())

    def get_proactivity_settings(self, request):
        self.json(self.app.proactivity.get_settings())

    def get_proactivity_pass(self, request):
        self.json(self.app.proactivity.last())

    def get_home_settings(self, request):
        self.json(self.app.home.settings())

    def get_connections(self, request):
        self.json(self.app.connection_info())

    def get_voice_call_status(self, request):
        self.json(self.app.call_status())

    def get_brain(self, request):
        self.json(self.app.brain_info())

    def get_brain_models(self, request):
        provider = request.query.get("provider", [None])[0]
        self.json(self.app.connections.brain_models(provider))

    def get_checkpoints(self, request):
        self.json({"checkpoints": self.app.timeline()})

    def get_timeline(self, request):
        self.json(self.app.timeline_info())

    def get_timeline_events(self, request):
        with self.app.activity.subscribe() as events:
            self.stream_events(events)

    def get_skills(self, request):
        self.json({"skills": self.app.agent.skills.list()})

    def get_skills_detail(self, request):
        params = request.query
        self.json(self.app.agent.skills.detail(params.get("id", [None])[0], params.get("version", [None])[0]))

    def get_memory_settings(self, request):
        self.json(self.app.memory_info())

    def get_memory_review(self, request):
        self.json(self.app.memory_review.get())

    def get_search_settings(self, request):
        self.json(self.app.search_info())

    def get_screenshot(self, request):
        name = request.params["name"]
        try:
            domain = request.query.get("domain", ["fly.io"])[0][:253]
            body = (browserbase.demo_image(domain) if name == "demo.png"
                    else browserbase.screenshot_path(self.app.storage, name).read_bytes())
        except (FileNotFoundError, HearthError):
            self.json({"error": "Browser screenshot not found."}, 404)
        else:
            self.response_headers(200, "image/png", len(body))
            self.wfile.write(body)

    def get_approvals(self, request):
        self.json({"approvals": approvals.records(self.app.storage)})

    def get_approvals_settings(self, request):
        self.json(approvals.policy(self.app.storage.load()))

    def get_event_automations(self, request):
        with self.app.storage.lock():
            state = self.app.storage.load()
            result = {"automations": event_automations.describe(state),
                      "threads": self.app.threads.list(),
                      "reminders": [{"id": row["id"], "message": row["message"]} for row in state["jobs"]
                                    if row["status"] == "scheduled"],
                      "timezone": saved(state)["timezone"], "feed_kinds": event_automations.FEED_KINDS}
        self.json(result)

    def get_tasks(self, request):
        self.json(tasks.mutate(self.app.storage, "list", {}))

    def get_reminders_settings(self, request):
        self.json(self.app.reminders.info())

    def get_reminders(self, request):
        self.json(self.app.reminders.list())

    def get_inbox(self, request):
        self.json(self.app.inbox.list())

    def get_reminders_outbox(self, request):
        identity = request.query.get("id", [""])[0]
        email = self.app.reminders.outbox(identity)
        body = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>Hearth reminder email</title></head><body style="margin:0">'
                + email["html"] + "</body></html>").encode("utf-8")
        self.response_headers(200, "text/html; charset=utf-8", len(body), email_preview=True)
        self.wfile.write(body)

    def get_pages(self, request):
        with self.app.storage.lock():
            zone = saved(self.app.storage.load())["timezone"]
        self.json({"pages": self.app.pages.listing(), "timezone": zone})

    def get_pages_detail(self, request):
        self.json(self.app.pages.detail(request.query.get("id", [None])[0]))

    def get_artifacts(self, request):
        force = request.query.get("refresh") == ["1"]
        self.json(self.artifact_times(self.app.artifacts.list(force=force)))

    def get_artifacts_settings(self, request):
        self.json(self.app.artifacts.info())

    def get_artifacts_detail(self, request):
        identity = request.query.get("id", [None])[0]
        self.json(self.artifact_times(self.app.artifacts.detail(identity)))

    def get_artifacts_file(self, request):
        params = request.query
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

    def get_memory_reindex(self, request):
        self.json(self.app.memory_sync_info())

    def get_memory_chat(self, request):
        params = request.query
        thread = params.get("thread", [None])[0]
        message = params.get("message", [None])[0]
        self.json(self.app.chat_memory(thread, message))

    def get_memory(self, request):
        params = request.query
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

    def dispatch(self):
        self.response_status = None
        # BaseHTTPRequestHandler normalizes leading slashes. Match the original target instead.
        target = self.requestline.split()[1]
        path, _, query = target.partition("?")
        methods, params = route_for(path, STATIC) if "#" not in target else ({}, {})
        if not methods:
            self.json({"error": "Page not found."}, 404)
            return
        route = methods.get(self.command)
        if route is None:
            self.json({"error": "Method not allowed."}, 405, headers={"Allow": ", ".join(methods)})
            return
        try:
            if route.origin:
                self.require_origin()
            if route.tick_token and not equal(self.headers.get("X-Hearth-Tick-Token"), self.app.reminders.tick_token):
                raise RequestError("Scheduler token required.", 401)
            if not route.during_restore:
                self.require_ready()
            body = self.read_body(route) if self.command == "POST" else None
            request = Request(path, parse_qs(query), params, body, route.operation)
            result = self.handle_route(route, request)
            if isinstance(result, ChatStream):
                self.stream_chat(result.events)
            elif isinstance(result, HTTPResult):
                self.json(result.data, result.status)
            elif result is not None:
                self.json(result)
        except RestoreInProgress:
            self.json({"error": "A checkpoint is being restored."}, 503, headers={"Retry-After": "2"})
        except RequestError as error:
            self.json({"error": str(error)}, error.status, headers=error.headers)
        except (pages.PageError, uploads.UploadError, voice.VoiceError) as error:
            self.json({"error": str(error)}, error.status)
        except workers.WorkerStorageError:
            self.app.subsystem_status.failure("http", "storage_error")
            self.json({"error": "Hearth could not stop the worker."}, 500)
        except HearthError as error:
            self.json({"error": str(error)}, 400)
        except CLIENT_DISCONNECT:
            return
        except Exception:
            self.app.subsystem_status.failure("http", "handler_error")
            if self.response_status is not None:
                self.close_connection = True
                return
            message = route.storage_error or ("Hearth could not read workspace data." if self.command == "GET"
                                              else "Hearth could not update workspace data.")
            self.json({"error": message}, 500)
        else:
            if route.handler not in ("get_health", "get_status") and self.response_status in range(200, 400):
                self.app.subsystem_status.success("http")

    do_GET = do_POST = dispatch

    def send_error(self, code, message=None, explain=None):
        if code == 501:
            # The base server uses 501 for methods without a do_* method.
            self.dispatch()
        else:
            super().send_error(code, message, explain)

    def require_origin(self):
        origin = self.headers.get("Origin")
        if self.headers.get("Sec-Fetch-Site") not in (None, "none", "same-origin") or (
            origin is not None and not self.same_origin(origin)
        ):
            message = "Open Timeline from Hearth." if self.command == "GET" else "Send this request from Hearth."
            raise RequestError(message, 403)

    def require_ready(self):
        if self.app.restoring():
            raise RestoreInProgress

    def handle_route(self, route, request):
        handler = getattr(self, route.handler)
        timeout = route.lock_timeout
        if timeout is None:
            if not route.during_restore:
                self.require_ready()
            return handler(request)
        if not self.app.operation.acquire(timeout=timeout):
            self.require_ready()
            raise RequestError("Hearth is working on another action.", 409)
        try:
            self.require_ready()
            return handler(request)
        finally:
            self.app.operation.release()

    def read_body(self, route):
        mime = self.headers.get_content_type()
        if route.media == "json" and mime != "application/json":
            raise RequestError("Expected a JSON request.")
        if route.media == "audio" and mime not in voice.AUDIO_TYPES:
            raise RequestError("Use a WebM, Ogg, MP4, or WAV audio recording.", 415)
        if route.media == "multipart" and mime != "multipart/form-data":
            raise RequestError("Expected a multipart file upload.", 415)
        length = body_length(self.headers, route.limit)
        if route.media == "none":
            return None
        if not length:
            message = {"json": "Expected a JSON request.", "audio": "No audio recording was received.",
                       "multipart": "No attachment was received."}
            raise RequestError(message[route.media])
        self.connection.settimeout(30 if route.media == "multipart" else 15)
        if route.media != "json":
            return length
        try:
            body = read_json(self.rfile, length)
        except TimeoutError:
            raise RequestError("The request timed out.", 408) from None
        if not route.shape(body):
            raise RequestError("Invalid request fields.")
        return body

    def artifact_times(self, result):
        with self.app.storage.lock():
            return {**result, "timezone": saved(self.app.storage.load())["timezone"]}

    def post_scheduler_tick(self, request):
        try:
            return self.app.scheduler_tick()
        except HearthError:
            raise RequestError("Hearth could not run the scheduler tick.", 500) from None

    def post_stop(self, request):
        body = request.body
        if request.operation == "workers":
            turn_id = require_text(body["turn_id"], 40)
            identity = require_text(body["id"], 40) if "id" in body else None
            return self.app.workers.stop(turn_id, identity)
        return self.app.stop_reply(require_text(body["thread_id"], 40), require_text(body["reply_id"], 40))

    def post_chat(self, request):
        body = request.body
        identities = body.get("attachment_ids", [])
        prompt = body.get("message", "")
        prompt = "" if identities and not prompt.strip() else require_text(prompt, 4_000)
        try:
            events = self.app.enqueue(body.get("thread_id", MAIN), prompt, attachment_ids=identities, stoppable=True)
        except uploads.UploadError as error:
            raise RequestError(str(error)) from None
        return ChatStream(events)

    def post_browse_approve(self, request):
        body = request.body
        return ChatStream(self.app.enqueue(body["thread_id"], "", approval=require_text(body["id"], 40)))

    def post_self_update(self, request):
        body = request.body
        if request.operation == "settings":
            self.app.self_updates.configure(body["repository"], body["enabled"], body.get("required_checks"))
            return self.app.connection_info()
        try:
            return self.app.self_updates.act(request.operation, body["id"], body["thread_id"],
                                             body["head"], body.get("feedback", ""))
        except ConnectorError as error:
            raise HearthError(self_update.errors_for(error)) from None

    def post_browse_settings(self, request):
        self.app.connections.save_preferences("browsing", browserbase.settings(request.body))
        self.app.reload_agent(reset_brain=False)
        return self.app.agent.browsing

    def post_thread(self, request):
        body, operation = request.body, request.operation
        title = require_text(body["title"], 80) if operation == "rename" else None
        return self.app.update_thread(operation, body.get("thread_id"), title=title, message_id=body.get("message_id"))

    def post_skills(self, request):
        body, operation = request.body, request.operation
        library = self.app.agent.skills
        if operation == "try":
            with self.app.storage.lock():
                skill = library.require(self.app.storage.load(), identity=body["id"])
                return self.app.threads.create(title=skill["name"], skill={key: skill[key] for key in ("id", "name")})
        result, _ = library.mutate(operation, body)
        return result

    def post_action(self, request):
        action_id = require_text(request.body["id"], 40)
        if request.operation == "approve":
            with self.app.storage.lock():
                action = self.app.storage.load()["actions"].get(action_id, {})
            return (self.app.pages.approve_share(action_id) if action.get("kind") == "page_share"
                    else self.app.agent.approve(action_id))
        if request.operation == "redo":
            return self.app.replay_memory(action_id, redo=True)
        result = self.app.undo_action(action_id)
        return HTTPResult(result, 202) if result.get("status") == "restoring" else result

    def get_page(self, request):
        disposition = None
        csp = page_policy.CSP
        if "token" in request.params:
            raw = self.app.pages.shared(request.params["token"])
            csp = page_policy.PUBLIC_CSP
        else:
            version = request.params.get("version")
            row, raw = self.app.pages.document(request.params["id"], int(version) if version else None)
            if request.query.get("download") == ["1"]:
                name = quote(artifacts.filename(row["title"], "html"), safe="")
                disposition = f"attachment; filename*=UTF-8''{name}"
        self.response_headers(200, "text/html; charset=utf-8", len(raw), disposition=disposition,
                              page_csp=csp)
        self.wfile.write(raw)

    def post_pages(self, request):
        body, operation = request.body, request.operation
        identity = require_text(body["id"], 32)
        if operation == "revert":
            return self.app.pages.revert(identity, body["version"], body["current"])
        if operation == "share":
            return self.app.pages.request_share(identity, body["version"])
        if operation == "revoke":
            return self.app.pages.revoke(identity)
        return self.app.pages.save_box(identity, body["version"])

    def post_memory_review(self, request):
        review = self.app.memory_review
        if request.operation == "settings":
            return review.configure(request.body)
        if request.operation == "decision":
            return review.decide(request.body)
        return review.kick(force=True)

    def post_feed(self, request):
        if request.operation == "refresh":
            self.app.ideas.kick()
            result = self.app.feed.tick(force=True)
            timeline.record(self.app.storage, "feed", "Feed refresh requested",
                            {"thread_id": "", "thread_title": "Workspace"},
                            data={"detail": result["status"], "card_count": len(result["cards"])})
            return result
        return {"settings": self.app.feed.save_settings, "feedback": self.app.feed.feedback,
                "chat": self.app.feed.chat, "idea": self.app.ideas.respond}[request.operation](request.body)

    def post_proactivity(self, request):
        body, operation = request.body, request.operation
        if operation == "pass":
            return self.app.proactivity.tick(force=True)
        if operation == "settings":
            return self.app.proactivity.save_settings(body)
        if operation == "do":
            result, prompt = self.app.proactivity.update(operation, body)
            if prompt is not None:
                return ChatStream(self.app.enqueue(result["id"], prompt, source=proactivity.SOURCE))
            return result
        return self.app.proactivity.update(operation, body)

    def post_goal(self, request):
        operation = request.operation
        if operation == "delete":
            return self.app.agent.execute("goal_update", {**request.body, "delete": True})
        return self.app.agent.execute("goal_" + operation, request.body)

    def post_home(self, request):
        body, operation = request.body, request.operation
        service = self.app.home
        if operation == "refresh":
            if body["id"] == "weather":
                service.refresh_weather()
                return service.settings()
            result, _ = service.panels.refresh(body["id"])
            return result
        if operation == "chat":
            return service.panel_chat(body["id"])
        return {"layout": service.adjust, "checklist": service.toggle,
                "settings": service.save_settings}[operation](body)

    def post_upload(self, request):
        thread_id = request.query.get("thread", [MAIN])[0]
        content_type = self.headers.get("Content-Type", "")

        def receive(output):
            return receive_multipart(self.rfile, request.body, content_type, output, max_bytes=uploads.MAX_BYTES)

        return HTTPResult(self.app.uploads.stage(thread_id, receive), 201)

    def post_upload_box(self, request):
        return self.app.uploads.save_box(request.body["thread_id"], request.body["id"])

    def get_upload(self, request):
        params = request.query
        thread_id = params.get("thread", [MAIN])[0]
        identity = params.get("id", [""])[0]
        try:
            if request.operation == "detail":
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

    def post_approvals(self, request):
        body, operation = request.body, request.operation
        if operation == "settings":
            result = approvals.settings(self.app.storage, body)
            self.app.memory_index.changed()
            return result
        return approvals.decide(self.app.agent, require_text(body["id"], 40), operation, body.get("changes"))

    def post_event_automations(self, request):
        if request.operation == "delete":
            return self.app.agent.execute("delete_event_automation", request.body)
        return event_automations.mutate(self.app, request.operation, request.body)

    def post_tasks(self, request):
        body, operation = request.body, request.operation
        if operation == "delete":
            result = self.app.agent.execute("delete_recurring_task", body)
            action = result["action"]
            if action["status"] == "pending":
                with self.app.storage.lock():
                    self.app.threads.append(MAIN, "assistant", action["title"] + "?", action_ids=[action["id"]])
            return result
        result = tasks.mutate(self.app.storage, operation, body)
        if operation == "run":
            self.app.task_runner.kick()
        return result

    def post_inbox(self, request):
        body, operation = request.body, request.operation
        if operation == "poll":
            if body.get("force") is False:
                raise RequestError("Invalid inbox request.")
            return {"processed": self.app.inbox.poll(force=bool(body), manual=bool(body))}
        return self.app.inbox.update(operation, body)

    def post_reminders(self, request):
        body, operation = request.body, request.operation
        if operation == "settings":
            return self.app.reminders.save(body)
        if operation == "test":
            return self.app.reminders.test(body.get("channel"))
        if operation in ("inspect", "action"):
            return self.app.reminders.use_token(body["token"], apply=operation == "action")
        if operation == "cancel":
            return self.app.reminders.cancel(body["id"])
        with self.app.storage.lock():
            state = self.app.storage.load()
            result = scheduler.add_job(state, **body)
            self.app.storage.save(state)
        return result

    def post_artifact(self, request):
        body, operation = request.body, request.operation
        service = self.app.artifacts
        if operation == "ask":
            result = file_questions.ask(self.app.agent, body)
            if result.get("source"):
                timeline.record(self.app.storage, "artifact", "Answered a question about Box files",
                                {"thread_id": "", "thread_title": "Workspace"},
                                provider="box", data={"citation_count": len(result["citations"])})
            return result
        if operation == "settings":
            self.app.connections.save_preferences("artifacts", box.settings(body))
            self.app.reload_agent(reset_brain=False)
            self.app.memory_sync.request("startup")
            return service.info()
        if operation == "undo":
            return service.undo(require_text(body["id"], 40))
        return service.mutate(operation, body)

    def post_call_token(self, request):
        return self.app.call_token()

    def post_call_report(self, request):
        result = voice_call.save_report(self.app.threads, request.body)
        if self.app.agent.memory["include_chat"]:
            self.app.memory_sync.request()
        return result

    def post_call_query(self, request):
        body = request.body
        with self.app.operation:
            self.require_ready()
            events = self.app.enqueue(body["thread_id"], require_text(body["query"], 4_000), source=voice_call.SOURCE)
        return self.call_reply(events)

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

    def post_voice(self, request):
        thread_id = request.query.get("thread", [None])[0]
        whisper = request.operation == "transcribe"
        if whisper:
            try:
                data = self.rfile.read(request.body)
            except TimeoutError:
                raise RequestError("The audio upload timed out.", 408) from None
            if len(data) != request.body:
                raise RequestError("The audio upload was interrupted.")
            connection = self.app.memory_index.hf_entry(self.app.agent.config)
            language = request.query.get("language", ["auto"])[0]
            text = voice.transcribe(self.app.gateway, connection, data, self.headers.get_content_type(), language)
        else:
            text = voice.clean_transcript(require_text(request.body["text"], 4000))
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
        return {"text": text}

    def post_connections(self, request):
        body, operation = request.body, request.operation
        if operation == "rescan":
            self.app.scan_connections(sync_memory=True)
        elif operation == "test":
            self.app.connections.test(body["provider"])
            self.app.connection_state = self.app.connections.report()
        else:
            previous = self.app.memory_index.target(self.app.agent.config)
            self.app.connections.save(body["provider"], body["value"])
            self.app.reload_agent(reset_brain=False)
            if previous != self.app.memory_index.target(self.app.agent.config):
                self.app.memory_sync.request("startup")
        return self.app.connection_info()

    def post_brain(self, request):
        body, operation = request.body, request.operation
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

    def post_memory(self, request):
        body, operation = request.body, request.operation
        agent = self.app.agent
        if operation == "search":
            return agent.memory_search(**body)
        if operation == "sync":
            return self.app.memory_sync.request("sync")
        if operation == "reindex":
            if self.app.memory_index.available(agent.config)["pinecone"]:
                return self.app.memory_sync.request("rebuild")
            return self.app.start_reindex()
        if operation == "forget":
            return self.app.forget_memory(body)
        storage = self.app.storage
        with storage.lock():
            if operation == "profile":
                current = memory.profile_record(storage)
                if body["revision"] != current["revision"]:
                    raise HearthError("The profile changed. Reload Memory before saving.")
                profile = memory.normalize_profile(body["profile"])
                data, _, _ = memory.parse(memory.PROFILE_NOTE, storage.read(memory.PROFILE_NOTE)
                                          if current["revision"] else "")
                data["profile"] = profile
                note = memory.render(data, "\n" + body["notes"].strip() + "\n")
                return agent.write_memory_notes([{"path": memory.PROFILE_NOTE, "content": note}])
            path = memory.resolve(storage, path=body["path"])
            if body["revision"] != memory.revision(storage.read(path)):
                raise HearthError("The note changed. Reload it before saving.")
            if operation == "write":
                return agent.write_memory_notes([{"path": path, "content": body["content"]}])
            return agent.move_memory_note(body["target"], path=path)

    def post_preference_test(self, request):
        body = request.body
        agent = self.app.agent
        if request.operation == "search":
            return agent.run_search(body["query"], search.settings(body["selection"]))
        query = redact_text(require_text(body["query"], 1_000))
        filters = {key: body[key] for key in ("kind", "thread_id") if key in body}
        return self.app.memory_index.run(agent.config, recall.settings(body["selection"]), query,
                                         filters=filters, budget=10)

    def post_preference_settings(self, request):
        feature = request.operation
        if feature == "memory" and self.app.reindex_running():
            raise HearthError("Wait for memory reindexing to finish before saving settings.")
        selection = (recall if feature == "memory" else search).settings(request.body)
        self.app.connections.save_preferences(feature, selection)
        self.app.reload_agent(reset_brain=False)
        if feature == "memory":
            self.app.memory_sync.request()
            return self.app.memory_info()
        return self.app.search_info()

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
        self.response_headers(200, "text/event-stream")
        self.wfile.flush()
        for packet in packets:
            if packet is None:
                self.wfile.write(b": Hearth is working\n\n")
            else:
                name, data = packet
                self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode("utf-8"))
            self.wfile.flush()


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
