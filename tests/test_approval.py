from __future__ import annotations

import os
import threading

from humidor.server.approval import ApprovalRequest, TtyApprover


def _answer_on_pty(answer: bytes | None, timeout: float = 5) -> tuple[bool, str]:
    master, slave = os.openpty()
    approver = TtyApprover(timeout=timeout, tty_path=os.ttyname(slave))
    result = {}

    def ask() -> None:
        result["decision"] = approver(ApprovalRequest("deploy", [("app", "hello-world")], "details"))

    t = threading.Thread(target=ask)
    t.start()
    shown = b""
    while b"Type 'yes'" not in shown:
        shown += os.read(master, 4096)
    if answer is not None:
        os.write(master, answer)
    t.join()
    os.close(master)
    os.close(slave)
    assert b"hello-world" in shown
    return result["decision"].approved, result["decision"].reason


def test_yes_approves():
    assert _answer_on_pty(b"yes\n")[0]


def test_anything_else_denies():
    assert not _answer_on_pty(b"y\n")[0]


def test_silence_times_out_as_denial():
    approved, reason = _answer_on_pty(None, timeout=0.5)
    assert not approved and "timed out" in reason


def test_no_terminal_denies(tmp_path):
    decision = TtyApprover(tty_path=str(tmp_path / "no-such-tty"))(ApprovalRequest("deploy", []))
    assert not decision.approved and "humidor serve" in decision.reason
