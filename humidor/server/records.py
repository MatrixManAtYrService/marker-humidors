"""What the server writes down: per-request logs and the deployment ledger.

- Request logs: one JSON file per request in <log_dir>, named
  00001-<what-happened>.json, with timing, every event and any error.
- Ledger: append-only deployments.jsonl recording every deploy and delete the
  server performed, so `verify` can tell its deploys apart from anyone else's.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any


def now() -> str:
    return datetime.now(UTC).isoformat()


def slugify(message: str) -> str:
    slug = re.sub(r"[^a-z0-9-]", "", re.sub(r"[\s_/]+", "-", message.lower()))
    return re.sub(r"-+", "-", slug).strip("-")[:200]


class RequestLog:
    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._sequence = max(
            (int(p.name.split("-", 1)[0]) for p in log_dir.glob("*.json") if p.name.split("-", 1)[0].isdigit()),
            default=0,
        )

    def context(self, message: str) -> RequestContext:
        with self._lock:
            self._sequence += 1
            seq = self._sequence
        return RequestContext(self.log_dir / f"{seq:05d}-{slugify(message)}.json", message, seq)


class RequestContext:
    def __init__(self, path: Path, message: str, sequence: int) -> None:
        self.path = path
        self.message = message
        self.sequence = sequence
        self.events: list[dict[str, Any]] = []
        self.start = datetime.now(UTC)
        self.outcome = "success"
        self.error: dict[str, Any] | None = None

    def log(self, event: str, **fields: Any) -> None:
        self.events.append({"event": event, "timestamp": now(), **fields})

    def __enter__(self) -> RequestContext:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        end = datetime.now(UTC)
        if exc is not None:
            self.outcome = "error"
            self.error = {"type": exc_type.__name__ if exc_type else None, "message": str(exc)}
        self.path.write_text(
            json.dumps(
                {
                    "sequence_number": self.sequence,
                    "message": self.message,
                    "start_time": self.start.isoformat(),
                    "end_time": end.isoformat(),
                    "duration_ms": int((end - self.start).total_seconds() * 1000),
                    "outcome": self.outcome,
                    "error": self.error,
                    "events": self.events,
                },
                indent=2,
                ensure_ascii=False,
            )
        )


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, entry: dict[str, Any]) -> None:
        with self._lock, self.path.open("a") as f:
            f.write(json.dumps({"time": now(), **entry}) + "\n")

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def last_for_service(self, service: str) -> dict[str, Any] | None:
        return next((e for e in reversed(self.entries()) if e.get("service") == service), None)

    def last_deploy(self) -> dict[str, Any] | None:
        """The last deploy of any humidor (for source diffs)."""
        return next((e for e in reversed(self.entries()) if e["action"] == "deploy"), None)
