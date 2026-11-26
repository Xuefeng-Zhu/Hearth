"""Bounded, process-local outcomes for workspace diagnostics."""

from threading import Lock

from .storage import iso


class SubsystemStatus:
    def __init__(self):
        self.lock = Lock()
        self.rows = {name: {"last_success": None, "last_failure": None,
                            "last_failure_code": None, "failure_count": 0}
                     for name in ("http", "scheduler", "box_recall")}
        self.rows["box_recall"]["stale"] = False

    def success(self, subsystem, *, at=None):
        with self.lock:
            row = self.rows[subsystem]
            row["last_success"] = at or iso()
            if "stale" in row:
                row["stale"] = False

    def failure(self, subsystem, code, *, last_success=None):
        with self.lock:
            row = self.rows[subsystem]
            row.update(last_failure=iso(), last_failure_code=code, failure_count=row["failure_count"] + 1)
            if "stale" in row:
                row.update(stale=True, last_success=last_success)

    def snapshot(self):
        with self.lock:
            return {name: row.copy() for name, row in self.rows.items()}
