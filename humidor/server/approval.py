"""Human approval for impactful operations, asked in the server's terminal.

The prompt is written to and read from /dev/tty, never from the HTTP request,
so nothing that can reach the server over HTTP (the agent included) can approve.
If the server has no terminal (e.g. it was started in the background), every
request is denied.
"""

from __future__ import annotations

import os
import select
import threading
from collections.abc import Callable
from dataclasses import dataclass

Approver = Callable[["ApprovalRequest"], "ApprovalDecision"]


@dataclass
class ApprovalRequest:
    action: str
    summary: list[tuple[str, str]]
    details: str = ""


@dataclass
class ApprovalDecision:
    approved: bool
    reason: str


class TtyApprover:
    def __init__(self, timeout: float = 300, tty_path: str = "/dev/tty") -> None:
        self.timeout = timeout
        self.tty_path = tty_path
        self._lock = threading.Lock()  # one prompt at a time

    def __call__(self, request: ApprovalRequest) -> ApprovalDecision:
        with self._lock:
            try:
                fd = os.open(self.tty_path, os.O_RDWR | os.O_NOCTTY)
            except OSError as e:
                return ApprovalDecision(
                    False, f"no terminal to ask for approval ({e}); run `humidor serve` in a terminal"
                )
            try:
                with os.fdopen(fd, "r+", buffering=1) as tty:
                    tty.write(render(request))
                    tty.write(f"Approve {request.action}? Type 'yes' within {int(self.timeout)}s: ")
                    tty.flush()
                    ready, _, _ = select.select([tty], [], [], self.timeout)
                    if not ready:
                        tty.write("\n(timed out, denied)\n")
                        return ApprovalDecision(False, "timed out waiting for approval")
                    answer = tty.readline().strip().lower()
                    approved = answer == "yes"
                    tty.write("approved\n\n" if approved else "denied\n\n")
                    return ApprovalDecision(
                        approved, "approved in server terminal" if approved else "denied in server terminal"
                    )
            except OSError as e:
                return ApprovalDecision(False, f"approval prompt failed: {e}")


def render(request: ApprovalRequest) -> str:
    width = max(len(k) for k, _ in request.summary) if request.summary else 0
    lines = ["", "=" * 72, f"humidor: approval requested for {request.action.upper()}", "-" * 72]
    lines += [f"  {k.ljust(width)}  {v}" for k, v in request.summary]
    if request.details:
        lines += ["-" * 72, request.details.rstrip()]
    lines += ["=" * 72, ""]
    return "\n".join(lines)
