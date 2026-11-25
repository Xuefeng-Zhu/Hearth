import fcntl
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
MEMORY_PATH = re.compile(r"(?:USER|(?:people|topics)/[\w-]+|daily/\d{4}-\d{2}-\d{2})\.md")
MAX_NOTE = 24_000


class HearthError(Exception):
    """An error that can be shown to the user."""


def iso(now=None):
    return (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")


def new_id():
    return uuid4().hex


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        name = Path(tmp.name)
        try:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
            name.replace(path)
        finally:
            name.unlink(missing_ok=True)


class Storage:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get("HEARTH_DATA_DIR", ROOT / ".hearth")).resolve()
        self.live = self.root / "live"
        self.memory = self.live / "memory"
        self.state = self.live / "state.json"
        self.root.mkdir(parents=True, exist_ok=True)
        with self.lock():
            if not self.memory.is_dir():
                staging = Path(tempfile.mkdtemp(dir=self.root))
                try:
                    shutil.copytree(ROOT / "memory", staging / "memory")
                    self.live.mkdir(exist_ok=True)
                    (staging / "memory").rename(self.memory)
                finally:
                    shutil.rmtree(staging)

    @contextmanager
    def lock(self):
        with (self.root / "state.lock").open("a") as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            yield

    def load(self):
        if self.state.is_file():
            return json.loads(self.state.read_text(encoding="utf-8"))
        return {"actions": {}, "jobs": [], "reminders": [], "outbox": [], "indexed": []}

    def save(self, state):
        atomic_write(self.state, json.dumps(state, ensure_ascii=False))

    def memory_path(self, name):
        if not isinstance(name, str) or not MEMORY_PATH.fullmatch(name):
            raise HearthError("Use USER.md or a Markdown file under people, topics, or daily.")
        path = self.memory / name
        if path.resolve() != path:
            raise HearthError("Memory files must stay inside the memory directory.")
        return path

    def files(self):
        return sorted(
            str(path.relative_to(self.memory))
            for path in self.memory.glob("**/*.md")
            if MEMORY_PATH.fullmatch(str(path.relative_to(self.memory)))
            and path.is_file() and path.resolve() == path
        )

    def read(self, name):
        path = self.memory_path(name)
        if not path.is_file():
            raise HearthError("That memory file does not exist.")
        return path.read_text(encoding="utf-8")

    def write(self, name, content):
        if not isinstance(content, str) or len(content) > MAX_NOTE:
            raise HearthError("Supply Markdown content of at most 24,000 characters.")
        atomic_write(self.memory_path(name), content)

    def search(self, query, limit=5):
        words = set(re.findall(r"\w+", query.lower()))
        hits = []
        for name in self.files():
            content = self.read(name)
            bag = re.findall(r"\w+", f"{name} {content}".lower())
            score = sum(bag.count(word) for word in words)
            if score:
                excerpts = [line for line in content.splitlines()
                            if words.intersection(re.findall(r"\w+", line.lower()))]
                hits.append((score, name, " ".join(excerpts)[:550] or content[:550]))
        return [{"path": name, "excerpt": excerpt}
                for _, name, excerpt in sorted(hits, key=lambda hit: (-hit[0], hit[1]))[:limit]]
