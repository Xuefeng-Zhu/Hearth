import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from hearth.storage import Storage
from hearth.threads import MAIN_ORIGIN
from hearth.workers import ACTIVE
from test_workers import WorkerGateway, fixture_app


STORAGE_ERROR = "Hearth could not save the worker's status."
ASSIGNMENTS = [("Faulted worker", "", None), ("Healthy worker", "", None)]


class WorkerStorageTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = Storage(directory.name)
        self.app = fixture_app(self.storage, WorkerGateway())
        self.pool = self.app.workers
        self.pool.configure(1)
        self.pool.timeout = 5
        self.addCleanup(self.pool.executor.shutdown)
        self.save = self.storage.save

    def checkpoint(self):
        with self.storage.lock():
            self.storage.write("USER.md", "Before the batch")
            checkpoint = self.app.checkpoints.create("Before the batch")
            self.storage.write("USER.md", "After the checkpoint")
            state = self.storage.load()
            state["actions"]["undo"] = {"id": "undo", "kind": "checkpoint", "checkpoint": checkpoint}
            self.save(state)

    def assert_can_restore(self):
        restored = threading.Event()
        restore_checkpoint = self.app.restore_checkpoint

        def restore(action):
            try:
                restore_checkpoint(action)
            finally:
                restored.set()

        with patch.object(self.app, "restore_checkpoint", side_effect=restore):
            self.app.start_restore("undo")
            self.assertTrue(restored.wait(3), "Checkpoint restore did not finish")
        self.assertIsNone(self.app.restore)
        self.assertEqual(self.storage.read("USER.md"), "Before the batch")

    def assert_write_failure_recovers(self, status, previous_status):
        self.checkpoint()
        events, attempts, executed = [], [], []
        waiting = threading.Event()
        release = threading.Event()
        baseline = self.pool.running
        wait = self.pool.condition.wait

        def fail_once(state):
            for row in state.get("workers", {}).values():
                if not attempts and row["title"] == "Faulted worker" and row["status"] == status:
                    attempts.append(self.storage.load().get("workers", {}).get(row["id"], {}).get("status"))
                    raise OSError("Traceback: failed writing /fixture/state.json")
            self.save(state)

        def observe_wait(timeout):
            waiting.set()
            return wait(timeout)

        def execute(worker, task):
            executed.append(task[0])
            if task == ASSIGNMENTS[0]:
                worker.step("running", label="Review the findings")
                release.wait(3)
            return {"result": {"summary": "Findings from the worker."}}

        with (ThreadPoolExecutor(max_workers=1) as caller,
              patch.object(self.storage, "save", side_effect=fail_once),
              patch.object(self.pool.condition, "wait", side_effect=observe_wait),
              patch.object(self.pool.condition, "notify_all", wraps=self.pool.condition.notify_all) as notify):
            result = caller.submit(self.pool.run, ASSIGNMENTS, "turn", MAIN_ORIGIN,
                                   lambda *event: events.append(event), execute)
            try:
                if status == "done":
                    self.assertTrue(waiting.wait(2), "Batch did not reach its condition wait")
            finally:
                release.set()
            failed, healthy = result.result(timeout=2)
            self.assertGreaterEqual(notify.call_count, 2)

        self.assertEqual(attempts, [previous_status])
        expected = ["Faulted worker", "Healthy worker"] if status == "done" else ["Healthy worker"]
        self.assertEqual(executed, expected)
        self.assertTrue(failed.terminal.is_set())
        self.assertIsNone(failed.data)
        self.assertEqual(failed.row["status"], "failed")
        self.assertEqual(failed.row["summary"], STORAGE_ERROR)
        self.assertEqual(healthy.row["status"], "done")
        self.assertEqual(self.pool.running, baseline)
        self.assertFalse(self.pool.active)
        self.assertFalse(self.pool.queue)
        state = self.storage.load()
        self.assertIn("undo", state["actions"])
        self.assertFalse(any(row["status"] in ACTIVE for row in state["workers"].values()))
        self.assertEqual(state["workers"][failed.identity], failed.row)
        self.assertEqual("started_at" in failed.row, status == "done")
        if status == "done":
            step, = failed.row["steps"]
            self.assertEqual((step["label"], step["status"], step["detail"]),
                             ("Review the findings", "failed", STORAGE_ERROR))
        self.assertIn(("worker", failed.row), events)
        self.assertNotIn("Traceback", repr(events))
        self.assertNotIn("/fixture/state.json", repr(events))
        self.assertEqual(self.pool.stop("turn"), {"workers": []})
        self.assert_can_restore()

    def test_queue_write_failure(self):
        self.assert_write_failure_recovers("queued", None)

    def test_start_write_failure(self):
        self.assert_write_failure_recovers("running", "queued")

    def test_finish_write_failure(self):
        self.assert_write_failure_recovers("done", "running")

    def test_rejected_submission_does_not_consume_a_slot(self):
        submit = self.pool.executor.submit
        executed = []

        def reject_first_job(function, worker, *args):
            future = submit(function, worker, *args)
            if worker.row["title"] == "Faulted worker":
                raise RuntimeError("Executor rejected the submission after enqueuing it")
            return future

        def execute(_, task):
            executed.append(task[0])
            return {"result": {"summary": "Done."}}

        with patch.object(self.pool.executor, "submit", side_effect=reject_first_job):
            batch = self.pool.run(ASSIGNMENTS, "turn", MAIN_ORIGIN, lambda *_: None, execute)

        self.assertEqual(executed, ["Healthy worker"])
        self.assertEqual([worker.row["status"] for worker in batch], ["failed", "done"])
        self.assertCountEqual(self.storage.load()["workers"].values(), [worker.row for worker in batch])
        self.assertEqual(self.pool.running, 0)
        self.assertFalse(self.pool.busy())

    def test_stop_all_cancels_remaining_workers_after_write_failure(self):
        ready = threading.Event()
        release = threading.Event()

        def execute(_, task):
            self.assertEqual(task, ASSIGNMENTS[0])
            ready.set()
            release.wait(3)
            return {"result": {"summary": "Late findings."}}

        def fail_cancel(state):
            if any(row["title"] == "Faulted worker" and row["status"] == "cancelled"
                   for row in state["workers"].values()):
                raise OSError("Traceback: failed writing /fixture/state.json")
            self.save(state)

        with ThreadPoolExecutor(max_workers=1) as caller:
            result = caller.submit(self.pool.run, ASSIGNMENTS, "turn", MAIN_ORIGIN, lambda *_: None, execute)
            try:
                self.assertTrue(ready.wait(2))
                with patch.object(self.storage, "save", side_effect=fail_cancel):
                    stopped = self.pool.stop("turn")["workers"]
                self.assertEqual([row["status"] for row in stopped], ["failed", "cancelled"])
                self.assertEqual(stopped[0]["summary"], STORAGE_ERROR)
                self.assertEqual([worker.row for worker in result.result(timeout=2)], stopped)
                self.assertTrue(self.pool.busy())
            finally:
                release.set()

        self.pool.executor.shutdown()
        self.assertFalse(self.pool.busy())
        self.assertCountEqual(self.storage.load()["workers"].values(), stopped)

    def test_stop_all_reconciles_after_writes_resume(self):
        events = []

        def fail_terminal_writes(state):
            if any(row["status"] in {"done", "failed"} for row in state.get("workers", {}).values()):
                raise OSError("Traceback: failed writing /fixture/state.json")
            self.save(state)

        def execute(worker, _):
            with self.storage.lock():
                state = self.storage.load()
                state["actions"]["proposal"] = {"id": "proposal", "status": "pending", "worker_id": worker.identity}
                self.storage.save(state)
            return {"result": {"summary": "Findings from the worker."}}

        with patch.object(self.storage, "save", side_effect=fail_terminal_writes):
            failed, = self.pool.run(ASSIGNMENTS[:1], "turn", MAIN_ORIGIN,
                                    lambda *event: events.append(event), execute)
            self.assertEqual(self.pool.stop("turn"), {"workers": []})
            self.assertFalse(self.pool.busy())

        state = self.storage.load()
        self.assertEqual(state["workers"][failed.identity]["status"], "running")
        self.assertEqual(state["actions"]["proposal"]["status"], "pending")
        self.assertIn(("worker", failed.row), events)
        self.assertEqual(failed.row["summary"], STORAGE_ERROR)
        self.assertEqual(self.pool.stop("turn"), {"workers": []})
        state = self.storage.load()
        self.assertEqual(state["workers"][failed.identity], failed.row)
        self.assertEqual(state["actions"]["proposal"]["status"], "cancelled")
