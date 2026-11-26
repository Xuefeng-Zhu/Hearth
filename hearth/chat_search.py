"""A disposable search index over the workspace's JSONL transcripts."""

import base64
import binascii
import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone

from .gateway_tools import redact_text
from .reply_text import TOOL_MARKUP, clean_reply
from .storage import HearthError, revision
from .threads import MAIN, SIDE_TITLE, compact, record_id

PAGE_SIZE = 50
PRIVATE_BLOCK = re.compile(
    r"<\s*(?P<tag>system|developer|hidden|thinking|think|analysis|reasoning|tool|tool_result)(?=[\s>])[^>]*>"
    r".*?(?:<\s*/\s*(?P=tag)\s*>|\Z)"
    r"|<\|im_start\|>\s*(?:system|developer|tool|analysis)\b.*?(?:<\|im_end\|>|\Z)"
    r"|<\|start_header_id\|>\s*(?:system|developer|tool|analysis)\s*<\|end_header_id\|>"
    r".*?(?:<\|eot_id\|>|\Z)"
    r"|<\|channel\|>\s*(?:analysis|commentary)\s*<\|message\|>"
    r".*?(?:<\|end\|>|(?=<\|channel\|>final)|\Z)"
    r"|<\|channel\|>final|<\|(?:message|end)\|>|<\|start\|>assistant",
    re.I | re.S,
)


def fold(text):
    return "".join(char for char in unicodedata.normalize("NFD", text.casefold())
                   if not unicodedata.category(char).startswith("M"))


def visible_text(row):
    text = TOOL_MARKUP.sub("", PRIVATE_BLOCK.sub("", row["content"]))
    text = clean_reply(text) if row["role"] == "assistant" else redact_text(text)
    return " ".join(text.replace("\x00", " ").split())


def snippet(text, query):
    folded = []
    offsets = []
    for index, char in enumerate(text):
        piece = fold(char)
        folded.append(piece)
        offsets.extend([index] * len(piece))
    normalized = "".join(folded)
    first = normalized.index(query)
    start = max(0, offsets[first] - 55)
    end = min(len(text), max(start + 165, offsets[first + len(query) - 1] + 56))
    parts = [{"text": "…"}] if start else []
    tail = start
    while first >= 0 and offsets[first] < end:
        left = max(offsets[first], tail)
        last = first + len(query)
        right = offsets[last - 1] + 1
        while right < len(text) and unicodedata.category(text[right]).startswith("M"):
            right += 1
        right = min(right, end)
        if left > tail:
            parts.append({"text": text[tail:left]})
        if right > left:
            parts.append({"text": text[left:right], "match": True})
            tail = right
        first = normalized.find(query, last)
    if tail < end or end < len(text):
        parts.append({"text": text[tail:end] + ("…" if end < len(text) else "")})
    return parts


def timestamp(value):
    if value:
        try:
            at = datetime.fromisoformat(value)
            return round(at.replace(tzinfo=at.tzinfo or timezone.utc).timestamp() * 1_000_000)
        except (ValueError, OverflowError):
            pass
    return 0


def parse_cursor(cursor):
    try:
        if len(cursor) > 256:
            raise ValueError
        at, thread, position = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if (type(at) is not int or not -(2**63) <= at < 2**63 or not isinstance(thread, str)
                or type(position) is not int or not 0 <= position < 2**63):
            raise ValueError
        return at, thread, position
    except (ValueError, TypeError, binascii.Error, RecursionError):
        raise HearthError("Choose a valid chat search cursor.") from None


class ChatSearch:
    def __init__(self, threads):
        self.threads = threads
        self.stamps = {}
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE messages (
                thread TEXT, position INTEGER, id TEXT, role TEXT, at TEXT, sort_at INTEGER, text TEXT, folded TEXT,
                PRIMARY KEY (thread, position)
            ) WITHOUT ROWID;
            CREATE INDEX newest ON messages (sort_at DESC, thread DESC, position DESC);
            CREATE INDEX thread_newest ON messages (thread, sort_at DESC, position DESC);
        """)

    def sync(self, index, thread, history_revision):
        identities = [thread] if thread is not None else index
        removed = self.stamps.keys() - index.keys()
        updated = {}
        with self.db:
            for identity in removed:
                self.db.execute("DELETE FROM messages WHERE thread = ?", (identity,))
            for identity in identities:
                path = self.threads.path(identity)
                stamp = history_revision, revision(path if identity != MAIN or path.is_file() else self.threads.storage.state)
                if self.stamps.get(identity) == stamp:
                    continue
                self.db.execute("DELETE FROM messages WHERE thread = ?", (identity,))
                self.db.executemany("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?)", self.rows(identity))
                updated[identity] = stamp
        for identity in removed:
            del self.stamps[identity]
        self.stamps.update(updated)

    def rows(self, thread):
        for position, row in self.threads.search_records(thread):
            role = row["role"]
            if role not in {"user", "assistant"} or not (content := visible_text(row)):
                continue
            at = row.get("at")
            yield thread, position, record_id(thread, position, row), role, at, timestamp(at), content, fold(content)

    def search(self, query, thread, limit, before, history_revision):
        query = query.strip()
        if not 2 <= len(query) <= 200:
            raise HearthError("Enter 2–200 characters to search chats.")
        folded = fold(" ".join(query.split()))
        if not folded:
            raise HearthError("Enter 2–200 characters to search chats.")
        if not limit.isascii() or not limit.isdigit() or len(limit) > 9 or int(limit) < 1:
            raise HearthError("Choose a positive chat search limit.")
        size = min(int(limit), PAGE_SIZE)
        cursor = parse_cursor(before) if before is not None else None
        # Treat SQL wildcard characters as literal message text.
        pattern = "%" + folded.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where = r"WHERE folded LIKE ? ESCAPE '\'"
        values = [pattern]
        if thread is not None:
            where += " AND thread = ?"
            values.append(thread)
        with self.threads.storage.lock():
            index = self.threads.load_index()
            if thread is not None:
                self.threads.require(thread, index)
            self.sync(index, thread, history_revision())
            total = self.db.execute(f"SELECT count(*) FROM messages {where}", values).fetchone()[0] if thread else None
            if cursor is not None:
                where += " AND (sort_at, thread, position) < (?, ?, ?)"
                values.extend(cursor)
            rows = self.db.execute(f"SELECT * FROM messages {where} ORDER BY sort_at DESC, thread DESC, position DESC LIMIT ?",
                                   (*values, size + 1)).fetchall()
            titles = {}
            for row in rows[:size]:
                identity = row["thread"]
                if identity not in titles:
                    title = index[identity].get("title")
                    if not title:
                        first = self.db.execute("SELECT text FROM messages WHERE thread = ? ORDER BY position LIMIT 1",
                                                (identity,)).fetchone()
                        title = compact(first["text"], 54) if first else SIDE_TITLE
                    titles[identity] = visible_text({"content": title, "role": "user"}) or SIDE_TITLE
        results = [{"id": row["id"], "thread_id": row["thread"], "thread_title": titles[row["thread"]],
                    "role": row["role"], "at": row["at"], "snippet": snippet(row["text"], folded)}
                   for row in rows[:size]]
        following = None
        if len(rows) > size:
            last = rows[size - 1]
            key = last["sort_at"], last["thread"], last["position"]
            following = base64.urlsafe_b64encode(json.dumps(key).encode()).decode()
        return {"results": results, "before": following, **({"total": total} if thread else {})}
