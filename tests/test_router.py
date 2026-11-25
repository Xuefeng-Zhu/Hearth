import json
import tempfile
import unittest
from pathlib import Path

from hearth import router
from hearth.connectors import read_config
from hearth.storage import ROOT, Storage

KIMI, FAST, PRO, CODER = router.PREFERRED_MODELS


class RouterTest(unittest.TestCase):
    def setUp(self):
        self.config = read_config(ROOT / "config/connectors.json")
        next(item for item in self.config["llm"] if item["provider"] == "huggingface")["connection_id"] = "conn_hf"
        self.mode, self.models, unavailable = router.setup(self.config)
        self.assertIsNone(unavailable)

    def order(self, kind, stats=None, mode=None, now=10_000):
        models, reason = router.order_models(self.models, kind, mode or self.mode, stats or {}, now=now)
        return [model["model"] for model in models], reason

    def test_classifies_turns_and_keeps_specialized_side_turns(self):
        samples = [
            ("Hi there!", False, "quick"),
            ("Can you create a slide for Seattle trip", False, "tool"),
            ("Open the reminders panel", False, "tool"),
            ("Plan a weekend in Seattle", False, "planning"),
            ("Read topics/thanksgiving.md", False, "tool"),
            ("Remind me to call Lin in 20 minutes", True, "tool"),
            ("提醒我明天给妈妈打电话", False, "tool"),
            ("Plan Thanksgiving dinner", False, "tool"),
            ("Compare the options and explain the trade-offs", False, "reasoning"),
            ("Context " * 130, False, "reasoning"),
            ("Write a Python function to search for files", False, "code"),
            ("你好！今天怎么样？", False, "multilingual"),
            ("Translate this phrase into Japanese", False, "multilingual"),
            ("How funny!", True, "side"),
            ("/btw One more thing", False, "side"),
            ("/side Refactor this function", False, "code"),
        ]
        for prompt, side, expected in samples:
            with self.subTest(prompt=prompt[:50], side=side):
                self.assertEqual(router.classify(prompt, side=side), expected)

    def test_smart_default_and_ordering_with_two_models_on_one_provider(self):
        self.assertEqual(self.mode, "smart")
        self.assertEqual(self.order("quick")[0], [FAST, KIMI, PRO, CODER, "hearth-demo"])
        self.assertEqual(self.order("side")[0][0], FAST)
        self.assertEqual(self.order("tool")[0], [KIMI, FAST, PRO, CODER, "hearth-demo"])
        self.assertEqual(self.order("reasoning")[0][0], PRO)
        self.assertEqual(self.order("code")[0][0], PRO)
        self.assertEqual(self.order("planning")[0][0], KIMI)
        self.assertEqual(self.order("multilingual")[0][0], KIMI)
        self.assertEqual(self.order("vision")[0], [KIMI, FAST, "hearth-demo"])
        self.assertEqual(router.setup(self.config, pool=[])[0], "smart")
        self.assertEqual(router.setup(self.config, {"provider": "priority", "model": ""})[0], "priority")
        self.assertEqual([m["provider"] for m in router.setup(self.config, {"provider": "mock", "model": ""})[1]],
                         ["mock"])
        custom = [{"provider": "huggingface", "model": "tiny-chat", "tags": {"speed": "fast", "tools": "low"}},
                  {"provider": "huggingface", "model": CODER}]
        self.mode, self.models, _ = router.setup(self.config, pool=custom)
        self.assertEqual(self.order("tool")[0], [CODER, "hearth-demo"])
        self.assertEqual(router.classify("Describe this", image_attachment=True), "vision")

    def test_demotion_uses_recent_failures_error_rate_and_latency(self):
        key = "huggingface:" + FAST
        stats = {key: {"last_failure": 9_950, "error_rate": .1, "p50_ms": 1_000}}
        models, reason = self.order("quick", stats)
        self.assertEqual(models, [KIMI, PRO, CODER, FAST, "hearth-demo"])
        self.assertIn("recent failure", reason)
        self.assertEqual(self.order("quick", stats, now=10_300)[0][0], FAST)

    def test_stats_persist_per_model_and_expire(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(tmp)
            stats = router.BrainStats(storage)
            first, second, *_, mock = self.models
            stats.record(first, True, 1_200, now=100)
            stats.record(first, False, 4_000, now=101)
            stats.record(first, True, 800, now=102)
            stats.record(second, True, 300, now=103)
            stats.record(mock, True, 1, now=104)
            disk = json.loads((Path(tmp) / "brain_stats.json").read_text())
            saved = router.BrainStats(storage).snapshot(now=104)
            self.assertEqual(set(saved), {router.model_key(first), router.model_key(second)})
            self.assertEqual(saved[router.model_key(first)],
                             {"p50_ms": 1_000, "error_rate": 1 / 3, "last_failure": 101, "sample_count": 3})
            self.assertEqual(disk[router.model_key(first)]["p50_ms"], 1_000)
            self.assertEqual(saved[router.model_key(second)]["p50_ms"], 300)
            self.assertEqual(stats.snapshot(now=105 + router.SAMPLE_AGE), {})
