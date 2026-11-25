"""Coalesce memory changes into background Pinecone sync jobs."""

import threading
import time

from . import pinecone, recall
from .connectors import ConnectorError
from .storage import HearthError

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

    def request(self, mode="change"):
        if not self.app.memory_index.available(self.app.agent.config)["pinecone"]:
            if mode in ("sync", "rebuild"):
                raise HearthError("Connect Pinecone in Connections first.")
            return
        with self.lock:
            manual = mode in ("sync", "rebuild")
            if manual or mode == "startup":
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
                self.job = job = {**self.job, "status": "failed", "error": recall.error_message(error)}
                transient = isinstance(error, OSError) or (isinstance(error, ConnectorError)
                            and error.status in pinecone.TRANSIENT and not error.unsupported)
                with self.lock:
                    self.retry_at = time.monotonic() + (self.retry_delay if transient else 60)
                    if transient:
                        self.retry_delay = min(self.retry_delay * 2, 60)
                    if self.pending not in ("sync", "rebuild", "startup"):
                        if transient or self.pending == "change":
                            # A retry retains startup inspection and backfill behavior.
                            self.pending = mode if mode in ("startup", "change") else "startup"
                            self.defer()
                        self.running = False
                        stop = True
                    else:
                        stop = False
                self.log(agent, job, failed=True)
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
                if result["work"] or mode != "change":
                    self.log(agent, self.job)

    def save_index(self, entry, info):
        with self.app.operation:
            self.app.connections.save_pinecone_index(entry, info)

    def refresh_box(self):
        service = self.app.artifacts
        connection = service.connection()
        if not connection:
            return
        scope = [connection, service.config()["folder_name"]]
        index = self.app.memory_index
        cache = index.read_index(index.box_path)
        previous = cache.get("rows", {}) if cache.get("scope") == scope else {}
        try:
            rows = service.memory_rows(previous)
            if rows is not None:
                index.replace_box_artifacts({"scope": scope, "rows": rows})
        except (HearthError, OSError):
            # The last Box snapshot and local copies remain available.
            pass

    def log(self, agent, job, failed=False):
        title = {"startup": "Pinecone startup backfill", "sync": "Pinecone memory sync",
                 "rebuild": "Pinecone index rebuilt", "change": "Pinecone memory updated"}[job["mode"]]
        if failed:
            title = "Pinecone memory sync failed"
        try:
            agent.log_activity("memory", title, provider="pinecone", error=failed,
                               data={**job, "namespace": agent.config["pinecone"]["namespace"]})
        except OSError:
            pass
