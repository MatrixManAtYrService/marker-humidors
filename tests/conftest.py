from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from humidor.server.approval import ApprovalDecision, ApprovalRequest
from humidor.server.main import Settings, create_app
from humidor.server.ucm import TranscriptResult, UcmError, parse_records

REPO_ROOT = Path(__file__).resolve().parent.parent
CLOUD = "https://acct.unison-services.cloud"
# Real cloud hashes are 52-char base32 text.
HASH_A = "ozrpvknrtnqg2y4ehmezooyzn6zcntuffyoctkylof7mthnmwv5a"
HASH_B = "b" * 52


class FakeRunner:
    """Stands in for UcmRunner: answers transcripts by what program they run."""

    def __init__(self) -> None:
        self.live: dict[str, str | None] = {}  # service -> hash
        self.next_hash = HASH_B
        self.fail: UcmError | None = None
        self.ran: list[str] = []
        self.transcripts: list[str] = []

    def run(self, transcript: str) -> TranscriptResult:
        self.transcripts.append(transcript)
        if self.fail:
            raise self.fail
        if "run humidor.op.list" in transcript:
            op = "list"
            out = "\n".join(
                f"HUMIDOR\tservice\t{name}\tid-{name}\t{h or ''}\t{'Instant +1762796643 642980000' if h else ''}"
                for name, h in self.live.items()
            )
        elif "run humidor.op.deploy" in transcript:
            op = "deploy"
            service = re.search(r'ServiceName.named "([^"]+)"', transcript).group(1)  # type: ignore[union-attr]
            self.live[service] = self.next_hash
            out = f"HUMIDOR\tdeployed\t{self.next_hash}\t{CLOUD}/s/{service}"
        elif "run humidor.op.destroy" in transcript:
            op = "destroy"
            service = re.search(r'target = "([^"]+)"', transcript).group(1)  # type: ignore[union-attr]
            h = self.live.pop(service, None) or HASH_A
            steps = (f"unassigned\t{service}", f"undeployed\t{h}", f"deleted-name\t{service}", f"teardown\t{service}")
            out = "\n".join(f"HUMIDOR\t{step}" for step in steps)
        else:
            op = "typecheck"
            out = "  + markerHumidor.deploy : Text\n        -> Text ->{Exception, Cloud} ServiceHash\n"
        self.ran.append(op)
        # Like real ucm: program output arrives on stdout glued to progress text.
        if op != "typecheck":
            out = "  ⚙️   Processing stanza 2 of 2." + out + "\n\n  ✔️   Completed transcript.\n"
        return TranscriptResult(output=out, records=parse_records(out))


class FakeApprover:
    def __init__(self, approve: bool = True) -> None:
        self.approve = approve
        self.requests: list[ApprovalRequest] = []

    def __call__(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        return ApprovalDecision(self.approve, "test approver")


class FakeSite:
    """The live web, as seen through httpx: answers from {(method, path): (status, body)}
    or {path: ...}, and records every request."""

    def __init__(self, responses: dict | None = None) -> None:
        self.responses = responses or {}
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method, request.url.path)
        status, body = self.responses.get(key, self.responses.get(request.url.path, (404, "not found")))
        return httpx.Response(status, text=body)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A copy of this repo's unison/ plus a humidor.toml, in its own git repo."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "humidor.toml").write_text('repo_url = "https://github.com/example/marker-humidor"\n')
    shutil.copytree(REPO_ROOT / "unison", root / "unison")
    git = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "init"], check=True)
    return root


Factory = Callable[..., tuple[TestClient, FakeRunner, FakeApprover]]


@pytest.fixture
def make_client(repo: Path, tmp_path: Path) -> Factory:
    """A server over the test repo. Every client made in one test shares the server's home."""

    def make(approve: bool = True, site: FakeSite | None = None):
        runner, approver = FakeRunner(), FakeApprover(approve)
        app = create_app(
            Settings(root=repo, home=tmp_path / "home"),
            runner=runner,  # type: ignore[arg-type]
            approver=approver,
            http=(site or FakeSite()).client(),
        )
        return TestClient(app), runner, approver

    return make
