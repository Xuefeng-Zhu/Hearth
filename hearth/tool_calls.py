"""Tool-call arguments and model-facing results shared by chat and workers."""

import json
import re

from . import browserbase
from .reminder_config import channel_from_prompt
from .storage import HearthError

INVALID_ARGUMENTS = "The tool received invalid arguments."
UNTRUSTED_RESULT_TOOLS = {"memory_read", "memory_search", "web_search", "gateway_request", "read_artifact",
                          "spawn_workers", *browserbase.TOOL_NAMES}


def decode_arguments(function, prompt):
    arguments = json.loads(function["arguments"])
    if function["name"] == "schedule" and isinstance(arguments, dict):
        arguments["channel"] = channel_from_prompt(prompt)
        arguments["urgent"] = bool(re.search(r"\b(?:urgent|urgently|even during quiet hours)\b", prompt, re.I))
    return arguments


def require_argument_object(arguments):
    if not isinstance(arguments, dict):
        raise HearthError("Tool arguments must be an object.")


def check_available(name, available, loading_skill, *, unavailable):
    if name not in available:
        raise HearthError(unavailable)
    if loading_skill and name != "skill_load":
        raise HearthError("Read the loaded skill before requesting other tools.")


def result_message(call, result, turn, *, serialize=None):
    call_id = call["id"]
    if call["function"]["name"] in UNTRUSTED_RESULT_TOOLS and not result.get("error"):
        turn["untrusted_evidence"] = True
        result = {**result, "untrusted": True}
    content = serialize(result) if serialize else json.dumps(result, ensure_ascii=False)
    return {"role": "tool", "tool_call_id": call_id, "content": content}
