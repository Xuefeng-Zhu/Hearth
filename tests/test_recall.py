import io
import json
import tempfile
import time
import unittest
from datetime import datetime, timezone

from hearth import recall
from hearth.agent import Agent
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import Gateway, read_config
from hearth.server import Application
from hearth.storage import HearthError, ROOT, Storage

ALLERGY = "Lena develops hives after consuming hazelnuts or almonds."


class EmbeddingHTTP:
    def __init__(self):
        self.requests = []

    def open(self, request, timeout):
        texts = json.loads(request.data)["inputs"]
        self.requests.append((request, texts))
        vectors = [[1, 0, 0] if "hazelnuts" in text or "who cannot eat nuts" in text else [0, 1, 0]
                   for text in texts]
        return io.BytesIO(json.dumps(vectors).encode())


class RecallTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.storage = Storage(scratch.name)
        self.checkpoints = LocalCheckpoints(self.storage)
        self.config = read_config(ROOT / "config/connectors.json")
        self.gateway = Gateway()
        self.http = EmbeddingHTTP()
        self.gateway.opener = self.http
        self.path = "topics/allergies.md"
        self.storage.write(self.path, "# Household\n\n" + ALLERGY + "\n\nLena visits on Fridays.\n")
        self.selection = recall.settings({"backend": "huggingface", "top_k": 1})
        self.config["llm"] = [dict(model, connection_id="demo-connector") if model["provider"] == "huggingface"
                              else model for model in self.config["llm"]]
        self.config["memory"] = self.selection
        self.query = "who cannot eat nuts"

    def test_hugging_face_semantic_match_reuses_index_and_only_embeds_edits(self):
        agent = Agent(self.storage, self.checkpoints, self.config, self.gateway)
        first = agent.memory_search(self.query)
        hit, = first["results"]
        self.assertEqual((hit["path"], hit["line"], hit["keyword"], hit["similarity"]), (self.path, 3, 0.0, 1.0))
        offline = agent.memory_index.run(agent.config, {**self.selection, "backend": "keyword"}, self.query)
        self.assertFalse(any(hit["path"] == self.path for hit in offline["results"]))
        request, _ = self.http.requests[0]
        self.assertTrue(request.full_url.endswith("/hf-inference/models/BAAI/bge-small-en-v1.5/pipeline/feature-extraction"))
        self.assertEqual(request.get_method(), "POST")
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(len(list((self.storage.live / "index").glob("*.json"))), 1)

        restarted = Agent(self.storage, self.checkpoints, self.config, self.gateway)
        self.assertEqual(restarted.memory_search(self.query)["embedded"], 0)
        self.storage.write(self.path, "# Household\n\n" + ALLERGY + "\n\nLena visits on Sundays.\n")
        result = restarted.memory_search(self.query)
        self.assertEqual(result["embedded"], 1)
        self.assertEqual(result["results"][0]["line"], 3)
        self.assertIn("Sundays", self.http.requests[-2][1][0])
        self.assertNotIn("hazelnuts", self.http.requests[-2][1][0])

    def test_local_recall_matches_a_chinese_phrase_inside_a_note(self):
        self.storage.write("topics/lantern.md", "# 星火测试\n\n我的星火测试笔记：青瓷风铃编号是云雀七码。\n")
        self.storage.write("topics/ceramics.md", "# 青瓷\n\n茶杯是青瓷做的。\n")
        index = recall.Recall(self.storage, self.gateway)
        for backend in ("local", "keyword"):
            with self.subTest(backend=backend):
                selection = {**self.selection, "backend": backend}
                hit, = index.run(self.config, selection, "青瓷风铃编号")["results"]
                self.assertEqual(hit["path"], "topics/lantern.md")
                self.assertIn("云雀七码", hit["excerpt"])

    def test_chat_cites_only_sources_used_and_persists_metadata(self):
        def completion(model, messages, tools, emit):
            reference = json.loads(messages[1]["content"])["untrusted_reference_data"]
            hit, = reference["Recalled memory (citation, path, line, heading, excerpt)"]
            self.assertEqual(hit["path"], self.path)
            self.assertEqual(hit["line"], 3)
            self.assertNotIn("memory_write", [tool["function"]["name"] for tool in tools])
            return {"role": "assistant", "content": f"Lena. {hit['citation']} [[memory:0000000000000000]]"}

        self.gateway.completion = completion
        agent = Agent(self.storage, self.checkpoints, self.config, self.gateway)
        events = []
        agent.chat(self.query, lambda name, data: events.append((name, data)))
        message = events[-1][1]["message"]
        self.assertEqual(message["content"], "Lena. [topics/allergies.md:3]")
        hit, = message["remembered"]
        self.assertNotIn("excerpt", hit)
        self.assertEqual(agent.threads.messages("main")[-1], message)

    def test_scope_chat_forget_and_undo(self):
        app = Application(self.storage, self.checkpoints, self.config)
        with self.storage.lock():
            side = app.threads.create()
            main = app.threads.append("main", "user", "orchard pruning on Saturday")
            message = app.threads.append(side["id"], "user", "orchard harvesting on Sunday")
        selection = {**self.selection, "backend": "keyword", "include_chat": True, "top_k": 20, "exclude": ["topics"]}
        hits = app.memory_index.run(app.agent.config, selection, "orchard")["results"]
        self.assertEqual({hit["message_id"] for hit in hits}, {main["id"], message["id"]})
        excluded = app.memory_index.run(app.agent.config, selection, "hazelnuts")["results"]
        self.assertEqual(excluded, [])
        off = app.memory_index.run(app.agent.config, {**selection, "include_chat": False}, "orchard")
        self.assertEqual(off["results"], [])

        victim = next(hit for hit in hits if hit["message_id"] == message["id"])
        self.assertEqual(app.chat_memory(side["id"], message["id"])["excerpt"], message["content"])
        action = app.forget_memory({"path": victim["path"], "message_id": victim["message_id"]})
        with self.assertRaisesRegex(HearthError, "forgotten"):
            app.chat_memory(side["id"], message["id"])
        self.assertEqual(app.threads.messages(side["id"]), [message])
        self.assertEqual([hit["message_id"] for hit in app.memory_index.run(app.agent.config, selection, "orchard")["results"]],
                         [main["id"]])
        app.checkpoints.restore(action["checkpoint"]["id"])
        self.assertEqual(app.chat_memory(side["id"], message["id"])["excerpt"], message["content"])

        note = next(item for item in recall.note_chunks(self.path, self.storage.read(self.path)) if item["line"] == 3)
        action = app.forget_memory({"path": self.path, "item_id": note["id"]})
        self.assertNotIn(ALLERGY, self.storage.read(self.path))
        self.assertIn("Fridays", self.storage.read(self.path))
        app.checkpoints.restore(action["checkpoint"]["id"])
        self.assertIn(ALLERGY, self.storage.read(self.path))

    def test_checkpointed_reindex_and_search_preferences_save(self):
        app = Application(self.storage, self.checkpoints, self.config, gateway=self.gateway)
        app.connections.selected = {"huggingface": "demo-connector"}
        app.connections.save_preferences("search", {"provider": "off", "max_results": 3, "recency": "week",
                                                    "safe_search": True, "include_domains": [], "exclude_domains": []})
        self.assertIn("search settings", self.checkpoints.list()[0]["comment"])
        app.reload_agent()
        self.assertEqual(app.search_info()["selection"]["max_results"], 3)
        original = self.http.open

        def check_snapshot(request, timeout):
            self.assertTrue(any("rebuilding Hearth memory" in item["comment"] for item in self.checkpoints.list()))
            return original(request, timeout)

        self.http.open = check_snapshot
        app.start_reindex()
        deadline = time.monotonic() + 3
        while app.reindex_running() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(app.reindex["status"], "complete")
        self.assertEqual(app.reindex["backend"], "huggingface")
        self.assertEqual(app.reindex["total"], app.reindex["embedded"])
        self.assertIn("checkpoint", app.reindex)

    def test_auto_remember_modes_and_approval(self):
        today = f"daily/{datetime.now(timezone.utc).date().isoformat()}.md"
        self.config["brain"] = {"provider": "mock", "model": ""}
        self.config["memory"] = {**self.selection, "backend": "keyword"}
        with self.assertRaisesRegex(HearthError, "Auto-remember is off"):
            Agent(self.storage, self.checkpoints, self.config).remember_fact("Lena enjoys cycling.")
        self.config["memory"]["auto_remember"] = "ask"
        agent = Agent(self.storage, self.checkpoints, self.config)
        events = []
        agent.chat("Remember this: Lena enjoys cycling.", lambda name, data: events.append((name, data)))
        action, = [data for name, data in events if name == "action"]
        self.assertEqual(action["status"], "pending")
        self.assertFalse(self.storage.memory_path(today).exists())
        self.assertEqual(agent.approve(action["id"])["status"], "complete")
        self.assertEqual(agent.approve(action["id"])["status"], "complete")
        self.assertEqual(self.storage.read(today).count("Lena enjoys cycling."), 1)

        self.config["memory"]["auto_remember"] = "automatic"
        agent = Agent(self.storage, self.checkpoints, self.config)
        events.clear()
        agent.chat("Remember that Lena uses a blue bicycle.", lambda name, data: events.append((name, data)))
        action, = [data for name, data in events if name == "action"]
        self.assertEqual(action["status"], "complete")
        self.assertTrue(action["checkpoint"])
        self.assertIn("Lena uses a blue bicycle.", self.storage.read(today))
