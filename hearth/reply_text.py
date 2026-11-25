import re

from .gateway_tools import redact_text


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
    r"<|-----|\b(?:api|access|refresh|sprites?|authorization|password|client|private|bearer)\b", re.I
)


def clean_reply(text):
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
