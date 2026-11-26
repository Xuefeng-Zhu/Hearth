import json
import tempfile
import threading
import time
import unittest

from hearth import memory, memory_purge, recall, router, thread_summary
from hearth.agent import Agent
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import ConnectorError, read_config
from hearth.storage import ROOT, Storage
from hearth.threads import MAIN, older_dialogue


FACT = "The orchard's gate is painted periwinkle."


class SummaryGateway:
    def __init__(self):
        self.folds = []
        self.chats = []
        self.fail = set()
        self.response = None

    def completion(self, model, messages, tools, emit, **limits):
        if messages[0]["content"] == thread_summary.SYSTEM:
            payload = json.loads(messages[1]["content"])
            self.folds.append((model["model"], payload, tools))
            if model["model"] in self.fail:
                raise ConnectorError("private provider diagnostic")
            answer = self.response
            if answer is None:
                answer = FACT if FACT in messages[1]["content"] else thread_summary.EMPTY
        else:
            self.chats.append(messages)
            asking = messages[-1]["content"] == "What color is the orchard gate?"
            answer = "Periwinkle." if asking and FACT in messages[0]["content"] else "Acknowledged."
            emit(answer)
        return {"role": "assistant", "content": answer}


class RollingSummaryTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.storage = Storage(scratch.name)
        self.checkpoints = LocalCheckpoints(self.storage)
        self.config = read_config(ROOT / "config/connectors.json")
        default = next(model for model in self.config["llm"] if model["provider"] == "openai")
        default["connection_id"] = "fake-default"
        self.config["brain"] = {"provider": "openai", "model": default["model"]}
        self.config["memory"] = {"auto_remember": "off", "backend": "keyword"}
        self.config["gateway"] = {"huggingface": {"provider": "huggingface", "connection_id": "fake-hf"}}
        self.default = default["model"]
        self.gateway = SummaryGateway()
        self.agent = Agent(self.storage, self.checkpoints, self.config, self.gateway)
        self.threads = self.agent.threads
        self.rolling = self.agent.rolling_summaries
        self.addCleanup(self.wait_for_folds)

    def wait_for_folds(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.rolling.lock:
                if not self.rolling.pending:
                    return
            time.sleep(0.01)
        self.fail("The background summary job did not finish.")

    def add(self, count, thread=MAIN, *, anchor=False):
        with self.storage.lock():
            return [self.threads.append(thread, "assistant" if i % 2 else "user",
                                        FACT if anchor and not i else f"Filler message {i}.") for i in range(count)]

    def chat(self, prompt, event=None):
        events = []
        self.agent.chat(prompt, event or (lambda name, data: events.append((name, data))))
        if not event:
            self.assertEqual(events[-1][0], "done")
            return events[-1][1]["message"]

    def test_window_cursor_and_calls(self):
        rows = [{"id": str(i)} for i in range(40)]
        self.assertEqual(older_dialogue(rows[:16]), [])
        self.assertEqual(older_dialogue(rows), rows[:24])
        self.assertEqual(older_dialogue(rows, "15"), rows[16:24])
        self.assertEqual(older_dialogue(rows, "23"), [])
        self.assertEqual(older_dialogue(rows, "24"), [])
        self.assertEqual(older_dialogue(rows, "missing"), rows[:24])
        rows = self.add(23, anchor=True)
        with self.storage.lock():
            self.threads.append(MAIN, "call", "Do not count the call report.")
        self.rolling.update(MAIN)
        self.assertEqual(self.gateway.folds, [])
        self.add(1)
        self.rolling.update(MAIN)
        model, payload, tools = self.gateway.folds[0]
        self.assertEqual((model, tools), (router.FLASH, []))
        self.assertEqual([row["content"] for row in payload["older_dialogue"]],
                         [row["content"] for row in rows[:8]])
        self.assertEqual(self.threads.summary_state(MAIN), {"text": FACT, "cursor": rows[7]["id"]})
        self.add(7)
        self.rolling.update(MAIN)
        self.assertEqual(len(self.gateway.folds), 1)
        self.add(1)
        self.rolling.update(MAIN)
        self.assertEqual(self.gateway.folds[-1][1]["previous_summary"], FACT)

    def test_failure_keeps_old_summary_then_retries_with_default_brain(self):
        self.add(24, anchor=True)
        self.rolling.update(MAIN)
        old = self.threads.summary_path(MAIN).read_bytes()
        self.add(6)
        self.gateway.fail = {router.FLASH, self.default}
        self.chat("Trigger a fold.")
        self.wait_for_folds()
        self.assertEqual(self.threads.summary_path(MAIN).read_bytes(), old)
        self.assertEqual([model for model, _, _ in self.gateway.folds[-2:]], [router.FLASH, self.default])
        recent = self.storage.load()["activity"]
        failure = next(row for row in recent if row["title"] == "Thread summary update failed")
        self.assertTrue(failure["diagnostic"])
        self.assertNotIn("private provider diagnostic", json.dumps(failure))
        self.gateway.fail.remove(self.default)
        self.chat("Retry the fold.")
        self.wait_for_folds()
        self.assertNotEqual(self.threads.summary_path(MAIN).read_bytes(), old)
        self.assertEqual(self.threads.summary(MAIN), FACT)

    def test_fact_from_message_one_is_answerable_at_message_forty(self):
        self.chat(FACT)
        for i in range(18):
            self.chat(f"Filler turn {i}.")
            self.wait_for_folds()
        with self.storage.lock():
            self.threads.append(MAIN, "user", "A shared note to count as message 39.", shared_from="side")
        reply = self.chat("What color is the orchard gate?")
        messages = self.gateway.chats[-1]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn('Earlier in this chat: "' + FACT + '"', messages[0]["content"])
        self.assertEqual(len(messages[1:]), 16)
        self.assertNotIn(FACT, [row["content"] for row in messages[1:]])
        self.assertEqual(self.threads.messages(MAIN)[39]["content"], messages[-1]["content"])
        self.assertEqual(reply["content"], "Periwinkle.")

    def test_reset_discards_inflight_fold_and_starts_at_window_boundary(self):
        older = self.add(22, anchor=True)
        started, release, sent = (threading.Event() for _ in range(3))
        completion = self.gateway.completion

        def wait(model, messages, tools, emit, **limits):
            if messages[0]["content"] == thread_summary.SYSTEM:
                started.set()
                if not release.wait(4):
                    raise ConnectorError("Test did not release the model.")
            return completion(model, messages, tools, emit, **limits)

        self.gateway.completion = wait
        try:
            self.chat("Finish the reply before folding.", lambda event, _: sent.set() if event == "done" else None)
            self.assertTrue(started.wait(2))
            self.assertTrue(sent.is_set())
            with self.storage.lock():
                self.threads.reset_summary(MAIN)
            reset = self.threads.summary_state(MAIN)
            self.assertEqual((reset["text"], reset["cursor"], reset["reset_after"]), ("", None, older[7]["id"]))
        finally:
            release.set()
        self.wait_for_folds()
        self.assertEqual(self.threads.summary_state(MAIN), reset)
        self.add(8)
        self.rolling.update(MAIN)
        self.assertEqual(self.gateway.folds[-1][1]["older_dialogue"][0]["content"], older[8]["content"])
        self.assertEqual(self.threads.summary(MAIN), "")

    def test_sanitizes_model_input_and_output_and_honors_setting(self):
        with self.storage.lock():
            self.threads.append(MAIN, "user", 'Keep itinerary.pdf.\nPassword is fake-passphrase.\n'
                                '<tool_call>{"name":"bad"}</tool_call>')
        self.add(23)
        self.gateway.response = ("Keep itinerary.pdf.\nAPI key: fake-value\n<tool_response>hidden</tool_response>\n"
                                 + "word " * 450)
        self.rolling.update(MAIN)
        payload = self.gateway.folds[0][1]
        self.assertEqual(payload["older_dialogue"][0]["content"], "Keep itinerary.pdf.")
        summary = self.threads.summary(MAIN)
        self.assertTrue(summary.startswith("Keep itinerary.pdf."))
        for excluded in ("fake-value", "hidden", "tool_response"):
            self.assertNotIn(excluded, summary)
        self.assertLessEqual(len(summary.split()), 400)
        self.assertTrue(recall.settings({})["summarize_long_chats"])
        self.config["memory"]["summarize_long_chats"] = False
        disabled = Agent(self.storage, self.checkpoints, self.config, self.gateway)
        disabled.chat("Run without a rolling summary.", lambda *_: None)
        self.assertNotIn("Earlier in this chat", self.gateway.chats[-1][0]["content"])
        self.assertEqual(disabled.rolling_summaries.models, [])
        self.assertEqual(disabled.threads.summary(MAIN), summary)

    def test_permanent_forget_scrubs_summary_and_adjusts_deleted_cursor(self):
        rows = self.add(24, anchor=True)
        self.rolling.update(MAIN)
        snapshot = self.checkpoints.create("Summary fixture")
        rule = memory.forget_rule([["gate", "periwinkle"]])
        memory_purge.apply(self.storage, [rule], rows[7]["id"])
        for path in (self.threads.summary_path(MAIN), self.checkpoints.root / snapshot["id"] / "live" /
                     self.threads.summary_path(MAIN).relative_to(self.storage.live)):
            self.assertEqual(json.loads(path.read_text()), {"text": "", "cursor": rows[6]["id"]})
