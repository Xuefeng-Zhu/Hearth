"""Bounded local references for a read-only proactive pass."""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from . import artifacts, mail_content, memory, page_html, recall
from .gateway_tools import redact_text
from .reminder_config import EMAIL
from .storage import HearthError
from .threads import MAIN


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def private_text(text):
    text = EMAIL.sub("[email]", redact_text(text))
    text = re.sub(r"https?://[^\s<>\])]+", "[link]", text, flags=re.I)
    text = re.sub(r"(?<!\w)\+?\d(?:[ ()-]*\d){9,}(?!\w)", "[number]", text)
    text = re.sub(r"(?i)\b\d{1,6} +(?:[\w.'-]+ +){1,5}(?:street|st|avenue|ave|road|rd|lane|ln|drive|dr|"
                  r"boulevard|blvd|court|ct|way|terrace|place)\b", "[address]", text)
    return re.sub(r"(?im)\b(?:confirmation|booking|reservation|tracking)\s*(?:code|number|#)\s*[:#]?\s*[\w-]+",
                  "[reference number]", text)


def private_match(value, rules):
    return "[forgotten]" in value or memory.matches_rule(value, rules)


def forget_rules(storage, state):
    return memory.standing_rules(storage) + [
        rule for identity, rules in state.get("proactivity_forget", {}).items()
        if not state["actions"].get(identity, {}).get("undone") for rule in rules
    ]


def record_forget(state, identity, removed):
    # Keep only salted phrase hashes for copied excerpts in other sources.
    phrases = []
    for item in removed:
        for line in item["excerpt"].splitlines():
            tokens = memory.words(line)
            phrase = " ".join(tokens[:8])
            if len(tokens) >= 3 and len(phrase) <= 120:
                phrases.append([phrase])
    if phrases:
        state.setdefault("proactivity_forget", {})[identity] = [
            memory.forget_rule(phrases[start:start + 12]) for start in range(0, len(phrases), 12)
        ]
    proactive = state.setdefault("proactivity", {})
    proactive["privacy_revision"] = identity
    for row in proactive.get("cards", {}).values():
        retire(row)


def retire(row):
    for key in ("title", "why", "urgency", "action", "sources", "wake_at"):
        row.pop(key, None)
    if row["status"] not in {"acted", "dismissed", "blocked"}:
        row["status"] = "expired"


class Context:
    def __init__(self, app, state):
        self.app = app
        self.storage = app.storage
        self.state = state
        self.rules = forget_rules(self.storage, state)
        self.skills = {row["id"]: row["name"] for row in app.agent.skills.listed(state)
                       if not private_match(row["name"], self.rules) and private_text(row["name"]) == row["name"]}
        self.selection = app.agent.memory
        self.chats = {}
        self.records = {}
        self.paths = [path for path in self.storage.files() if path not in {memory.APPROVAL_NOTE, memory.PROACTIVITY_NOTE}
                      and recall.folder_allowed(path, self.selection)]

    def revision(self):
        files = [(path, self.storage.memory_path(path).stat().st_mtime_ns) for path in self.paths]
        inbox = list(self.state.get("inbox", {}))
        return digest([files, inbox, self.rules, self.state.get("proactivity", {}).get("privacy_revision")])

    def messages(self, thread):
        if thread not in self.chats:
            if thread not in self.app.threads.load_index():
                return {}
            forgotten = set(self.state.get("forgotten_chat", []))
            self.chats[thread] = {
                row["id"]: row for row in self.app.threads.messages(thread, limit=12, dialogue_only=True)
                if row.get("id") and row["id"] not in forgotten
                and row.get("source") not in {"proactivity", "recurring-task"}
            }
        return self.chats[thread]

    def raw(self, source):
        kind, _, key = source.partition(":")
        state = self.state
        if kind == "memory":
            if key not in self.paths:
                return None
            text = self.storage.read(key)
            if key == memory.PROFILE_NOTE:
                data, notes, _ = memory.parse(key, text)
                profile = {k: v for k, v in data["profile"].items() if k not in {"phone", "addresses"}}
                text = json.dumps(profile, ensure_ascii=False) + "\n" + notes
            return f"{key}\n{text}", 1_600
        if kind == "chat":
            thread, _, message = key.partition("/")
            row = self.messages(thread).get(message)
            if row:
                return f"{row.get('at', '')} {row['role']}: {row['content']}", 900
        if kind == "reminder":
            row = next((row for row in state["jobs"] if row["id"] == key and row["status"] == "scheduled"), None)
            if row:
                return f"{row['next_at']} {row['message']}\n{row.get('note', '')}", 700
        if kind == "task":
            row = state.get("recurring_tasks", {}).get(key)
            if row and not row.get("deleted"):
                return f"{row['name']} ({'enabled' if row['enabled'] else 'paused'}, next: {row.get('next_run')})\n{row['instruction']}", 500
        if kind == "inbox":
            row = state.get("inbox", {}).get(key)
            if row and row.get("status") in {"review", "accepted"} and not row.get("suspicious"):
                proposal = row.get("proposal", {})
                text = "\n".join(str(row.get(field) or "") for field in ("received_at", "title", "body"))
                fields = {field: proposal.get(field) for field in ("kind", "at", "events", "summary")}
                return text + "\n" + json.dumps(fields, ensure_ascii=False), 1_600
        if kind == "page":
            row = state.get("pages", {}).get(key)
            if row and row.get("version") is not None:
                try:
                    doc = page_html.document_from(self.app.pages.read(row, row["version"]).decode("utf-8"))
                    body = doc.find("body")
                    text = " ".join(body.xpath(".//text()[not(ancestor::style or ancestor::script)]")) if body is not None else ""
                except (HearthError, OSError, UnicodeError):
                    text = ""
                return f"{row['title']} (v{row['version']}, {row['updated_at']})\n{text}", 1_600
        if kind == "artifact":
            row = state.get("artifacts", {}).get(key)
            if row and not row.get("deleted"):
                text = row.get("content") or row.get("summary") or ""
                if not text and row.get("structured"):
                    text = json.dumps(row["structured"], ensure_ascii=False)[:6_000]
                return f"{row['title']} ({row['format']}, {row.get('updated_at')})\n{text}", 1_200
        return None

    def get(self, source):
        if source not in self.records:
            self.records[source] = self.read(source)
        return self.records[source]

    def read(self, source):
        raw = self.raw(source)
        if raw is None:
            return None
        value, limit = raw
        if private_match(value, self.rules) or mail_content.INJECTION.search(value):
            return None
        return {"id": source, "text": private_text(value)[:limit], "revision": digest(value)}

    def collect(self, now):
        paths = self.paths
        memory_paths = []
        for folder in recall.FOLDERS:
            entries = [path for path in paths if recall.note_scope(path) == folder]
            entries.sort(key=lambda path: (path == memory.PROFILE_NOTE, self.storage.memory_path(path).stat().st_mtime_ns),
                         reverse=True)
            memory_paths.extend(entries[:12])
        state = self.state
        inbox = sorted(state.get("inbox", {}).values(), key=lambda row: row["received_at"], reverse=True)
        jobs = sorted(state["jobs"], key=lambda row: row["next_at"])
        tasks = list(state.get("recurring_tasks", {}))
        pages = sorted(artifacts.page_artifacts(state), key=lambda row: row["updated_at"], reverse=True)
        files = sorted(state.get("artifacts", {}).values(), key=lambda row: row.get("updated_at") or row["created_at"],
                       reverse=True)
        sources = ([f"memory:{path}" for path in memory_paths]
                   + [f"reminder:{row['id']}" for row in jobs if row["status"] == "scheduled"][:18]
                   + [f"task:{identity}" for identity in tasks if identity != "morning-brief"][:10]
                   + [f"inbox:{row['id']}" for row in inbox if row["status"] in {"review", "accepted"}][:12]
                   + [f"page:{row['id']}" for row in pages[:8]]
                   + [f"artifact:{row['id']}" for row in files if not row.get("deleted")][:8])
        threads = self.app.threads.load_index()
        recent_threads = sorted(threads, key=lambda thread: (
            self.app.threads.path(thread).stat().st_mtime if self.app.threads.path(thread).is_file() else 0),
            reverse=True)
        cutoff = (now - timedelta(days=14)).astimezone(timezone.utc).isoformat()
        for thread in dict.fromkeys([MAIN, *recent_threads[:5]]):
            sources.extend(f"chat:{thread}/{row['id']}" for row in list(self.messages(thread).values())[-5:]
                           if (row.get("at") or "") >= cutoff)
        return [record for source in sources if (record := self.get(source))]
