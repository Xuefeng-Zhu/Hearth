import io
import json
import tempfile
import unittest
from urllib.error import HTTPError

from hearth.agent import Agent
from hearth.checkpoints import LocalCheckpoints
from hearth.connectors import Gateway, read_config
from hearth.gateway_tools import validate_request
from hearth.storage import HearthError, ROOT, Storage


class TestGatewayTools(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.storage = Storage(temporary.name)
        self.checkpoints = LocalCheckpoints(self.storage)
        self.gateway = Gateway()
        self.requests = []
        self.gateway.opener = self
        self.config = read_config(ROOT / "config/connectors.json")
        self.config["gateway"] = {"future_tool": {"provider": "future_tool", "connection_id": "conn_future"}}
        self.agent = Agent(self.storage, self.checkpoints, self.config, self.gateway)

    def open(self, request, timeout):
        self.requests.append(request)
        if request.get_method() != "GET":
            checkpoint, = self.checkpoints.list()
            snapshot = self.checkpoints.root / checkpoint["id"] / "live" / "state.json"
            action, = json.loads(snapshot.read_text())["actions"].values()
            self.assertEqual(action["status"], "changing")
        return io.BytesIO(b'{"items": [1], "api_key": "placeholder-that-must-not-be-retained"}')

    def test_mock_can_read_any_discovered_provider(self):
        events = []
        self.agent.chat("Gateway future_tool GET /v1/items?limit=1", lambda name, data: events.append((name, data)))
        request, = self.requests
        self.assertEqual(request.get_method(), "GET")
        self.assertTrue(request.full_url.endswith("/future_tool/conn_future/v1/items?limit=1"))
        self.assertIsNone(request.data)
        messages = self.storage.load()["messages"]
        self.assertIn("[redacted]", messages[-1]["content"])
        self.assertNotIn("placeholder-that-must-not-be-retained", str(events))
        self.assertFalse(self.checkpoints.list())

    def test_non_get_waits_for_approval_and_checkpoint_and_cannot_replay(self):
        events = []
        self.agent.chat('Gateway future_tool PATCH /v1/items/1 | {"name": "Revised"}',
                        lambda name, data: events.append((name, data)))
        action, = [data for name, data in events if name == "action"]
        self.assertEqual(action["status"], "pending")
        self.assertFalse(self.requests)
        self.assertFalse(self.checkpoints.list())

        result = self.agent.approve(action["id"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["response"]["data"]["api_key"], "[redacted]")
        self.assertNotIn("response", self.storage.load()["actions"][action["id"]])
        request, = self.requests
        self.assertEqual(request.get_method(), "PATCH")
        self.assertEqual(json.loads(request.data), {"name": "Revised"})
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual(request.get_header("Idempotency-key"), action["id"])
        self.assertFalse(self.agent.can_undo(result))

        self.assertEqual(self.agent.approve(action["id"])["status"], "complete")
        self.checkpoints.restore(result["checkpoint"]["id"])
        with self.assertRaises(HearthError):
            self.agent.approve(action["id"])
        self.assertEqual(len(self.requests), 1)

    def test_connection_changes_and_checkpoint_failure_prevent_request(self):
        with self.storage.lock():
            action = self.agent.gateway_request("future_tool", "POST", "/v1/items")["action"]
        alternate = {"provider": "future_tool", "connection_id": "conn_alternate"}
        changed = Agent(self.storage, self.checkpoints, {**self.config, "gateway": {"future_tool": alternate}})
        with self.assertRaisesRegex(HearthError, "connection changed"):
            changed.approve(action["id"])

        def fail(comment):
            raise OSError("local checkpoint failed")

        self.checkpoints.create = fail
        with self.assertRaisesRegex(HearthError, "could not checkpoint"):
            self.agent.approve(action["id"])
        self.assertEqual(self.storage.load()["actions"][action["id"]]["status"], "pending")
        self.assertFalse(self.requests)

    def test_gateway_rejects_credential_arguments_and_escaping_paths(self):
        for path in ("//elsewhere.test/t", "https://elsewhere.test", "/../other", "/%2e%2e/other",
                     "/%252e%252e/other", "/a%5cb", "/v1?api_key=opaque", "/v1#bad"):
            with self.subTest(path=path), self.assertRaises(HearthError):
                validate_request("future_tool", "GET", path, None)
        with self.assertRaises(HearthError):
            validate_request("upstash", "GET", "/SET/name/changed", None)
        self.assertEqual(validate_request("upstash", "GET", "/GET/name", None), ("GET", "GET/name"))
        with self.assertRaises(HearthError):
            validate_request("future_tool", "POST", "/v1", {"api_key": "opaque"})
        self.agent.chat('Gateway future_tool POST /v1 | {"api_key":"opaque-user-input"}', lambda *_: None)
        self.assertNotIn("opaque-user-input", self.storage.state.read_text())
        self.assertFalse(self.requests)


class TestNativeModelProtocols(unittest.TestCase):
    def setUp(self):
        self.gateway = Gateway()
        self.gateway.opener = self
        self.model = "test-model"
        self.history = [{"role": "system", "content": "Use tools."}, {"role": "user", "content": "Read note."}]
        self.tools = [{"type": "function", "function": {"name": "memory_read", "description": "Read.",
                                                       "parameters": {"type": "object"}}}]
        self.options = {}
        self.emitted = []

    def open(self, request, timeout):
        self.options = (request.full_url, request.headers, json.loads(request.data))
        packets = b"".join(f"data: {json.dumps(packet)}\n\n".encode() for packet in self.packets)
        return io.BytesIO(packets)

    def complete(self, provider):
        return self.gateway.completion({"provider": provider, "connection_id": "conn_test", "model": self.model},
                                       self.history, self.tools, self.emitted.append)

    def test_anthropic_streams_tool_call_and_sends_tool_result(self):
        self.packets = [
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "tool_use", "id": "toolu_demo", "name": "memory_read", "input": {}}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "input_json_delta", "partial_json": '{"path":'}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "input_json_delta", "partial_json": '"USER.md"}'}},
            {"type": "message_stop"},
        ]
        reply = self.complete("anthropic")
        url, headers, body = self.options
        self.assertTrue(url.endswith("/anthropic/conn_test/v1/messages"))
        self.assertEqual(headers["Anthropic-version"], "2023-06-01")
        self.assertNotIn("Authorization", headers)
        self.assertEqual(body["system"], "Use tools.")
        self.assertEqual(body["tools"][0]["input_schema"], {"type": "object"})
        call, = reply["tool_calls"]
        self.assertEqual(json.loads(call["function"]["arguments"]), {"path": "USER.md"})
        self.history += [reply, {"role": "tool", "tool_call_id": call["id"], "content": "{}"}]
        self.packets = [{"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Read."}},
                        {"type": "message_stop"}]
        self.assertEqual(self.complete("anthropic")["content"], "Read.")
        result, = self.options[2]["messages"][-1]["content"]
        self.assertEqual(result["tool_use_id"], "toolu_demo")

    def test_gemini_preserves_native_function_ids_and_thought_signatures(self):
        part = {"functionCall": {"id": "fn_demo", "name": "memory_read", "args": {"path": "USER.md"}},
                "thoughtSignature": "opaque-test-signature"}
        self.packets = [{"candidates": [{"content": {"parts": [part]}, "finishReason": "STOP"}]}]
        reply = self.complete("gemini")
        self.assertTrue(self.options[0].endswith("/gemini/conn_test/v1beta/models/test-model:streamGenerateContent?alt=sse"))
        self.assertEqual(self.options[2]["tools"][0]["functionDeclarations"][0]["parametersJsonSchema"],
                         {"type": "object"})
        call, = reply["tool_calls"]
        self.history += [reply, {"role": "tool", "tool_call_id": call["id"], "content": '{"content":"sample"}'}]
        self.packets = [{"candidates": [{"content": {"parts": [{"text": "Read."}]}, "finishReason": "STOP"}]}]
        self.assertEqual(self.complete("gemini")["content"], "Read.")
        conversation = self.options[2]["contents"]
        self.assertEqual(conversation[-2]["parts"], [part])
        self.assertEqual(conversation[-1]["parts"],
                         [{"functionResponse": {"id": "fn_demo", "name": "memory_read",
                                                "response": {"content": "sample"}}}])

    def test_huggingface_streams_fragmented_tool_calls_and_text(self):
        self.packets = [
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_demo",
                 "function": {"name": "memory_read", "arguments": '{"path":'}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0,
                 "function": {"arguments": '"USER.md"}'}}]}, "finish_reason": "tool_calls"}]},
        ]
        reply = self.complete("huggingface")
        url, headers, body = self.options
        self.assertTrue(url.endswith("/huggingface/conn_test/v1/chat/completions"))
        self.assertNotIn("Authorization", headers)
        self.assertTrue(body["stream"])
        self.assertEqual(body["tools"], self.tools)
        call, = reply["tool_calls"]
        self.assertEqual(json.loads(call["function"]["arguments"]), {"path": "USER.md"})
        self.history += [reply, {"role": "tool", "tool_call_id": "call_demo", "content": "{}"}]
        self.packets = [{"choices": [{"delta": {"content": "Read"}}]},
                        {"choices": [{"delta": {"content": "."}, "finish_reason": "stop"}]}]
        self.assertEqual(self.complete("huggingface")["content"], "Read.")
        self.assertEqual(self.emitted, ["Read", "."])
        self.assertEqual(self.options[2]["messages"][-1]["tool_call_id"], "call_demo")

    def test_huggingface_retries_without_native_tools_and_continues_in_json_mode(self):
        payloads = []

        def open_request(request, timeout):
            body = json.loads(request.data)
            payloads.append(body)
            if "tools" in body:
                raise HTTPError(request.full_url, 400, "Bad request", {}, io.BytesIO(b"private provider details"))
            return self.open(request, timeout)

        self.gateway.opener = type("Opener", (), {"open": staticmethod(open_request)})()
        self.packets = [{"choices": [{"delta": {"content":
            '{"tool_calls":[{"name":"memory_read","arguments":{"path":"USER.md"}}]}'}, "finish_reason": "stop"}]}]
        reply = self.complete("huggingface")
        call, = reply["tool_calls"]
        self.assertEqual(call["function"]["name"], "memory_read")
        self.assertEqual(self.emitted, [])
        self.assertNotIn("tools", payloads[-1])
        self.assertIn("memory_read", payloads[-1]["messages"][0]["content"])
        self.history += [reply, {"role": "tool", "tool_call_id": call["id"], "content": '{"note":"sample"}'}]
        self.packets = [{"choices": [{"delta": {"content": '{"reply":"Read it."}'}, "finish_reason": "stop"}]}]
        self.assertEqual(self.complete("huggingface")["content"], "Read it.")
        self.assertEqual(self.emitted, ["Read it."])
        self.assertEqual(len(payloads), 3)
        self.assertNotIn("tools", payloads[-1])
        self.assertEqual(payloads[-1]["messages"][-1]["role"], "user")
        self.assertIn('{"note":"sample"}', payloads[-1]["messages"][-1]["content"])
