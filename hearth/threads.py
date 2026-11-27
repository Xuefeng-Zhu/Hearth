import json
import tempfile
from collections import deque
from datetime import datetime
from hashlib import sha256
from itertools import chain, islice
from pathlib import Path

from . import memory
from .gateway_tools import redact_text
from .reply_text import clean_reply
from .storage import HearthError, atomic_write, iso, new_id, revision

MAIN = "main"
SIDE_TITLE = "New side chat"
MAIN_ORIGIN = {"thread_id": MAIN, "thread_title": "Main"}
HISTORY_WINDOW = 16
SUMMARY_TRIGGER = 8
TRANSCRIPT_SIZE = 50
SIDEBAR_SIZE = 100


def compact(text, limit):
    line = " ".join(text.split())
    if len(line) > limit:
        return line[:limit - 1].rsplit(" ", 1)[0] + "…"
    return line


def older_dialogue(dialogue, after=None):
    """Return messages outside the prompt window and after the saved cursor."""
    start = next((i + 1 for i, row in enumerate(dialogue) if row["id"] == after), 0)
    return dialogue[start:max(0, len(dialogue) - HISTORY_WINDOW)]


class InvalidSummary(ValueError):
    pass


def reverse_lines(stream, end):
    """Yield JSONL records newest first, with their byte offsets."""
    prefix = b""
    while end:
        start = max(0, end - 8192)
        stream.seek(start)
        lines = (stream.read(end - start) + prefix).split(b"\n")
        prefix = lines[0] if start else b""
        offset = start + sum(len(line) + 1 for line in lines)
        for line in reversed(lines[bool(start):]):
            offset -= len(line) + 1
            if line:
                yield offset, line
        end = start


def clean_message(row):
    clean = clean_reply if row["role"] == "assistant" else redact_text
    return {**row, "content": clean(row["content"])}


def model_content(row, actions):
    content = row["content"]
    if row["role"] != "assistant" or content == "[forgotten]":
        return content
    source = row.get("source")
    if source == "approval":
        status = actions.get(row.get("approval_id"), {}).get("status")
        if status in {"complete", "sent"}:
            return f"[Completed after your approval] {content}"
        label = f"Hearth approval outcome ({status.replace('_', ' ')})" if status else "Hearth approval outcome"
        return f"[{label}] {content}"
    if source == "event-automation":
        return f"[Hearth automation run result] {content}"
    if source == "recurring-task":
        return f"[Hearth recurring task result] {content}"
    return content


def record_id(thread_id, position, row):
    return row.get("id") or f"{thread_id}:{position}"


class Threads:
    """Thread files and their index are read and changed under Storage.lock()."""

    def __init__(self, storage):
        self.storage = storage
        self.root = storage.live / "threads"
        self.index = self.root / "index.json"
        self.sidebar_cache = {}

    def load_index(self):
        sides = json.loads(self.index.read_text(encoding="utf-8")) if self.index.is_file() else {}
        return {MAIN: {"title": "Main"}, **sides}

    def save_index(self, index):
        self.storage.bump_revision(threads=True)
        atomic_write(self.index, json.dumps({key: value for key, value in index.items() if key != MAIN},
                                           ensure_ascii=False))

    def path(self, thread_id):
        return self.root / f"{thread_id}.jsonl"

    def summary_path(self, thread_id):
        return self.root / thread_id / "summary.json"

    def summary_state(self, thread_id):
        self.require(thread_id)
        try:
            state = json.loads(self.summary_path(thread_id).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (ValueError, RecursionError):
            raise InvalidSummary("Invalid thread summary.") from None
        if (not isinstance(state, dict) or not isinstance(state.get("text"), str)
                or any(state.get(key) is not None and not isinstance(state[key], str) for key in ("cursor", "reset_after"))):
            raise InvalidSummary("Invalid thread summary.")
        return state

    def save_summary(self, thread_id, state):
        self.require(thread_id)
        self.storage.bump_revision()
        atomic_write(self.summary_path(thread_id), json.dumps(state, ensure_ascii=False))

    def summary(self, thread_id):
        try:
            text = self.summary_state(thread_id).get("text", "")
            return "" if text and memory.matches_rule(text, memory.standing_rules(self.storage)) else text
        except (OSError, ValueError):
            # A summary is optional context, even if reading it fails.
            return ""

    def reset_summary(self, thread_id):
        older = self.messages(thread_id, dialogue_only=True, limit=HISTORY_WINDOW + 1)
        self.save_summary(thread_id, {"text": "", "cursor": None, "reset": new_id(),
                                      "reset_after": older[0]["id"] if len(older) > HISTORY_WINDOW else None})

    def require(self, thread_id, index=None):
        index = self.load_index() if index is None else index
        if not isinstance(thread_id, str) or thread_id not in index:
            raise HearthError("That chat no longer exists.")
        return index[thread_id]

    def messages(self, thread_id, limit=None, *, dialogue_only=False):
        self.require(thread_id)
        path = self.path(thread_id)
        if not path.is_file():
            legacy = self.storage.load().get("messages", []) if thread_id == MAIN else []
            messages = (message for message in legacy if not dialogue_only or message["role"] != "call")
            rows = list(messages if limit is None else deque(messages, maxlen=limit))
        else:
            with path.open(encoding="utf-8") as stream:
                messages = (json.loads(line) for line in stream)
                if dialogue_only:
                    messages = (message for message in messages if message["role"] != "call")
                rows = list(messages if limit is None else deque(messages, maxlen=limit))
        return [clean_message(row) for row in rows]

    def model_history(self, rows):
        actions = self.storage.load()["actions"] if any(row.get("source") == "approval" for row in rows) else {}
        return [{**row, "content": model_content(row, actions)} for row in rows]

    def search_records(self, thread_id):
        path = self.path(thread_id)
        if path.is_file():
            with path.open("rb") as stream:
                offset = 0
                for line in stream:
                    yield offset, json.loads(line)
                    offset += len(line)
        elif thread_id == MAIN:
            yield from enumerate(self.storage.load().get("messages", ()), 1)

    def page_around(self, thread_id, state, message_id):
        """Find a message's record and use the usual cursor to read its window."""
        path = self.path(thread_id)
        half = TRANSCRIPT_SIZE // 2
        if not path.is_file():
            rows = state.get("messages", []) if thread_id == MAIN else []
            for index, row in enumerate(rows):
                if record_id(thread_id, index + 1, row) == message_id:
                    end = index + half
                    before = f"l:{end}" if end < len(rows) else None
                    return (*self.page(thread_id, state, before), bool(before))
            return None
        with path.open("rb") as stream:
            newer = deque(maxlen=half)
            for offset, raw in reverse_lines(stream, stream.seek(0, 2)):
                row = json.loads(raw)
                if record_id(thread_id, offset, row) == message_id:
                    before = None
                    if len(newer) == half:
                        boundary, line = newer[0]
                        before = f"{boundary}:{sha256(line).hexdigest()[:16]}"
                    return (*self.page(thread_id, state, before), bool(before))
                newer.append((offset, raw))
        return None

    def page(self, thread_id, state, before=None):
        """Page by a validated record boundary that stays valid after appends."""
        path = self.path(thread_id)
        if not path.is_file():
            rows = state.get("messages", []) if thread_id == MAIN else []
            end = len(rows)
            if before is not None:
                if not before.startswith("l:") or len(before) > 20 or not before[2:].isascii() or not before[2:].isdigit():
                    raise HearthError("That transcript cursor is no longer available.")
                end = int(before[2:])
                if not 0 < end <= len(rows):
                    raise HearthError("That transcript cursor is no longer available.")
            start = max(0, end - TRANSCRIPT_SIZE)
            prompt = None
            if start and rows[start]["role"] != "user":
                earlier = reversed(rows[max(0, start - TRANSCRIPT_SIZE):start])
                prompt = next((row for row in earlier if row["role"] == "user"), None)
            return ([clean_message({**row, "id": record_id(thread_id, i, row)})
                     for i, row in enumerate(rows[start:end], start + 1)],
                    f"l:{start}" if start else None, clean_message(prompt) if prompt else None)
        with path.open("rb") as stream:
            end = stream.seek(0, 2)
            if before is not None:
                marker, _, checksum = before.partition(":")
                if not marker.isascii() or not marker.isdigit() or len(marker) > 18 or len(checksum) != 16:
                    raise HearthError("That transcript cursor is no longer available.")
                offset = int(marker)
                if not 0 < offset < end:
                    raise HearthError("That transcript cursor is no longer available.")
                stream.seek(offset - 1)
                if stream.read(1) != b"\n" or sha256(stream.readline().rstrip(b"\n")).hexdigest()[:16] != checksum:
                    raise HearthError("That transcript cursor is no longer available.")
                end = offset
            lines = reverse_lines(stream, end)
            records = list(islice(lines, TRANSCRIPT_SIZE))
            earlier = next(lines, None)
            older = prompt = None
            if earlier:
                boundary, line = records[-1]
                older = f"{boundary}:{sha256(line).hexdigest()[:16]}"
                if json.loads(line)["role"] != "user":
                    candidates = (json.loads(raw) for _, raw in islice(chain([earlier], lines), TRANSCRIPT_SIZE))
                    prompt = next((row for row in candidates if row["role"] == "user"), None)
        messages = []
        for offset, line in reversed(records):
            row = json.loads(line)
            messages.append(clean_message({**row, "id": record_id(thread_id, offset, row)}))
        return messages, older, clean_message(prompt) if prompt else None

    def last_reply(self, thread_id, legacy=()):
        """Read the newest assistant ID without loading every thread's history."""
        path = self.path(thread_id)
        if not path.is_file():
            return next((row.get("id") for row in reversed(legacy) if row["role"] == "assistant"), None)
        with path.open("rb") as stream:
            for _, line in reverse_lines(stream, stream.seek(0, 2)):
                row = json.loads(line)
                if row["role"] == "assistant":
                    return row.get("id")
        return None

    def recent_messages(self, thread_id, since, legacy):
        """Read today's dialogue and enough preceding records for Home's five recent events."""
        def collect(records):
            rows = []
            older = 0
            cutoff = None
            for row in records:
                if row.get("at"):
                    at = datetime.fromisoformat(row["at"])
                    if cutoff is not None and at < cutoff and row["role"] != "call":
                        if row["role"] == "user":
                            rows.append(row)  # Preserve the prompt for the first reply at the boundary.
                        break
                    if at < since:
                        older += 1
                        if older == 12:
                            cutoff = at
                rows.append(row)
            return list(reversed(rows))

        path = self.path(thread_id)
        if not path.is_file():
            return collect(reversed(legacy)) if thread_id == MAIN else []
        with path.open("rb") as stream:
            return collect(json.loads(line) for _, line in reverse_lines(stream, stream.seek(0, 2)))

    def sidebar(self, index, active, legacy, offset=0, selected=None):
        ids = list(index)
        visible = ids[offset:offset + SIDEBAR_SIZE]
        if selected is not None and selected not in visible:
            visible.append(selected)
        rows = []
        self.sidebar_cache = {key: value for key, value in self.sidebar_cache.items() if key in index}
        for identity in visible:
            stamp = index[identity], revision(self.path(identity))
            cached = self.sidebar_cache.get(identity)
            if not cached or cached[0] != stamp:
                row = self.describe(identity, index)
                row["last_reply"] = self.last_reply(identity)
                self.sidebar_cache[identity] = stamp, row
            else:
                row = cached[1]
            if identity == MAIN and legacy and stamp[1] == (None,):
                row = {**row, "last_reply": self.last_reply(MAIN, legacy)}
            rows.append({**row, "busy": identity in active,
                         **({"activity": active[identity]} if active.get(identity) else {})})
        next_offset = offset + SIDEBAR_SIZE
        return rows, next_offset if next_offset < len(ids) else None

    def append(self, thread_id, role, content, **fields):
        self.require(thread_id)
        message = {"id": new_id(), "role": role, "content": content, "at": iso(), **fields}
        path = self.path(thread_id)
        legacy = None
        if path.is_file():
            previous = path.read_text(encoding="utf-8")
        else:
            legacy = self.storage.load() if thread_id == MAIN else {}
            previous = "".join(json.dumps({**item, "id": record_id(thread_id, index, item)}, ensure_ascii=False) + "\n"
                               for index, item in enumerate(legacy.get("messages", ()), 1))
        self.storage.bump_revision(threads=True)
        atomic_write(path, previous + json.dumps(message, ensure_ascii=False) + "\n")
        if legacy is not None and "messages" in legacy:
            del legacy["messages"]
            self.storage.save(legacy)
        return message

    def update_side_summary(self, thread_id, message, summary):
        if thread_id not in self.load_index():
            return
        path = self.path(thread_id)
        with path.open(encoding="utf-8") as stream:
            lines = list(stream)
        for index, line in enumerate(reversed(lines), 1):
            row = json.loads(line)
            if row.get("id") == message["id"]:
                if row["content"] == message["content"] and row.get("summary") == message["summary"]:
                    row["summary"] = summary
                    lines[-index] = json.dumps(row, ensure_ascii=False) + "\n"
                    atomic_write(path, "".join(lines))
                return

    def describe(self, thread_id, index=None):
        thread = self.require(thread_id, index)
        title = thread.get("title")
        path = self.path(thread_id)
        if not title and path.is_file():
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    first = json.loads(line)
                    if first["role"] != "call":
                        title = compact(first["content"], 54)
                        break
        return {"id": thread_id, "title": title or SIDE_TITLE, **({"skill": thread["skill"]} if "skill" in thread else {})}

    def list(self):
        index = self.load_index()
        return [self.describe(thread_id, index) for thread_id in index]

    def create(self, *, title=None, panel_context=None, skill=None):
        index = self.load_index()
        thread_id = new_id()
        index[thread_id] = {"created_at": iso()}
        if title is not None:
            index[thread_id]["title"] = title
        if panel_context is not None:
            index[thread_id]["panel_context"] = panel_context
        if skill is not None:
            index[thread_id]["skill"] = skill
        self.save_index(index)
        return self.describe(thread_id, index)

    def rename(self, thread_id, title):
        index = self.load_index()
        self.require_side(thread_id, index)["title"] = title
        self.save_index(index)
        return self.describe(thread_id, index)

    def require_side(self, thread_id, index=None):
        thread = self.require(thread_id, index)
        if thread_id == MAIN:
            raise HearthError("Main is pinned and cannot be renamed, deleted, or shared to itself.")
        return thread

    def delete(self, thread_id):
        index = self.load_index()
        self.require_side(thread_id, index)
        data = self.root / thread_id
        with tempfile.TemporaryDirectory(dir=self.storage.root, ignore_cleanup_errors=True) as temporary:
            staged = Path(temporary) / thread_id
            if data.is_dir():
                data.rename(staged)
            try:
                self.save_index({key: value for key, value in index.items() if key != thread_id})
                self.path(thread_id).unlink(missing_ok=True)
            except OSError:
                if staged.exists():
                    staged.rename(data)
                self.save_index(index)
                raise

    def context(self, thread_id, *, rolling=True):
        if thread_id != MAIN:
            rows = self.model_history(self.messages(MAIN, limit=6, dialogue_only=True))
            recent = [{"role": message["role"], "excerpt": compact(message["content"], 390)}
                      for message in rows]
            return "Recent Main excerpts for read-only reference", recent
        summaries = []
        for thread in self.list()[1:]:
            recent = self.messages(thread["id"], limit=2, dialogue_only=True)
            if not recent:
                continue
            summary = next((message["summary"] for message in reversed(recent) if message.get("summary")),
                           "The user opened a discussion about this topic.")
            reference = {"title": thread["title"], "summary": compact(summary, 220)}
            if rolling and (earlier := self.summary(thread["id"])):
                reference["earlier"] = compact(earlier, 400)
            summaries.append(reference)
        return "Side chat summaries for reference", summaries
