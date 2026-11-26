"""Tool-call arguments and model-facing results shared by chat and workers."""

import json
import re

from . import browserbase
from .connectors import ConnectorError
from .reminder_config import channel_from_prompt
from .storage import HearthError

INVALID_ARGUMENTS = "The tool received invalid arguments."
RESULT_PREVIEW_LIMIT = 12_000
PARENT_CONTEXT_LIMIT = 128_000
RESEARCH_EVIDENCE_LIMIT = 32_000
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


def truncated_result(preview, *, untrusted):
    return json.dumps({"truncated": True, "preview": preview, **({"untrusted": True} if untrusted else {})},
                      ensure_ascii=False)


def tool_text(result, *, capped=True):
    text = json.dumps(result, ensure_ascii=False)
    if not capped or len(text) <= RESULT_PREVIEW_LIMIT:
        return text
    return truncated_result(text[:RESULT_PREVIEW_LIMIT], untrusted=isinstance(result, dict) and
                            result.get("untrusted") is True)


def result_message(call, result, turn, *, capped=True):
    call_id = call["id"]
    if call["function"]["name"] in UNTRUSTED_RESULT_TOOLS and not result.get("error"):
        turn["untrusted_evidence"] = True
        result = {**result, "untrusted": True}
    return {"role": "tool", "tool_call_id": call_id, "content": tool_text(result, capped=capped)}


def largest_first(sizes, indices):
    # Keep newer evidence when equally sized results compete for space.
    return sorted(indices, key=lambda index: -sizes[index])


def parent_context(messages, tools, initial_count):
    # Use the gateway's ASCII-safe JSON encoding to include escaping and tool declarations.
    remaining = PARENT_CONTEXT_LIMIT - len(json.dumps({"messages": [], "tools": tools}))
    sizes = [len(json.dumps(message)) + 2 for message in messages]
    excess = sum(sizes) - remaining
    if excess <= 0:
        return messages

    messages = messages.copy()

    def replace(index, message):
        nonlocal excess
        size = len(json.dumps(message)) + 2 if message is not None else 0
        excess += size - sizes[index]
        sizes[index] = size
        messages[index] = message

    results = (index for index in range(initial_count, len(messages)) if messages[index]["role"] == "tool")
    for index in largest_first(sizes, results):
        message = messages[index]
        content = truncated_result("", untrusted=json.loads(message["content"]).get("untrusted") is True)
        limited = {**message, "content": content}
        if len(json.dumps(limited)) + 2 < sizes[index]:
            replace(index, limited)
        if excess <= 0:
            return messages

    # Keep the system instructions and current user request.
    for index in range(2, initial_count - 1):
        replace(index, None)
        if excess <= 0:
            break
    if excess > 0 and initial_count > 2:
        message = messages[1]
        reference = json.loads(message["content"])["untrusted_reference_data"]
        while excess > 0 and reference:
            key = max(reference, key=lambda key: len(json.dumps(reference[key])))
            value = reference[key]
            if isinstance(value, list) and len(value) > 1:
                reference[key] = value[:len(value) // 2]
            else:
                del reference[key]
            content = json.dumps({"untrusted_reference_data": reference, "truncated": True}, ensure_ascii=False)
            replace(1, {**message, "content": content})

    # Exceptionally large tool arguments can fill the remaining budget. Drop a whole round
    # at a time so every retained native call still has exactly one matching result.
    for index in range(initial_count, len(messages)):
        if excess <= 0 and messages[index]["role"] == "assistant":
            break
        replace(index, None)
    if excess > 0:
        raise ConnectorError("The model context exceeded Hearth's size limit.")
    return [message for message in messages if message is not None]


def research_evidence(results):
    lines = [f"{name}: {tool_text(result)}" for name, result in results]
    sizes = [len(json.dumps(line)) + 2 for line in lines]
    excess = sum(sizes) - RESEARCH_EVIDENCE_LIMIT
    for index in largest_first(sizes, range(len(lines))):
        if excess <= 0:
            break
        name, result = results[index]
        line = f"{name}: {truncated_result('', untrusted=result.get('untrusted') is True)}"
        excess += len(json.dumps(line)) + 2 - sizes[index]
        lines[index] = line
    return "\n".join(lines)
