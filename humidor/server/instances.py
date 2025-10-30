"""Which humidors exist, and their admin tokens.

Lives only on the server, under <HUMIDOR_HOME>/humidors/ (mode 700):
    <name>.json    {"label": "Chucho", "created": ..., "status": "pending" | "deployed",
                    "hash": ..., "url": ...}
    <name>.token   the admin token (mode 600). Deploys read it from disk inside ucm,
                   so it never appears in a transcript, log or HTTP response.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from humidor.server.records import now


class HumidorStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _dir(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        return self.root

    def names(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json")) if self.root.is_dir() else []

    def exists(self, name: str) -> bool:
        return (self.root / f"{name}.json").exists()

    def token_path(self, name: str) -> Path:
        return self._dir() / f"{name}.token"

    def token(self, name: str) -> str:
        return self.token_path(name).read_text()

    def meta(self, name: str) -> dict[str, Any]:
        return json.loads((self.root / f"{name}.json").read_text())

    def create(self, name: str, label: str) -> None:
        fd = os.open(self.token_path(name), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(32))
        self.update(name, label=label, created=now(), status="pending")

    def update(self, name: str, **fields: Any) -> None:
        path = self._dir() / f"{name}.json"
        data = json.loads(path.read_text()) if path.exists() else {}
        path.write_text(json.dumps({**data, **fields}, indent=2, ensure_ascii=False))

    def snapshot(self, name: str) -> dict[str, str] | None:
        """This humidor's files as they are now, so a failed change can put them back."""
        if not self.exists(name):
            return None
        return {suffix: (self.root / f"{name}{suffix}").read_text() for suffix in (".json", ".token")}

    def restore(self, name: str, snapshot: dict[str, str] | None) -> None:
        self.remove(name)
        if snapshot is None:
            return
        for suffix, text in snapshot.items():
            path = self._dir() / f"{name}{suffix}"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(text)

    def remove(self, name: str) -> None:
        for suffix in (".json", ".token"):
            (self.root / f"{name}{suffix}").unlink(missing_ok=True)

    def backup_dir(self) -> Path:
        d = self.root.parent / "backups"
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
        return d
