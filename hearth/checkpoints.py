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
        match = re.search(r"\bv\d+(?:[.\-]\d+)*\b", output)
        if not match:
            raise HearthError("Sprite did not return a checkpoint ID.")
        return {"id": match[0], "comment": comment, "created_at": iso()}

    def list(self):
        items = []
        for line in self.command("list").splitlines():
            match = re.match(r"\s*(?:[-*]\s*)?(v\d+(?:[.\-]\d+)*)(?![\w.])\s*[:\s]*(.*)", line)
            if match:
                checkpoint_id, detail = match.groups()
                items.append({"id": checkpoint_id, "comment": detail, "created_at": ""})
        return items

    def restore(self, checkpoint_id):
        if not SPRITE_ID.fullmatch(checkpoint_id):
            raise HearthError("Invalid Sprite checkpoint ID.")
        self.command("restore", checkpoint_id)
