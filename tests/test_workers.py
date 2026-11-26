import asyncio
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from hearth import approvals, browserbase, tasks, workers
from hearth.agent import TURN_MEMORY, tool_call
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import ConnectorError, Gateway, read_config
from hearth.server import Application
from hearth.storage import ROOT, HearthError, Storage
from hearth.threads import MAIN_ORIGIN
from test_skills import playbook

PROMPT = "Use parallel workers to compare notes on grants, venues, and equipment."
ASSIGNMENTS = [
    {"title": title, "instructions": f"Summarize the public findings about {title.lower()}.", "tools": ["memory_read"]}
    for title in ["Grants", "Venues", "Equipment"]
]


class WorkerGateway(Gateway):
    def __init__(self, *, assignments=ASSIGNMENTS, hold=None):
        self.assignments = assignments
        self.hold = hold
        self.results = []
        self.limits = []

    def discover(self):
        return {"huggingface": ["conn_fixture"]}, {"huggingface"}

    def request(self, path, body, headers, timeout, *, method=None):
        raise ConnectorError("No upstream request in the worker fixture.", 404, missing_connection=True)

    def completion(self, model, messages, tools, emit, **limits):
        worker = (TURN_MEMORY.get() or {}).get("worker")
        if not worker:
            if not tools:
                return {"role": "assistant", "content": "Fixture summary."}
            if messages[-1]["role"] == "tool":
                result = json.loads(messages[-1]["content"])
                self.results = result["workers"]
                return {"role": "assistant", "content": "Combined findings\n\n" + "\n".join(
                    f"- {row['title']} · {row['summary']}" for row in self.results)}
            return tool_call("spawn_workers", {"tasks": self.assignments})
        self.limits.append(limits)
        title = worker.row["title"]
        if messages[-1]["role"] == "tool":
            tool_result = json.loads(messages[-1]["content"])
            message = tool_result.get("message", "").strip() or f"{title} research finished."
            return {"role": "assistant", "content": json.dumps({"summary": message,
                    "sources": ["https://example.org/public-source"]})}
        if title.startswith("Slow") and self.hold is not None:
            self.hold.wait(40)
            return {"role": "assistant", "content": "Finished the slow fixture."}
        if title == "Playbook":
            return tool_call("skill_create", {
                "name": "Prepare for rehearsal", "description": "Check the rehearsal space.",
                "content": playbook("Prepare for rehearsal")})
        if title == "Browser":
            return tool_call("browse_session", {"url": "https://example.org", "steps": []})
        return tool_call("memory_read", {"path": "topics/thanksgiving.md"})


def fixture_app(storage, gateway):
    app = Application(storage, LocalCheckpoints(storage), read_config(ROOT / "config/connectors.json"), gateway=gateway)
    app.scan_connections()
    return app


def collect(events, until=None):
    rows = []
    while packet := events.get(timeout=6):
        rows.append(packet)
        if until and until(*packet):
            break
    return rows


class PoolTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = Storage(directory.name)

    def add_batch(self, pool, identity, count, run):
        events, result = [], []

        def batch():
            result.extend(pool.run([(f"Task {i}", "", None) for i in range(count)],
                                   identity, MAIN_ORIGIN, lambda _, row: events.append(row), run))

        thread = threading.Thread(target=batch, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 4)
        return thread, events, result

    def test_global_cap_and_queued_dispatch(self):
        pool = workers.Pool(self.storage, cap=2, timeout=4)
        self.addCleanup(pool.executor.shutdown)
        ready = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        active = 0
        peak = 0
        lock = threading.Lock()

        def run(*_):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                if active == 2:
                    ready.set()
            release.wait(3)
            with lock:
                active -= 1
            return {"result": {"summary": "Done"}}

        first, _, _ = self.add_batch(pool, "first", 3, run)
        self.assertTrue(ready.wait(2))
        second, events, _ = self.add_batch(pool, "second", 2, run)
        deadline = time.monotonic() + 2
        while len(events) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual([row["status"] for row in events], ["queued", "queued"])
        release.set()
        first.join(3)
        second.join(3)
        self.assertEqual(peak, 2)
        rows = list(self.storage.load()["workers"].values())
        self.assertEqual([row["status"] for row in rows], ["done"] * 5)

    def test_timeout_returns_while_inflight_tool_drains(self):
        pool = workers.Pool(self.storage, cap=1, timeout=0.20)
        self.addCleanup(pool.executor.shutdown)
        release = threading.Event()
        self.addCleanup(release.set)
        ran = []

        def run(worker, _):
            ran.append(worker.identity)
            release.wait(3)
            return {"result": {"summary": "Too late"}}

        thread, _, batch = self.add_batch(pool, "first", 2, run)
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual([worker.row["summary"] for worker in batch], ["Worker timed out."] * 2)
        self.assertEqual(len(ran), 1)
        self.assertTrue(pool.busy())
        release.set()
        pool.executor.shutdown()
        self.assertFalse(pool.busy())
        self.assertEqual([row["status"] for row in self.storage.load()["workers"].values()], ["failed", "failed"])

    def test_stop_one_then_stop_all_without_running_queued_work(self):
        pool = workers.Pool(self.storage, cap=1, timeout=4)
        self.addCleanup(pool.executor.shutdown)
        ready = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        ran = []

        def run(worker, _):
            ran.append(worker.identity)
            ready.set()
            release.wait(3)
            return {"result": {"summary": "Late"}}

        thread, events, batch = self.add_batch(pool, "turn", 3, run)
        self.assertTrue(ready.wait(2))
        queued = next(row for row in events if row["title"] == "Task 1")
        self.assertEqual(len(pool.stop("another turn", queued["id"])["workers"]), 0)
        self.assertEqual(len(pool.stop("turn", queued["id"])["workers"]), 1)
        self.assertEqual(len(pool.stop("turn")["workers"]), 2)
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual([worker.row["status"] for worker in batch], ["cancelled"] * 3)
        self.assertEqual(len(ran), 1)

    def test_browser_slots_cover_session_creation_through_release(self):
        browser = browserbase.Browserbase(None)
        lock = threading.Lock()
        active, released = set(), []
        first_pair = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        threads = []
        results = []

        def call(path, body, *, timeout):
            with lock:
                if path == "v1/sessions":
                    identity = f"fixture-{len(active) + len(released)}"
                    active.add(identity)
                    if len(active) == 2:
                        first_pair.set()
                    self.assertLessEqual(len(active), 2)
                    return {"id": identity, "connectUrl": "wss://connect.browserbase.com/"}
                identity = path.rsplit("/", 1)[1]
                active.remove(identity)
                released.append(identity)
                return {"status": "REQUEST_RELEASE"}

        async def drive(*_args, **_kwargs):
            await asyncio.to_thread(release.wait, 3)
            return {"text": "Fixture result"}, None

        with patch.object(browser, "call", side_effect=call), patch.object(browser, "drive", side_effect=drive):
            for _ in range(3):
                thread = threading.Thread(target=lambda: results.append(browser.session(
                    "https://example.org", [], lambda *_: None)), daemon=True)
                thread.start()
                threads.append(thread)
            self.assertTrue(first_pair.wait(2))
            self.assertEqual(len(active), 2)
            release.set()
            for thread in threads:
                thread.join(3)
        self.assertEqual(len(results), 3)
        self.assertEqual(len(released), 3)
        self.assertTrue(all(result["text"] == "Fixture result" for result, _ in results))


class ChatWorkersTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = Storage(directory.name)

    def make_app(self, gateway):
        app = fixture_app(self.storage, gateway)
        self.addCleanup(app.workers.executor.shutdown)
        return app

    def test_results_merge_in_one_reply_and_skill_limits_are_inherited(self):
        gateway = WorkerGateway()
        app = self.make_app(gateway)
        skill, _ = app.agent.skills.mutate("create", {"markdown": playbook(
            tools=["spawn_workers", "memory_read"])})
        with self.storage.lock():
            thread = app.threads.create(skill={"id": skill["id"], "name": skill["name"]})
        events = collect(app.enqueue(thread["id"], PROMPT))
        rows = [data for kind, data in events if kind == "worker"]
        self.assertEqual(len([row for row in rows if row["status"] == "done"]), 3)
        messages = app.threads.messages(thread["id"])
        self.assertEqual([row["role"] for row in messages], ["user", "assistant"])
        self.assertEqual(messages[1]["worker_turn_id"], messages[0]["id"])
        self.assertIn("Grants research finished.", messages[1]["content"])
        self.assertIn("Equipment research finished.", messages[1]["content"])
        self.assertEqual([row["title"] for row in gateway.results], ["Grants", "Venues", "Equipment"])
        self.assertEqual(gateway.results[0]["sources"], ["https://example.org/public-source"])
        self.assertTrue(all(request["max_tokens"] == workers.OUTPUT_TOKENS for request in gateway.limits))
        self.assertEqual(len([row for row in app.timeline_info()["entries"] if row["kind"] == "worker"]), 3)
        with self.assertRaisesRegex(HearthError, "available"):
            workers.validate_tasks([{"title": "Escape", "instructions": "Run a tool", "tools": ["send_email"]}],
                                   {"memory_read": {}})

    def test_approval_stays_gated_notifies_chat_and_resumes(self):
        assignment = {"title": "Playbook", "instructions": "Create the requested rehearsal skill.", "tools": ["skill_create"]}
        app = self.make_app(WorkerGateway(assignments=[assignment]))
        events = app.enqueue("main", "Create a rehearsal skill with parallel workers.")
        before = collect(events, lambda name, _: name == "action")
        self.assertTrue(any(name == "worker" and row["status"] == "waiting_approval" for name, row in before))
        _, proposal = before[-1]
        self.assertEqual((proposal["status"], proposal["worker_title"]), ("pending", "Playbook"))
        self.assertEqual(len(app.agent.skills.list()), 4)
        self.assertEqual(approvals.decide(app.agent, proposal["id"], "approve")["status"], "complete")
        after = collect(events)
        self.assertTrue(any(name == "worker" and row["status"] == "done" for name, row in after))
        self.assertEqual(len(app.agent.skills.list()), 5)
        self.assertEqual(len(app.threads.messages("main")), 2)

    def test_stop_withdraws_pending_approval(self):
        assignment = {"title": "Playbook", "instructions": "Create the requested skill.", "tools": ["skill_create"]}
        app = self.make_app(WorkerGateway(assignments=[assignment]))
        events = app.enqueue("main", "Create a rehearsal skill with parallel workers.")
        before = collect(events, lambda name, _: name == "action")
        _, proposal = before[-1]
        app.workers.stop(proposal["worker_turn_id"], proposal["worker_id"])
        self.assertEqual(approvals.decide(app.agent, proposal["id"], "approve")["status"], "cancelled")
        self.assertTrue(any(name == "done" for name, _ in collect(events)))
        self.assertEqual(len(app.agent.skills.list()), 4)

    def test_last_model_call_uses_evidence_without_native_tool_history(self):
        class AtLimit(WorkerGateway):
            def completion(self, model, messages, tools, emit, **limits):
                if not (TURN_MEMORY.get() or {}).get("worker"):
                    return super().completion(model, messages, tools, emit, **limits)
                self.limits.append(limits)
                if tools:
                    return tool_call("memory_read", {"path": "topics/thanksgiving.md"})
                if [item["role"] for item in messages] != ["system", "user"]:
                    raise AssertionError("Text-only synthesis included native tool history")
                if messages[-1]["content"].count("topics/thanksgiving.md") != workers.TOOL_LIMIT:
                    raise AssertionError("Text-only synthesis lost evidence")
                return {"role": "assistant", "content": '{"summary":"All findings reviewed.","sources":[]}'}

        gateway = AtLimit(assignments=ASSIGNMENTS[:1])
        app = self.make_app(gateway)
        events = collect(app.enqueue("main", PROMPT))
        self.assertEqual(gateway.results[0]["summary"], "All findings reviewed.")
        self.assertEqual(len(gateway.limits), workers.MODEL_LIMIT)
        self.assertTrue(any(name == "done" for name, _ in events))

    def test_batched_calls_fit_budget_and_parent_combines_partial_results(self):
        class Batched(WorkerGateway):
            def completion(self, model, messages, tools, emit, **limits):
                worker = (TURN_MEMORY.get() or {}).get("worker")
                if not worker:
                    return super().completion(model, messages, tools, emit, **limits)
                title = worker.row["title"]
                if title == "Venues":
                    raise ConnectorError("Venue research was unavailable.")
                if not tools:
                    evidence = json.loads(messages[-1]["content"].split("reference data: ", 1)[1])
                    assert len(evidence) == workers.TOOL_LIMIT
                    assert all(json.loads(item)["path"] == "topics/thanksgiving.md" for item in evidence)
                    return {"role": "assistant", "content": json.dumps({"summary": f"{title} findings verified."})}
                calls = [tool_call("memory_read", {"path": "topics/thanksgiving.md"})["tool_calls"][0]
                         for _ in range(workers.TOOL_LIMIT)]
                calls.append(tool_call("memory_read", {"path": "topics/omitted.md"})["tool_calls"][0])
                return {"role": "assistant", "content": None, "tool_calls": calls}

        gateway = Batched()
        app = self.make_app(gateway)
        events = collect(app.enqueue("main", PROMPT))
        self.assertEqual([row["status"] for row in gateway.results], ["done", "failed", "done"])
        done = [data for name, data in events if name == "worker" and data["status"] == "done"]
        self.assertEqual(len(done), 2)
        for row in done:
            self.assertEqual([step["status"] for step in row["steps"]], ["done"] * workers.TOOL_LIMIT)
        replies = [row["content"] for row in app.threads.messages("main") if row["role"] == "assistant"]
        self.assertEqual(len(replies), 1)
        for finding in ("Grants findings verified.", "Equipment findings verified.", "Venue research was unavailable."):
            self.assertIn(finding, replies[0])

    def test_synthesis_ignores_stray_calls_and_recovers_blank_replies(self):
        class StrayCalls(WorkerGateway):
            def completion(self, model, messages, tools, emit, **limits):
                worker = (TURN_MEMORY.get() or {}).get("worker")
                if not worker:
                    return super().completion(model, messages, tools, emit, **limits)
                if tools:
                    return {"role": "assistant", "content": None, "tool_calls": [
                        tool_call("memory_read", {"path": "topics/thanksgiving.md"})["tool_calls"][0]
                        for _ in range(workers.TOOL_LIMIT)
                    ]}
                stray = tool_call("memory_read", {"path": "topics/omitted.md"})
                if worker.row["title"] == "Grants":
                    stray["content"] = '{"summary":"Grant synthesis kept.","sources":[]}'
                    return stray
                if worker.row["title"] == "Venues":
                    return {"role": "assistant", "content": (
                        '```json\n{"summary":"Venue synthesis kept.","sources":[]}\n```\n'
                        'memory_read>{"path":"topics/omitted.md"}'
                    )}
                return {"role": "assistant", "content": 'memory_read>{"path":"topics/omitted.md"}'}

        gateway = StrayCalls()
        app = self.make_app(gateway)
        events = collect(app.enqueue("main", PROMPT))
        self.assertEqual([row["status"] for row in gateway.results], ["done"] * 3)
        self.assertEqual(gateway.results[0]["summary"], "Grant synthesis kept.")
        self.assertEqual(gateway.results[1]["summary"], "Venue synthesis kept.")
        self.assertIn("topics/thanksgiving.md", gateway.results[2]["summary"])
        self.assertIn("# Thanksgiving", gateway.results[2]["summary"])
        for name, row in events:
            if name == "worker" and row["status"] == "done":
                self.assertEqual(len(row["steps"]), workers.TOOL_LIMIT)

    def test_recurring_task_can_delegate_and_handoff_approval(self):
        assignment = {"title": "Browser", "instructions": "Check the sample page with a browser session.",
                      "tools": ["browse_session"]}
        app = self.make_app(WorkerGateway(assignments=[assignment]))
        now = datetime.now(timezone.utc)
        tasks.mutate(self.storage, "create", {"name": "Site check",
                     "instruction": "Check the sample site with parallel workers.",
                     "schedule": {"type": "interval", "minutes": 10}}, clock=now)
        self.assertEqual(app.task_runner.tick(now + timedelta(minutes=10)), 1)
        state = self.storage.load()
        run, = state["task_runs"].values()
        self.assertEqual(run["status"], "approval_needed")
        self.assertIn("Submitted for approval", run["output"])
        proposal, = approvals.records(self.storage, pending=True)
        self.assertEqual((proposal["worker_title"], proposal["task_run"]), ("Browser", run["id"]))
