import io
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from hearth import approvals, event_automations, router, tasks, uploads
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import ConnectorError, Gateway, read_config
from hearth.server import Application
from hearth.storage import ROOT, Storage
from hearth.threads import MAIN


class ChatContextTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.storage = Storage(folder.name)
        self.gateway = Mock(spec=Gateway)
        config = read_config(ROOT / "config/connectors.json")
        config["memory"] = {"backend": "keyword", "summarize_long_chats": False}
        self.app = Application(self.storage, LocalCheckpoints(self.storage), config, gateway=self.gateway)
        self.agent = self.app.agent
        self.agent.brain_mode = "manual"
        self.agent.models = [{"provider": "huggingface", "model": router.KIMI, "connection_id": "fixture"}]
        connection = patch.object(self.agent.memory_index, "hf_entry", return_value=self.agent.models[0])
        connection.start()
        self.addCleanup(connection.stop)

    def stage(self, name, data):
        def receive(file):
            return name, file.write(data)

        return self.app.uploads.stage(MAIN, receive)

    def image(self):
        image = io.BytesIO()
        Image.new("RGB", (40, 25), "purple").save(image, "PNG")
        return self.stage("screenshot.png", image.getvalue())

    def chat(self, prompt, attachments=()):
        events = []
        self.agent.chat(prompt, lambda name, data: events.append((name, data)), attachments=attachments)
        self.assertEqual(events[-1][0], "done", events)
        return events[-1][1]["message"]

    def receipt(self, identity, status, result):
        row = {"id": identity, "status": status, "result": result}
        with self.storage.lock():
            state = self.storage.load()
            state["actions"][identity] = row
            self.storage.save(state)
            approvals.append_result(self.agent, row)

    def older_attachment(self):
        item = self.stage("older.txt", b"An older note about the greenhouse.")
        with self.storage.lock():
            self.app.threads.append(MAIN, "user", "Read this note.", attachment_ids=[item["id"]])

    def test_receipts_are_labeled_in_model_history_with_their_recorded_outcomes(self):
        self.receipt("deleted", "complete", {"message": "Deleted Run 44 greenhouse check."})
        self.receipt("mail", "sent", {"message": "AgentMail confirmed the send."})
        self.receipt("declined", "declined", {"message": "The user declined this action. It did not run."})
        self.receipt("failed", "failed", {"error": "The connector could not complete the action."})
        with self.storage.lock():
            self.app.threads.append(MAIN, "assistant", "Fixture automation reply.", source=event_automations.SOURCE)
            self.app.threads.append(MAIN, "assistant", "Fixture recurring task reply.", source=tasks.SOURCE)
            self.app.threads.append(MAIN, "assistant", "Ordinary reply.")
        original = self.app.threads.messages(MAIN)
        self.gateway.completion.return_value = {"content": "Yes, Hearth completed the deletion."}

        self.chat("Did you delete the greenhouse check?")

        messages = self.gateway.completion.call_args.args[1]
        self.assertIn("Acknowledge that result when asked about it", messages[0]["content"])
        self.assertNotIn("The latest user message includes attachments", messages[0]["content"])
        self.assertEqual(messages[2:-1], [{"role": "assistant", "content": content} for content in (
            "[Completed after your approval] Deleted Run 44 greenhouse check.",
            "[Completed after your approval] AgentMail confirmed the send.",
            "[Hearth approval outcome (declined)] The user declined this action. It did not run.",
            "[Hearth approval outcome (failed)] The connector could not complete the action.",
            "[Hearth automation run result] Fixture automation reply.",
            "[Hearth recurring task result] Fixture recurring task reply.",
            "Ordinary reply.",
        )])
        self.assertEqual(self.app.threads.messages(MAIN)[:len(original)], original)

    def test_short_chinese_question_is_grounded_in_the_latest_attachment(self):
        self.older_attachment()
        self.receipt("deleted", "complete", {"message": "Deleted Run 44 greenhouse check."})
        screenshot = self.image()
        self.gateway.completion.side_effect = [
            {"content": "截图上显示了一条关于预测市场的帖子。"},
            {"content": "截图显示有人这样声称。仅凭截图无法证实。[[A1]]"},
        ]

        answer = self.chat("这真的吗", [screenshot])

        self.assertEqual(self.gateway.completion.call_args_list[0].args[0]["model"], uploads.VISION_MODELS[0])
        messages = self.gateway.completion.call_args.args[1]
        self.assertIn("short or ambiguous question", messages[0]["content"])
        self.assertIn("“这真的吗”, or “这是什么” refers to the attachments sent with the latest user message",
                      messages[0]["content"])
        self.assertEqual(messages[-1], {"role": "user", "content": "这真的吗"})
        self.assertEqual(messages[-2]["content"], "[Completed after your approval] Deleted Run 44 greenhouse check.")
        current, earlier = json.loads(messages[1]["content"])["untrusted_reference_data"]["Attachment reference data"]
        self.assertTrue(current["sent_with_latest_user_message"])
        self.assertEqual(current["text"], "截图上显示了一条关于预测市场的帖子。")
        self.assertFalse(earlier["sent_with_latest_user_message"])
        self.assertEqual(earlier["filename"], "older.txt")
        self.assertEqual(answer["attachment_citations"], [screenshot["id"]])

    def test_failed_current_vision_requests_an_explicit_reply_about_the_unreadable_image(self):
        self.older_attachment()
        with self.storage.lock():
            self.app.threads.append(MAIN, "assistant", "What details should the page include?", page_question=True)
        screenshot = self.image()
        self.gateway.completion.side_effect = [
            *(ConnectorError("Vision unavailable", 503) for _ in uploads.VISION_MODELS),
            {"content": "我无法读取你刚发送的截图。[[A1]]"},
        ]

        answer = self.chat("这是什么", [screenshot])

        self.assertEqual([call.args[0]["model"] for call in self.gateway.completion.call_args_list[:-1]],
                         list(uploads.VISION_MODELS))
        messages = self.gateway.completion.call_args.args[1]
        self.assertIn("Explicitly tell the user in the reply that you couldn't read these current attachments: [[A1]]",
                      messages[0]["content"])
        self.assertNotIn("couldn't read these current attachments: [[A1]], [[A2]]", messages[0]["content"])
        failed, earlier = json.loads(messages[1]["content"])["untrusted_reference_data"]["Attachment reference data"]
        self.assertTrue(failed["sent_with_latest_user_message"])
        self.assertIn("could not describe this image", failed["note"])
        self.assertNotIn("text", failed)
        self.assertFalse(earlier["sent_with_latest_user_message"])
        self.assertEqual(answer["content"], "我无法读取你刚发送的截图。")
        self.assertEqual(answer["attachment_citations"], [screenshot["id"]])
