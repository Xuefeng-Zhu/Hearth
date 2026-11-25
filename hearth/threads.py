import json
import tempfile
from collections import deque
from pathlib import Path

from .gateway_tools import redact_text
from .reply_text import clean_reply
from .storage import HearthError, atomic_write, iso, new_id

MAIN = "main"
SIDE_TITLE = "New side chat"
MAIN_ORIGIN = {"thread_id": MAIN, "thread_title": "Main"}


def compact(text, limit):
    line = " ".join(text.split())
    if len(line) > limit:
        return line[:limit - 1].rsplit(" ", 1)[0] + "…"
    return line


class Threads:
    """Thread files and their index are read and changed under Storage.lock()."""

    def __init__(self, storage):
        self.storage = storage
        self.root = storage.live / "threads"
        self.index = self.root / "index.json"

    def load_index(self):
        sides = json.loads(self.index.read_text(encoding="utf-8")) if self.index.is_file() else {}
        return {MAIN: {"title": "Main"}, **sides}

    def save_index(self, index):
        atomic_write(self.index, json.dumps({key: value for key, value in index.items() if key != MAIN},
                                           ensure_ascii=False))

    def path(self, thread_id):
        return self.root / f"{thread_id}.jsonl"

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
        for message in rows:
            clean = clean_reply if message["role"] == "assistant" else redact_text
            message["content"] = clean(message["content"])
        return rows

    def append(self, thread_id, role, content, **fields):
        self.require(thread_id)
        message = {"id": new_id(), "role": role, "content": content, "at": iso(), **fields}
        path = self.path(thread_id)
        legacy = None
        if path.is_file():
            previous = path.read_text(encoding="utf-8")
        else:
            legacy = self.storage.load() if thread_id == MAIN else {}
            previous = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in legacy.get("messages", []))
        atomic_write(path, previous + json.dumps(message, ensure_ascii=False) + "\n")
        if legacy is not None and "messages" in legacy:
            del legacy["messages"]
            self.storage.save(legacy)
        return message

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
        return {"id": thread_id, "title": title or SIDE_TITLE}

    def list(self):
        index = self.load_index()
        return [self.describe(thread_id, index) for thread_id in index]

    def create(self, *, title=None, panel_context=None):
        index = self.load_index()
        thread_id = new_id()
        index[thread_id] = {"created_at": iso()}
        if title is not None:
            index[thread_id]["title"] = title
        if panel_context is not None:
            index[thread_id]["panel_context"] = panel_context
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

    def context(self, thread_id):
        if thread_id != MAIN:
            recent = [{"role": message["role"], "excerpt": compact(message["content"], 390)}
                      for message in self.messages(MAIN, limit=6, dialogue_only=True)]
            return "Recent Main excerpts for read-only reference", recent
        summaries = []
        for thread in self.list()[1:]:
            recent = self.messages(thread["id"], limit=2, dialogue_only=True)
            if not recent:
                continue
            summary = next((message["summary"] for message in reversed(recent) if message.get("summary")),
                           "The user opened a discussion about this topic.")
            summaries.append({"title": thread["title"], "summary": summary})
        return "Side chat summaries for reference", summaries
