"""Coalesce memory changes into background Pinecone sync jobs."""

import threading
import time
from datetime import datetime, timezone

from . import pinecone, recall, timeline
from .connectors import ConnectorError
from .gateway_tools import scrub
from .storage import HearthError, iso, new_id
from .threads import MAIN_ORIGIN

MODES = ("change", "startup", "sync", "rebuild")


class MemorySync:
    def __init__(self, app):
        self.app = app
        self.lock = threading.Lock()
        self.job = None
        self.pending = None
        self.running = False
        self.retry_at = 0
        self.retry_delay = 2
        self.retry_timer = None
        self.retry_target = None

    def request(self, mode="change"):
        config = self.app.agent.config
        if not self.app.memory_index.available(config)["pinecone"]:
            if mode in ("sync", "rebuild"):
                raise HearthError("Connect Pinecone in Settings → Connections first.")
            return
        with self.lock:
            manual = mode in ("sync", "rebuild")
            target = self.app.memory_index.target(config)
            if manual or target != self.retry_target:
                self.retry_at = 0
            if self.retry_timer:
                self.retry_timer.cancel()
                self.retry_timer = None
            if self.pending is None or MODES.index(mode) > MODES.index(self.pending):
                self.pending = mode
            if not self.running and time.monotonic() < self.retry_at:
                self.defer()
                return self.job
            if not self.running:
                self.running = True
                self.job = self.new_job(self.pending)
                threading.Thread(target=self.work, name="pinecone-sync", daemon=True).start()
            return self.job

    @staticmethod
    def new_job(mode):
        return {"status": "running", "mode": mode, "phase": "connecting",
                "total": 0, "upserted": 0, "unchanged": 0, "deleted": 0, "work": 0}

    def defer(self):
        delay = max(0, self.retry_at - time.monotonic())
        self.retry_timer = threading.Timer(delay, self.request)
        self.retry_timer.daemon = True
        self.retry_timer.start()

    def work(self):
        while True:
            with self.lock:
                mode = self.pending
                if mode is None:
                    self.running = False
                    return
                self.pending = None
                self.job = self.new_job(mode)
            agent = self.app.agent
            if not self.app.memory_index.available(agent.config)["pinecone"]:
                self.job = None
                continue
            previous_check = self.app.connections.checks.get("pinecone")
            if mode != "change":
                self.refresh_box()

            def progress(**fields):
                self.job = {**self.job, "phase": "syncing", **fields}

            started = time.monotonic()
            try:
                result = self.app.memory_index.sync_pinecone(
                    agent.config, agent.memory, progress=progress, save_index=self.save_index,
                    inspect=mode != "change", rebuild=mode == "rebuild",
                )
            except (HearthError, OSError) as error:
                transient = isinstance(error, OSError) or (
                    isinstance(error, ConnectorError) and not error.unsupported and (
                        error.status in pinecone.TRANSIENT[1:] or str(error) == "The gateway is unavailable."
                    )
                )
                self.job = job = {**self.job, "status": "failed", "error": recall.error_message(error),
                                  "retrying": transient}
                self.log(agent, job, failed=True)
                with self.lock:
                    target = self.app.memory_index.target(agent.config)
                    same_target = target == self.app.memory_index.target(self.app.agent.config)
                    if same_target:
                        self.retry_target = target
                        self.retry_at = time.monotonic() + (self.retry_delay if transient else 300)
                        if transient:
                            self.retry_delay = min(self.retry_delay * 2, 60)
                    stop = same_target and self.pending not in ("sync", "rebuild")
                    if stop:
                        if transient or self.pending is not None:
                            # A retry retains startup inspection and backfill behavior.
                            if self.pending is None or self.pending == "change":
                                self.pending = mode if mode in ("startup", "change") else "startup"
                            self.defer()
                        self.running = False
                if stop:
                    return
            else:
                if previous_check:
                    with self.app.operation:
                        same_target = self.app.memory_index.target(agent.config) == self.app.memory_index.target(self.app.agent.config)
                        if same_target and self.app.connections.clear_pinecone_failure(previous_check):
                            self.app.connection_state = self.app.connections.report()
                self.retry_at, self.retry_delay = 0, 2
                self.job = {**self.job, **result, "status": "complete",
                            "latency_ms": round((time.monotonic() - started) * 1_000)}
                if result["work"] or mode != "change" or self.retry_target:
                    self.log(agent, self.job)
                self.retry_target = None

    def save_index(self, entry, info):
        with self.app.operation:
            self.app.connections.save_pinecone_index(entry, info)

    def refresh_box(self):
        service = self.app.artifacts
        index = self.app.memory_index
        status = self.app.subsystem_status
        last_success = None
        try:
            scope = service.box_scope()
            epoch = service.epoch
            if not scope[0] or self.app.restoring():
                return
            cache = index.read_index(index.box_path)
            if cache.get("scope") != list(scope):
                cache = {}
            try:
                saved_at = datetime.fromisoformat(cache.get("last_success", ""))
                if saved_at.tzinfo == timezone.utc:
                    last_success = iso(saved_at)
            except (TypeError, ValueError):
                pass
            rows, incomplete = service.memory_rows(cache.get("rows", {}))
            with self.app.operation:
                if scope != service.box_scope() or epoch != service.epoch or self.app.restoring():
                    return
                if rows is not None:
                    checked_at = last_success if incomplete else iso()
                    index.replace_box_artifacts({"scope": list(scope), "rows": rows, "last_success": checked_at})
        except OSError:
            status.failure("box_recall", "storage_error", last_success=last_success)
        except Exception:
            status.failure("box_recall", "refresh_failed", last_success=last_success)
        else:
            if incomplete:
                status.failure("box_recall", "refresh_failed", last_success=last_success)
            elif rows is not None:
                status.success("box_recall", at=checked_at)

    def log(self, agent, job, failed=False):
        title = {"startup": "Pinecone startup backfill", "sync": "Pinecone memory sync",
                 "rebuild": "Pinecone index rebuilt", "change": "Pinecone memory updated"}[job["mode"]]
        if failed:
            title = "Pinecone memory sync will retry" if job["retrying"] else "Pinecone memory sync failed"
        elif job["mode"] == "startup" and not job["work"]:
            title = "Pinecone startup check"
        config = agent.config["pinecone"]
        data = scrub({**job, "namespace": config["namespace"], "index": config["index"]})
        try:
            storage = self.app.storage
            with storage.lock():
                state = storage.load()
                activity = state.setdefault("activity", [])
                if failed:
                    last = next((row["data"] for row in reversed(activity) if timeline.pinecone_sync(row, config)), {})
                    if last.get("error") == data["error"] and bool(last.get("retrying")) == job["retrying"]:
                        return
                activity.append(timeline.entry("memory", title, MAIN_ORIGIN, id=new_id(), at=iso(),
                                               provider="pinecone", error=failed and not job["retrying"], data=data))
                storage.save(state)
        except OSError:
            pass
