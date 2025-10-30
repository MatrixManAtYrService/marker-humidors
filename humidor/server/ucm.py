"""Runs UCM transcripts against a sandboxed fork of the base codebase.

Every operation forks the base codebase (built from unison/base.md, which pins
the libraries), loads unison/src/*.u from disk, and runs a small generated
program. Programs report results by printing tab-separated lines starting with
"HUMIDOR", which this module parses. Nothing persists between operations, so
what runs is always what is in the repo.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from humidor.config import Config, service_name

FENCE = "```"
PROJECT = "humidor/main"
RECORD_RE = re.compile(r"HUMIDOR\t([^\r\n]*)")
AUTH_HINTS = ("auth.login", "credentials", "not logged in", "unauthorized", "401")


class UcmError(Exception):
    def __init__(self, message: str, output: str = "", needs_auth: bool = False) -> None:
        super().__init__(message)
        self.output = output
        self.needs_auth = needs_auth


@dataclass
class TranscriptResult:
    output: str
    records: list[list[str]] = field(default_factory=list)

    def of_kind(self, kind: str) -> list[list[str]]:
        return [r[1:] for r in self.records if r and r[0] == kind]

    def added_definitions(self) -> list[str]:
        """The '+ name : type' lines UCM prints after typechecking, joined per definition."""
        defs: list[str] = []
        for line in self.output.splitlines():
            stripped = line.strip()
            if stripped.startswith("+ "):
                defs.append(stripped[2:])
            elif defs and line.startswith(" " * 6) and stripped and not stripped.startswith(("Run ", "Done")):
                defs[-1] += " " + stripped
        return [re.sub(r"\s+", " ", d) for d in defs if not d.startswith("humidor.op.")]


def _ucm_block(*commands: str) -> str:
    return "\n".join([f"{FENCE}ucm", *(f"{PROJECT}> {c}" for c in commands), FENCE, ""])


def _unison_block(code: str) -> str:
    return "\n".join([f"{FENCE}unison", code.strip(), FENCE, ""])


def _load_sources(config: Config) -> str:
    # All files go in one scratch block so they can refer to each other.
    combined = "\n\n".join(f"-- {src.name}\n{src.read_text()}" for src in config.sources)
    return _unison_block(combined) + _ucm_block("update")


def _text(value: str) -> str:
    """A Unison text literal. Only checked plain values (names, paths, URLs) are passed."""
    if any(c in value for c in '"\\\n\r'):
        raise ValueError(f"refusing to embed {value!r} in Unison source")
    return f'"{value}"'


def deploy_program(humidor: str, label: str, repo_url: str, token_path: Path) -> str:
    """Deploy one humidor, assign its name, and print its hash and URL.

    The admin token is read from token_path inside ucm, so the secret never
    appears in the transcript or its output.
    """
    return f"""
humidor.op.deploy : '{{IO, Exception}} ()
humidor.op.deploy = Cloud.main do
  use Text ++
  token = FilePath.readFileUtf8 (FilePath.FilePath {_text(str(token_path))})
  h = markerHumidor.deploy {_text(humidor)} {_text(label)} {_text(repo_url)} token
  uri = ServiceName.assign (ServiceName.named {_text(service_name(humidor))}) h
  (ServiceHash.ServiceHash raw) = h
  printLine ("HUMIDOR\\tdeployed\\t" ++ raw ++ "\\t" ++ URI.toText uri)
"""


LIST_PROGRAM = """
humidor.op.list : '{IO, Exception} ()
humidor.op.list = do
  use Text ++
  ServiceName.list() |> List.foreach cases ServiceNameInfo (ServiceName.Untyped.Untyped id n) dep _ ->
    match dep with
      Some d ->
        (ServiceHash.Untyped.Untyped h) = DeploymentInfo.hash d
        printLine ("HUMIDOR\\tservice\\t" ++ n ++ "\\t" ++ ServiceName.Id.toText id ++ "\\t" ++ h ++ "\\t" ++ toDebugText (DeploymentInfo.deployedAt d))
      None ->
        printLine ("HUMIDOR\\tservice\\t" ++ n ++ "\\t" ++ ServiceName.Id.toText id ++ "\\t\\t")
"""


def destroy_program(humidor: str) -> str:
    """Unassign and undeploy a humidor's service, delete its name, then run
    markerHumidor.teardown to delete its database and environment."""
    return f"""
humidor.op.destroy : '{{IO, Exception}} ()
humidor.op.destroy = Cloud.main do
  use Text ++ ==
  target = {_text(service_name(humidor))}
  isTarget = cases ServiceNameInfo (ServiceName.Untyped.Untyped _ n) _ _ -> n == target
  match List.find isTarget (ServiceName.list()) with
    None -> printLine ("HUMIDOR\\tmissing\\t" ++ target)
    Some (ServiceNameInfo _ dep _) ->
      ServiceName.unassign (ServiceName.named target)
      printLine ("HUMIDOR\\tunassigned\\t" ++ target)
      match dep with
        Some d ->
          (ServiceHash.Untyped.Untyped h) = DeploymentInfo.hash d
          Cloud.undeploy (ServiceHash.ServiceHash h)
          printLine ("HUMIDOR\\tundeployed\\t" ++ h)
        None -> ()
      ServiceName.delete (ServiceName.named target)
      printLine ("HUMIDOR\\tdeleted-name\\t" ++ target)
  markerHumidor.teardown {_text(humidor)}
  printLine ("HUMIDOR\\tteardown\\t" ++ target)
"""


def typecheck_transcript(config: Config) -> str:
    # Typecheck the deploy wrapper too, with placeholders; it is not run.
    program = deploy_program("typecheck", "Typecheck", config.repo_url, Path("/nonexistent/token"))
    return _load_sources(config) + _unison_block(program) + _ucm_block("update")


def deploy_transcript(config: Config, humidor: str, label: str, token_path: Path) -> str:
    program = deploy_program(humidor, label, config.repo_url, token_path)
    return _load_sources(config) + _unison_block(program) + _ucm_block("update", "run humidor.op.deploy")


def list_transcript() -> str:
    return _unison_block(LIST_PROGRAM) + _ucm_block("update", "run humidor.op.list")


def destroy_transcript(config: Config, humidor: str) -> str:
    return (
        _load_sources(config) + _unison_block(destroy_program(humidor)) + _ucm_block("update", "run humidor.op.destroy")
    )


def parse_records(output: str) -> list[list[str]]:
    """Find "HUMIDOR\t..." records anywhere in the output.

    Program output reaches us via ucm's stdout, where it can share a line with
    ucm's progress text ("Processing stanza 2 of 2.HUMIDOR\t..."), so match
    anywhere rather than at line start. Duplicates are dropped.
    """
    seen: dict[str, None] = {}
    for m in RECORD_RE.finditer(output):
        seen.setdefault(m.group(1), None)
    return [rec.split("\t") for rec in seen]


def _failure_message(output: str) -> str:
    if "🛑" in output:
        return output.split("🛑", 1)[1].strip()[:4000]
    return output.strip()[-4000:]


class UcmRunner:
    """Runs transcripts one at a time (ucm processes are memory-hungry)."""

    def __init__(self, base_codebase: Path, base_transcript: Path, ucm: str = "ucm", timeout: float = 900) -> None:
        self.base_codebase = base_codebase
        self.base_transcript = base_transcript
        self.ucm = ucm
        self.timeout = timeout
        self._lock = threading.Lock()

    def _exec(self, args: list[str], transcript: Path) -> str:
        if shutil.which(self.ucm) is None:
            raise UcmError(f"'{self.ucm}' not found on PATH. Run the server from `nix develop`, or install ucm.")
        proc = subprocess.run(
            [self.ucm, *args, str(transcript)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        out_md = transcript.with_suffix(".output.md")
        output = out_md.read_text() if out_md.exists() else ""
        output += "\n" + proc.stdout + proc.stderr
        if proc.returncode != 0 or "🛑" in output:
            message = _failure_message(output)
            needs_auth = any(h in message.lower() for h in AUTH_HINTS)
            raise UcmError(message, output=output, needs_auth=needs_auth)
        return output

    def ensure_base(self, rebuild: bool = False) -> None:
        with self._lock:
            if rebuild and self.base_codebase.exists():
                shutil.rmtree(self.base_codebase)
            if self.base_codebase.exists():
                return
            self.base_codebase.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="humidor-") as tmp:
                transcript = Path(tmp) / "base.md"
                shutil.copy(self.base_transcript, transcript)
                self._exec(["transcript.in-place", "-C", str(self.base_codebase)], transcript)

    def run(self, transcript_text: str) -> TranscriptResult:
        self.ensure_base()
        with self._lock, tempfile.TemporaryDirectory(prefix="humidor-") as tmp:
            transcript = Path(tmp) / "op.md"
            transcript.write_text(transcript_text)
            output = self._exec(["transcript.fork", "-c", str(self.base_codebase)], transcript)
            return TranscriptResult(output=output, records=parse_records(output))
