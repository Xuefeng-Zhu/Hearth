import json
import re

from .gateway_tools import redact_text
from .storage import new_id


TOOL_TAG = r"function(?:_call)?|tool_calls?|tool_response"
TOOL_MARKUP = re.compile(
    rf"<\s*(?:{TOOL_TAG})(?=[\s=/])[^>]*?/>"
    rf"|<\s*(?P<tag>{TOOL_TAG})(?=[\s=>])[^>]*>"
    r".*?(?:<\s*/\s*(?P=tag)\s*>|\Z)"
    rf"|<\s*/\s*(?:{TOOL_TAG})(?=[\s=>])[^>]*>"
    rf"|<\s*/?\s*(?:{TOOL_TAG})(?=[\s=/]|\Z)[^>]*\Z"
    r"|<\|(?:im_start|im_end|eot_id|end_of_text|start_header_id|end_header_id)\|>",
    re.I | re.S,
)
# These can begin a credential assignment or private key that spans model chunks.
UNSAFE_PREFIX = re.compile(
    r"<|\{|\[\s*\{|\b[\w.-]+\s*>|\x60\x60\x60|-----|"
    r"\b(?:api|access|refresh|sprites?|authorization|password|client|private|bearer)\b", re.I
)

TEXT_CALL = re.compile(
    r"<\s*tool_calls?\s*>|<\|python_tag\|>|"
    r"(?P<name>[a-z_]\w*)\s*>(?=\s*\{)|"
    r"(?P<partial>\b[a-z]+_[a-z_]+\s*>)(?=\s*$)|"
    r"\x60\x60\x60(?:json\b)?[ \t]*\r?\n(?=\s*[\[{])|"
    r"(?P<bare>\{\s*\"(?:name|function|tool|tool_calls|arguments|parameters|type)\")",
    re.I,
)
TOOL_END = re.compile(r"\s*(?:<\s*/\s*tool_calls?\s*>|\x60\x60\x60)", re.I)
TAGGED_NAME = re.compile(r"([a-z_]\w*)\s*>\s*", re.I)
DECODER = json.JSONDecoder()


def text_tool_calls(text, *, keep_worker_result=False):
    """Separate textual tool envelopes from prose before either is shown or persisted."""
    calls, prose = [], []
    malformed = False
    end = 0
    while match := TEXT_CALL.search(text, end):
        prose.append(text[end:match.start()])
        start = match.start() if match["bare"] else match.end()
        start += len(text[start:]) - len(text[start:].lstrip())
        name = match["name"]
        if match[0].lower() == "<|python_tag|>" and (tagged := TAGGED_NAME.match(text, start)):
            name = tagged[1]
            start = tagged.end()
        try:
            value, end = DECODER.raw_decode(text, start)
            if closing := TOOL_END.match(text, end):
                end = closing.end()
            if (keep_worker_result and match[0].startswith("```") and isinstance(value, dict)
                    and "summary" in value and value.keys() <= {"summary", "sources"}):
                prose.append(text[match.start():end])
                continue
            if name:
                value = {"name": name, "arguments": value}
            entries = value.get("tool_calls", [value]) if isinstance(value, dict) else value
            parsed = []
            for entry in entries:
                function = entry.get("function", entry)
                name = function.get("name") or function.get("tool")
                args = function.get("arguments", function.get("parameters", function.get("args", {})))
                if isinstance(args, str):
                    args = json.loads(args)
                if not isinstance(name, str) or not re.fullmatch(r"[a-z_]\w*", name, re.I) or not isinstance(args, dict):
                    raise ValueError("Invalid textual tool call")
                parsed.append({"type": "function", "id": new_id(),
                               "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})
            if not parsed:
                raise ValueError("Empty textual tool call")
            calls.extend(parsed)
        except (AttributeError, TypeError, ValueError, RecursionError):
            malformed = True
            if end <= match.start():
                closing = TOOL_END.search(text, start)
                end = closing.end() if closing else len(text)
    prose.append(text[end:])
    return "".join(prose), calls, malformed


def clean_reply(text, *, keep_worker_result=False):
    text, _, _ = text_tool_calls(text, keep_worker_result=keep_worker_result)
    return redact_text(TOOL_MARKUP.sub("", text))


class ReplyStream:
    def __init__(self, emit):
        self.emit = emit
        self.pending = ""
        self.held = False

    def write(self, text):
        self.pending += text
        if self.held:
            return
        # A word can be a credential even if the provider divides it into several deltas.
        cut = max(self.pending.rfind(char) for char in (" ", "\n", "\r", "\t")) + 1
        if not cut:
            return
        if match := UNSAFE_PREFIX.search(self.pending, 0, cut):
            self.held = True
            cut = max(self.pending.rfind(char, 0, match.start()) for char in (" ", "\n", "\r", "\t")) + 1
        if cut:
            self.emit(redact_text(self.pending[:cut]))
            self.pending = self.pending[cut:]

    def finish(self):
        if text := clean_reply(self.pending):
            self.emit(text)
