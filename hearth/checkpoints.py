import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .storage import HearthError, iso, new_id

SPRITE_ID = re.compile(r"v\d+(?:[.\-]\d+)*")


class LocalCheckpoints:
    mode = "local"

    def __init__(self, storage):
        self.storage = storage
        self.root = storage.root / "checkpoints"
        self.root.mkdir(exist_ok=True)

    def create(self, comment):
        checkpoint = {"id": new_id(), "comment": comment, "created_at": iso()}
        with tempfile.TemporaryDirectory(dir=self.root) as staging:
            path = Path(staging) / "snapshot"
            path.mkdir()
            shutil.copytree(self.storage.live, path / "live")
            (path / "checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
            path.rename(self.root / checkpoint["id"])
        return checkpoint

    def list(self):
        items = [json.loads(path.read_text(encoding="utf-8")) for path in self.root.glob("*/checkpoint.json")]
        return sorted(items, key=lambda item: item["created_at"], reverse=True)

    def restore(self, checkpoint_id):
        if not re.fullmatch(r"[0-9a-f]{32}", checkpoint_id):
            raise HearthError("Invalid checkpoint ID.")
        source = self.root / checkpoint_id / "live"
        if not source.is_dir():
            raise HearthError("Checkpoint is unavailable.")
        with tempfile.TemporaryDirectory(dir=self.storage.root) as staging:
            backup = Path(staging) / "previous"
            restored = Path(staging) / "restored"
            shutil.copytree(source, restored)
            self.storage.live.rename(backup)
            try:
                restored.rename(self.storage.live)
            except OSError:
                backup.rename(self.storage.live)
                raise


class SpriteCheckpoints:
    mode = "sprite"

    @staticmethod
    def command(*args):
        try:
            result = subprocess.run(
                ("sprite-env", "checkpoints", *args), stdin=subprocess.DEVNULL,
                capture_output=True, text=True, check=True, timeout=75,
            )
        except (OSError, subprocess.SubprocessError):
            raise HearthError(f"Sprite could not {args[0]} the checkpoint.") from None
        return result.stdout

    def create(self, comment):
        output = self.command("create", "--comment", comment)
        match = re.search(r"\b(?:ID:\s+|Checkpoint\s+)(v\d+(?:[.\-]\d+)*)\b", output)
        if not match:
            raise HearthError("Sprite did not return a checkpoint ID.")
        return {"id": match[1], "comment": comment, "created_at": iso()}

    def list(self):
        try:
            entries = json.loads(self.command("list")) or []
            return [{"id": item["id"], "comment": item.get("comment") or
                     ("Automatic Sprite checkpoint" if item.get("is_auto") else "Sprite checkpoint"),
                     "created_at": item.get("create_time") or ""}
                    for item in entries if SPRITE_ID.fullmatch(item["id"])]
        except (KeyError, TypeError, ValueError):
            raise HearthError("Sprite returned an unreadable checkpoint list.") from None

    def restore(self, checkpoint_id):
        if not SPRITE_ID.fullmatch(checkpoint_id):
            raise HearthError("Invalid Sprite checkpoint ID.")
        self.command("restore", checkpoint_id)
