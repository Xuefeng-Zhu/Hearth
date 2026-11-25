"""Bounded delegation for chat and recurring turns."""

import json
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .gateway_tools import redact_text
from .storage import HearthError, new_id
from .threads import compact

DEFAULT_CAP = 4
MAX_WORKERS = 6
TIMEOUT = 75
TOOL_LIMIT = 4
MODEL_LIMIT = TOOL_LIMIT + 1
OUTPUT_TOKENS = 1536
ACTIVE = {"queued", "running", "waiting_approval"}


def validate_cap(value):
    if type(value) is not int or not 1 <= value <= MAX_WORKERS:
        raise HearthError("Choose 1 to 6 parallel workers.")
    return value


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def validate_tasks(tasks, available):
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= MAX_WORKERS:
        raise HearthError("Delegate between one and six independent tasks.")
    validated = []
    for task in tasks:
        if not isinstance(task, dict) or task.keys() - {"title", "instructions", "tools"}:
            raise HearthError("Each worker needs a title and instructions.")
        title, instructions = task.get("title"), task.get("instructions")
        if not isinstance(title, str) or not title.strip() or len(title) > 100:
            raise HearthError("Worker titles must be between 1 and 100 characters.")
        if not isinstance(instructions, str) or not instructions.strip() or len(instructions) > 2_000:
            raise HearthError("Worker instructions must be between 1 and 2,000 characters.")
        names = task.get("tools")
        if "tools" in task and (not isinstance(names, list) or len(names) > len(available) or
                                any(not isinstance(name, str) or name not in available for name in names)):
            raise HearthError("Workers can use only tools available to the current turn.")
        validated.append((compact(redact_text(title), 100), redact_text(instructions).strip(), names))
    return validated


class Halt(Exception):
    pass


class Worker:
    def __init__(self, pool, turn_id, origin, title, event):
        self.pool = pool
        self.event = event
        self.queued = time.monotonic()
        self.deadline = self.queued + pool.timeout
        self.started = None
        self.terminal = threading.Event()
        self.row = {**origin, "id": new_id(), "turn_id": turn_id, "title": title, "status": "queued",
                    "queued_at": timestamp(), "steps": [], "elapsed_ms": 0}
        self.data = None

    @property
    def identity(self):
        return self.row["id"]

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if self.terminal.is_set() or remaining <= 0:
            raise Halt
        return remaining

    def step(self, status, *, label=None, detail=None):
        with self.pool.condition:
            self.remaining()
            steps = self.row["steps"]
            if label is not None:
                steps = [*steps, {"label": compact(redact_text(label), 180), "at": timestamp(), "status": status}]
            else:
                steps = [*steps[:-1], {**steps[-1], "status": status,
                         **({"detail": compact(redact_text(detail), 180)} if detail else {})}]
            waiting = status == "waiting_approval"
            self.pool.publish(self, {
                "status": "waiting_approval" if waiting else "running",
                "steps": steps, "summary": "Review the approval card." if waiting else "Working on the assignment.",
            })

    def wait_approval(self, identity):
        while True:
            remaining = self.remaining()
            row = self.pool.storage.load()["actions"].get(identity)
            if not row:
                raise HearthError("The approval is no longer available.")
            if row["status"] not in {"pending", "changing", "sending"}:
                return row
            self.terminal.wait(min(0.15, remaining))


def withdraw(state, worker, reason, now):
    from . import approvals

    withdrawn = []
    for row in state["actions"].values():
        if row.get("worker_id") == worker["id"] and row["status"] == "pending":
            row.update(status="cancelled", updated_at=now.isoformat(timespec="seconds"),
                       result={"message": reason})
            if row.get("tool"):
                approvals.log(state, row, "Cancelled", now)
            state.get("task_notifications", {}).pop(row["id"], None)
            withdrawn.append(row)
    return withdrawn


class Pool:
    def __init__(self, storage, cap=DEFAULT_CAP, *, timeout=TIMEOUT):
        self.storage = storage
        self.cap = cap
        self.timeout = timeout
        self.condition = threading.Condition()
        self.executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="hearth-worker")
        self.queue = deque()
        self.active = {}
        self.running = 0

    def recover(self):
        with self.storage.lock():
            state = self.storage.load()
            interrupted = [row for row in state.get("workers", {}).values() if row["status"] in ACTIVE]
            for row in interrupted:
                reason = "Hearth restarted before this worker finished."
                row.update(status="failed", summary=reason, finished_at=timestamp())
                if not row.get("task_run"):
                    withdraw(state, row, reason, datetime.now(timezone.utc))
            if interrupted:
                self.storage.save(state)

    def configure(self, cap):
        with self.condition:
            self.cap = cap
            self.dispatch()

    def busy(self):
        with self.condition:
            return bool(self.active or self.running)

    def control(self, identity):
        if identity:
            with self.condition:
                return self.active.get(identity)

    def publish(self, worker, changes, *, withdraw_reason=None):
        row = {**worker.row, **changes,
               "elapsed_ms": round((time.monotonic() - (worker.started or worker.queued)) * 1_000)}
        withdrawn = []
        with self.storage.lock():
            state = self.storage.load()
            state.setdefault("workers", {})[worker.identity] = row
            if withdraw_reason:
                withdrawn = withdraw(state, row, withdraw_reason, datetime.now(timezone.utc))
            self.storage.save(state)
        worker.row = row
        worker.event("worker", row)
        for action in withdrawn:
            worker.event("action", action)

    def finish(self, worker, status, summary, *, data=None, withdraw_pending=False):
        if worker.terminal.is_set():
            return
        worker.terminal.set()
        worker.data = data
        changes = {"status": status, "summary": summary, "finished_at": timestamp()}
        if status != "done" and (steps := worker.row["steps"]) and steps[-1]["status"] in ACTIVE:
            changes["steps"] = [*steps[:-1], {**steps[-1], "status": status, "detail": summary}]
        self.publish(worker, changes, withdraw_reason=summary if withdraw_pending else None)
        self.active.pop(worker.identity, None)
        self.condition.notify_all()

    def expire(self, worker):
        self.finish(worker, "failed", "Worker timed out.",
                    withdraw_pending=not worker.row.get("task_run"))

    def dispatch(self):
        while self.queue and self.running < self.cap:
            worker, task, execute = self.queue.popleft()
            if worker.terminal.is_set():
                continue
            if time.monotonic() >= worker.deadline:
                self.expire(worker)
                continue
            worker.started = time.monotonic()
            self.running += 1
            self.publish(worker, {"status": "running", "started_at": timestamp()})
            self.executor.submit(self.run_worker, worker, task, execute)

    def run_worker(self, worker, task, execute):
        status, summary, data = "failed", "The worker could not finish.", None
        try:
            worker.remaining()
            data = execute(worker, task)
            status, summary = "done", compact(data["result"]["summary"], 240)
        except Halt:
            summary = "Worker timed out."
        except HearthError as error:
            summary = compact(redact_text(str(error)), 240)
        finally:
            with self.condition:
                self.running -= 1
                if time.monotonic() >= worker.deadline:
                    self.expire(worker)
                else:
                    self.finish(worker, status, summary, data=data, withdraw_pending=status == "failed")
                self.dispatch()

    def run(self, tasks, turn_id, origin, event, execute):
        batch = [Worker(self, turn_id, origin, title, event) for title, _, _ in tasks]
        with self.condition:
            for worker, task in zip(batch, tasks):
                self.active[worker.identity] = worker
                self.publish(worker, {})
                self.queue.append((worker, task, execute))
            self.dispatch()
            while waiting := [worker for worker in batch if not worker.terminal.is_set()]:
                now = time.monotonic()
                for worker in waiting:
                    if worker.deadline <= now:
                        self.expire(worker)
                self.queue = deque(item for item in self.queue if not item[0].terminal.is_set())
                remaining = min(worker.deadline for worker in waiting) - now
                if remaining > 0:
                    self.condition.wait(remaining)
        return batch

    def stop(self, turn_id, identity=None):
        with self.condition:
            stopped = []
            for worker in list(self.active.values()):
                if worker.row["turn_id"] == turn_id and (identity is None or worker.identity == identity):
                    self.finish(worker, "cancelled", "Stopped by the user.", withdraw_pending=True)
                    stopped.append(worker.row)
            self.queue = deque(item for item in self.queue if not item[0].terminal.is_set())
            return {"workers": stopped}


def tool_text(result):
    # Keep later model calls bounded even when a connector returns a large document.
    text = json.dumps(result, ensure_ascii=False)
    if len(text) <= 12_000:
        return text
    return json.dumps({"truncated": True, "preview": text[:12_000]}, ensure_ascii=False)
