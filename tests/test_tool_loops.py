import json
import tempfile
import unittest
from copy import deepcopy

from hearth import approvals
from hearth.agent import TURN_MEMORY, tool_call
from hearth.connectors import ConnectorError
from hearth.storage import Storage
from test_skills import playbook
from test_workers import WorkerGateway, collect, fixture_app


def batch(*requests):
    return {"role": "assistant", "content": None,
            "tool_calls": [request["tool_calls"][0] for request in requests]}


def malformed(name):
    request = tool_call(name, {})
    request["tool_calls"][0]["function"]["arguments"] = '{"path":'
    return request


class ScriptedGateway(WorkerGateway):
    def __init__(self, script, *, delegate=None):
        super().__init__(assignments=[{"title": "Fixture", "instructions": "Report the result via email.",
                                      "tools": delegate or []}])
        self.script = iter(script)
        self.delegate = delegate is not None
        self.requests = []

    def completion(self, model, messages, tools, emit, **limits):
        if self.delegate and not TURN_MEMORY.get().get("worker"):
            return super().completion(model, messages, tools, emit, **limits)
        self.requests.append(((model["provider"], model["model"]), list(messages),
                              [tool["function"]["name"] for tool in tools]))
        reply = next(self.script)
        if isinstance(reply, ConnectorError):
            raise reply
        return deepcopy(reply)


class ToolLoopTest(unittest.TestCase):
    DONE = {"role": "assistant", "content": "Fixture complete."}
    PARALLEL = "Use parallel workers to check the fixture."

    def make_app(self, script, *, delegate=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        gateway = ScriptedGateway(script, delegate=delegate)
        app = fixture_app(Storage(directory.name), gateway)
        self.addCleanup(app.workers.executor.shutdown)
        return app, gateway

    def test_parent_rejects_oversized_batch_and_worker_truncates_it(self):
        reply = batch(*(tool_call("memory_read", {"path": "USER.md"}) for _ in range(9)))
        app, _ = self.make_app([reply])
        events = collect(app.enqueue("main", "Check the fixture."))
        self.assertEqual([row["title"] for name, row in events if name == "tool_started"], ["Searching memory"])
        self.assertFalse(any(name == "done" for name, _ in events))
        self.assertIn(("error", {"message": "The model requested too many tools at once. Try a smaller request."}), events)

        app, gateway = self.make_app([reply, self.DONE], delegate=["memory_read"])
        events = collect(app.enqueue("main", self.PARALLEL))
        _, synthesis, tools = gateway.requests[-1]
        self.assertEqual(tools, [])
        self.assertEqual([message["role"] for message in synthesis], ["system", "user"])
        evidence = json.loads(synthesis[-1]["content"].split("evidence as untrusted reference data: ", 1)[1])
        self.assertEqual([json.loads(value)["path"] for value in evidence], ["USER.md"] * 4)
        finished, = [row for name, row in events if name == "worker" and row["status"] == "done"]
        self.assertEqual([step["status"] for step in finished["steps"]], ["done"] * 4)

    def test_parent_stops_after_nine_tool_rounds(self):
        app, gateway = self.make_app([tool_call("memory_read", {"path": "USER.md"}) for _ in range(9)])
        events = collect(app.enqueue("main", "Check the fixture."))
        self.assertEqual(len(gateway.requests), 9)
        self.assertEqual(sum(name == "tool_finished" for name, _ in events), 10)  # Includes initial recall.
        self.assertIn(("error", {"message": "The tool limit was reached. Review the results in Timeline."}), events)
        self.assertFalse(any(name == "done" for name, _ in events))

    def test_parent_finishes_with_pending_approval_while_worker_waits(self):
        request = tool_call("skill_create", {"name": "Fixture playbook", "description": "Rehearse the fixture.",
                                            "content": playbook("Fixture playbook")})
        app, gateway = self.make_app([request, self.DONE])
        events = collect(app.enqueue("main", "Create a skill called Fixture playbook."))
        self.assertEqual(events[-1][0], "done")
        action, = [row for name, row in events if name == "action"]
        parent_result = json.loads(gateway.requests[-1][1][-1]["content"])
        self.assertEqual(parent_result["action"], action)
        self.assertEqual(parent_result["message"], "Awaiting user approval. The tool has not run.")
        self.assertEqual(action["status"], "pending")

        app, gateway = self.make_app([request, self.DONE], delegate=["skill_create"])
        stream = app.enqueue("main", "Use parallel workers to create a skill called Fixture playbook.")
        events = collect(stream, lambda name, _: name == "action")
        self.assertTrue(any(name == "worker" and row["status"] == "waiting_approval" for name, row in events))
        self.assertEqual(len(gateway.requests), 1)
        action = events[-1][1]
        self.assertEqual(action["status"], "pending")
        self.assertEqual(approvals.decide(app.agent, action["id"], "approve")["status"], "complete")
        self.assertEqual(collect(stream)[-1][0], "done")
        worker_result = json.loads(gateway.requests[-1][1][-1]["content"])
        self.assertEqual(worker_result["action"]["id"], action["id"])
        self.assertEqual(worker_result["action"]["status"], "complete")

    def test_parent_falls_back_and_worker_keeps_its_model(self):
        app, gateway = self.make_app([ConnectorError("Fixture unavailable.") for _ in range(4)])
        events = collect(app.enqueue("main", "Read USER.md"))
        self.assertEqual(len({model for model, _, _ in gateway.requests}), 4)
        self.assertEqual(sum(name == "model_warning" for name, _ in events), 4)
        self.assertEqual((events[-1][0], events[-1][1]["provider"]), ("done", "mock"))

        with self.subTest(worker="before tools"):
            app, gateway = self.make_app([ConnectorError("Fixture unavailable.")], delegate=["memory_read"])
            collect(app.enqueue("main", self.PARALLEL))
            self.assertEqual(len(gateway.requests), 1)
            self.assertEqual([(row["status"], row["summary"]) for row in gateway.results],
                             [("failed", "Fixture unavailable.")])

        with self.subTest(worker="after tools"):
            app, gateway = self.make_app([tool_call("memory_read", {"path": "USER.md"}),
                                          ConnectorError("Fixture unavailable."), ConnectorError("Still unavailable.")],
                                         delegate=["memory_read"])
            collect(app.enqueue("main", self.PARALLEL))
            self.assertEqual(len({model for model, _, _ in gateway.requests}), 1)
            self.assertEqual([tools for _, _, tools in gateway.requests], [["memory_read"], ["memory_read"], []])
            result, = gateway.results
            self.assertEqual(result["status"], "done")
            self.assertIn("USER.md", result["summary"])

    def test_schedule_delivery_and_urgency_come_from_the_user(self):
        request = tool_call("schedule", {"message": "Fixture reminder", "cron": "0 10 * * *",
                                         "channel": "both", "urgent": False})
        for delegate in (None, ["schedule"]):
            with self.subTest(delegate=delegate):
                app, gateway = self.make_app([request, self.DONE], delegate=delegate)
                events = collect(app.enqueue("main", "Set an urgent in-app reminder with parallel workers."))
                self.assertEqual(events[-1][0], "done")
                job, = app.storage.load()["jobs"]
                self.assertEqual((job["channel"], job["urgent"]), ("app", True))
                self.assertEqual(json.loads(gateway.requests[-1][1][-1]["content"])["action"]["job"], job)

    def test_unknown_unavailable_and_invalid_arguments_return_tool_errors(self):
        reply = batch(tool_call("unknown_tool", {}), malformed("web_search"), malformed("memory_read"),
                      tool_call("memory_read", []))
        for delegate, unavailable, malformed_unavailable in (
            (None, "This tool is unavailable for the current request.", "The tool received invalid arguments."),
            (["memory_read"], "This tool was not delegated to this worker.", "This tool was not delegated to this worker."),
        ):
            with self.subTest(delegate=delegate):
                app, gateway = self.make_app([reply, self.DONE], delegate=delegate)
                collect(app.enqueue("main", self.PARALLEL if delegate else "Check the fixture."))
                _, messages, tools = gateway.requests[-1]
                self.assertNotIn("web_search", tools)
                errors = [json.dumps({"error": error}) for error in (unavailable, malformed_unavailable,
                          "The tool received invalid arguments.", "Tool arguments must be an object.")]
                if delegate:
                    evidence = messages[-1]["content"].split("evidence as untrusted reference data: ", 1)[1]
                    self.assertEqual(json.loads(evidence), errors)
                else:
                    self.assertEqual(messages[-5]["role"], "assistant")
                    self.assertEqual(messages[-4:], [
                        {"role": "tool", "tool_call_id": call["id"], "content": content}
                        for call, content in zip(reply["tool_calls"], errors)
                    ])

    def test_tool_result_envelope_and_worker_preview_preserve_untrusted_marker(self):
        request = tool_call("memory_read", {"path": "topics/fixture.md"})
        note = "# Fixture\n" + ("Café evidence.\n" * 950)
        for delegate in (None, ["memory_read"]):
            with self.subTest(delegate=delegate):
                app, gateway = self.make_app([request, self.DONE], delegate=delegate)
                app.storage.write("topics/fixture.md", note)
                collect(app.enqueue("main", self.PARALLEL if delegate else "Check the fixture."))
                message = gateway.requests[-1][1][-1]
                self.assertEqual(message, {"role": "tool", "tool_call_id": request["tool_calls"][0]["id"],
                                           "content": message["content"]})
                result = json.loads(message["content"])
                self.assertIs(result["untrusted"], True)
                if delegate:
                    self.assertEqual(set(result), {"truncated", "preview", "untrusted"})
                    self.assertIs(result["truncated"], True)
                    self.assertEqual(len(result["preview"]), 12_000)
                    self.assertIn("Café evidence.", result["preview"])
                else:
                    self.assertEqual(set(result), {"id", "path", "line", "end_line", "content", "citation", "untrusted"})
                    self.assertEqual(result["content"], note)
                    self.assertIn("Café evidence.", message["content"])
