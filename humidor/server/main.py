"""humidor server: the only place that holds the Unison Cloud login and the humidors' admin tokens.

Read-only operations (check, ls, verify, reading comments) run freely and are
logged. Operations that change what is deployed or what people wrote (create,
delete, deploy, editing or removing comments) are shown to the owner in the
server's terminal and run only if approved there.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from humidor.config import (
    API_PATH_RE,
    BACKUP_PATH,
    CHECKS,
    SERVICE_PREFIX,
    Check,
    Config,
    ConfigError,
    check_label,
    check_slug,
    load_config,
    service_name,
    slug,
)
from humidor.server import ucm
from humidor.server.approval import ApprovalRequest, Approver, TtyApprover
from humidor.server.instances import HumidorStore
from humidor.server.records import Ledger, RequestContext, RequestLog, now
from humidor.server.ucm import UcmError, UcmRunner

MAX_DETAIL_LINES = 200
CREDENTIALS = Path.home() / ".local/share/unisonlanguage/credentials.json"


@dataclass
class Settings:
    root: Path
    home: Path

    @classmethod
    def from_env(cls) -> Settings:
        root = Path(os.environ.get("HUMIDOR_REPO", ".")).resolve()
        home = Path(os.environ.get("HUMIDOR_HOME", Path.home() / ".local/share/humidor")).expanduser()
        return cls(root=root, home=home)


@dataclass
class LiveService:
    name: str
    id: str
    hash: str | None
    deployed_at: str | None


class CreateRequest(BaseModel):
    label: str


class AdminRequest(BaseModel):
    method: str
    path: str
    body: dict[str, Any] | None = None


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, check=True, timeout=30
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def _source_sha256(config: Config) -> str:
    h = hashlib.sha256()
    for src in config.sources:
        h.update(src.name.encode() + b"\0" + src.read_bytes() + b"\0")
    return h.hexdigest()


def _truncate(text: str, max_lines: int = MAX_DETAIL_LINES) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines] + [f"... ({len(lines) - max_lines} more lines)"])


def _pretty(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) if not isinstance(data, str) else data


def _error(status: int, error: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": error, "message": message, **extra})


AUTH_INSTRUCTIONS = (
    "On the server machine, run `ucm`, then `auth.login` (this needs a Unison Cloud account), then retry. "
    "(An agent cannot do this; ask the owner.)"
)


def _ucm_http_error(e: UcmError, ctx: RequestContext) -> HTTPException:
    ctx.log("ucm_failed", message=str(e), needs_auth=e.needs_auth, output=e.output[-8000:])
    ctx.outcome = "error"
    if e.needs_auth:
        return _error(499, "cloud_auth_required", str(e)[:1000], instructions=AUTH_INSTRUCTIONS)
    return _error(502, "ucm_failed", str(e)[:4000])


def _base_url(url: str) -> str:
    """https://acct.unison-services.cloud/s/marker-humidor-x/ -> https://acct.unison-services.cloud"""
    return url.split("/s/", 1)[0]


def create_app(
    settings: Settings,
    runner: UcmRunner | None = None,
    approver: Approver | None = None,
    http: httpx.Client | None = None,
) -> FastAPI:
    runner = runner or UcmRunner(
        base_codebase=settings.home / "base-codebase",
        base_transcript=settings.root / "unison" / "base.md",
        ucm=os.environ.get("HUMIDOR_UCM", "ucm"),
    )
    approver = approver or TtyApprover(timeout=float(os.environ.get("HUMIDOR_APPROVAL_TIMEOUT", 300)))
    http = http or httpx.Client(timeout=30, follow_redirects=False)
    ledger = Ledger(settings.home / "deployments.jsonl")
    store = HumidorStore(settings.home / "humidors")
    request_log = RequestLog(settings.root / "humidor_logs")

    app = FastAPI(title="humidor-server", description="Manages a fleet of marker humidor pages on Unison Cloud")

    @app.exception_handler(HTTPException)
    async def _flat_errors(_request: Any, exc: HTTPException) -> JSONResponse:
        content = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content=content)

    # --- helpers -----------------------------------------------------------

    def config() -> Config:
        # Re-read every request: the repo on disk (as pulled from git) is the source of truth.
        try:
            return load_config(settings.root)
        except ConfigError as e:
            raise _error(500, "bad_config", str(e))

    def existing(name: str) -> str:
        try:
            check_slug(name)
        except ConfigError as e:
            raise _error(400, "bad_name", str(e))
        if not store.exists(name):
            labels = ", ".join(store.meta(n)["label"] for n in store.names()) or "(none)"
            raise _error(404, "unknown_humidor", f"No humidor {name!r}. Existing: {labels}")
        return name

    def live_services(ctx: RequestContext) -> dict[str, LiveService]:
        result = runner.run(ucm.list_transcript())
        services = {}
        for rec in result.of_kind("service"):
            rec += [""] * (4 - len(rec))
            name, sid, h, deployed_at = rec[:4]
            services[name] = LiveService(name, sid, h.strip() or None, instant_to_iso(deployed_at))
        ctx.log(
            "listed_live_services",
            count=len(services),
            services={n: {"hash": v.hash, "deployed_at": v.deployed_at} for n, v in services.items()},
        )
        return services

    def try_live_services(ctx: RequestContext) -> tuple[dict[str, LiveService] | None, str | None]:
        try:
            return live_services(ctx), None
        except UcmError as e:
            ctx.log("list_failed", message=str(e)[:2000], needs_auth=e.needs_auth)
            if e.needs_auth:
                return None, "not logged in to Unison Cloud on the server; the owner must run `auth.login` in ucm"
            return None, str(e)[:500]

    def run_ucm(ctx: RequestContext, transcript: str) -> ucm.TranscriptResult:
        try:
            return runner.run(transcript)
        except UcmError as e:
            raise _ucm_http_error(e, ctx)

    def ask(ctx: RequestContext, request: ApprovalRequest) -> None:
        ctx.log("approval_requested", action=request.action, summary=dict(request.summary))
        decision = approver(request)
        ctx.log("approval_decided", approved=decision.approved, reason=decision.reason)
        if not decision.approved:
            ctx.outcome = "denied"
            raise HTTPException(status_code=403, detail={"error": "denied", "reason": decision.reason})

    def source_summary(cfg: Config, ctx: RequestContext) -> tuple[list[tuple[str, str]], str]:
        """Typecheck the app and describe its source for an approval prompt."""
        checked = run_ucm(ctx, ucm.typecheck_transcript(cfg))
        definitions = checked.added_definitions()
        ctx.log("typechecked", definitions=definitions)
        src = cfg.root / "unison"
        head = _git(cfg.root, "rev-parse", "HEAD")
        dirty = bool(_git(cfg.root, "status", "--porcelain", "--", str(src)))
        last = ledger.last_deploy()
        if last and last.get("git_sha"):
            details = _git(cfg.root, "diff", last["git_sha"], "--", str(src)) or "(no source changes since last deploy)"
            title = f"diff since last deploy ({last['git_sha'][:10]}):"
        else:
            details = "\n".join(f"--- {s.relative_to(cfg.root)}\n{s.read_text()}" for s in cfg.sources)
            title = "full source (nothing deployed yet):"
        summary = [
            ("git HEAD", f"{head[:12] or '?'}{'  (unison/ has UNCOMMITTED changes)' if dirty else ''}"),
            ("page link", cfg.repo_url or "(none; set repo_url in humidor.toml)"),
            ("definitions", "\n" + "\n".join(f"      {d}" for d in definitions)),
        ]
        return summary, title + "\n" + _truncate(details)

    def deploy_one(cfg: Config, name: str, ctx: RequestContext, current: LiveService | None) -> dict:
        label = store.meta(name)["label"]
        result = run_ucm(ctx, ucm.deploy_transcript(cfg, name, label, store.token_path(name)))
        deployed = result.of_kind("deployed")
        if not deployed:
            ctx.outcome = "error"
            raise _error(502, "no_hash_reported", result.output[-2000:])
        new_hash = deployed[-1][0].strip()
        url = deployed[-1][1].strip().rstrip("/") + "/" if len(deployed[-1]) > 1 else None
        entry = {
            "action": "deploy",
            "humidor": name,
            "service": service_name(name),
            "hash": new_hash,
            "previous_hash": current.hash if current else None,
            "git_sha": _git(cfg.root, "rev-parse", "HEAD"),
            "git_dirty": bool(_git(cfg.root, "status", "--porcelain", "--", str(cfg.root / "unison"))),
            "source_sha256": _source_sha256(cfg),
        }
        ledger.append(entry)
        store.update(name, status="deployed", hash=new_hash, url=url, deployed=now())
        ctx.log("deployed", **entry, url=url)
        return {**entry, "label": label, "url": url, "hash_url": f"{_base_url(url)}/h/{new_hash}/" if url else None}

    def admin_call(name: str, method: str, path: str, body: dict | None = None) -> httpx.Response:
        url = store.meta(name).get("url")
        if not url:
            raise _error(409, "not_deployed", f"{name} has no known URL; it was never deployed successfully")
        headers = {"Authorization": f"Bearer {store.token(name)}"}
        content = None
        if body is not None:
            # Raw UTF-8: Unison's JSON decoder mishandles \\u surrogate-pair escapes.
            content = json.dumps(body, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        return http.request(method, f"{url}{path}", headers=headers, content=content)

    def row(name: str, live: dict[str, LiveService] | None) -> dict:
        meta = store.meta(name)
        svc = live.get(service_name(name)) if live is not None else None
        last = ledger.last_for_service(service_name(name))
        return {
            "name": meta["label"],
            "url": meta.get("url"),
            "live_hash": svc.hash if svc else None,
            "deployed_at": svc.deployed_at if svc else None,
            "state": _state(live, svc, last),
        }

    # --- read-only ---------------------------------------------------------

    @app.get("/health")
    def health() -> dict:
        cfg = config()
        return {
            "status": "ok",
            "repo": str(cfg.root),
            "setup": setup_checks(cfg, settings, runner),
            "humidors": {n: store.meta(n)["label"] for n in store.names()},
        }

    @app.get("/humidors")
    def list_humidors() -> dict:
        with request_log.context("ls") as ctx:
            live, live_error = try_live_services(ctx)
            known = {service_name(n) for n in store.names()}
            strays = [
                {"service": s.name, "live_hash": s.hash, "note": "marker-humidor service this server does not manage"}
                for s in (live or {}).values()
                if s.name.startswith(SERVICE_PREFIX + "-") and s.name not in known
            ]
            return {
                "humidors": [row(n, live) for n in store.names()],
                "strays": strays,
                "services_in_account": len(live) if live is not None else None,
                "live_error": live_error,
            }

    @app.post("/humidors/{name}/verify")
    def verify(name: str) -> dict:
        existing(name)
        with request_log.context(f"verify {name}") as ctx:
            live, live_error = try_live_services(ctx)
            result = verify_humidor(
                name, store.meta(name), live, live_error, ledger.last_for_service(service_name(name)), http
            )
            ctx.log("verified", ok=result["ok"], results=result["results"])
            return result

    # --- changes (approval required) ----------------------------------------

    @app.post("/humidors/{name}")
    def create(name: str, req: CreateRequest) -> dict:
        cfg = config()
        try:
            label = check_label(req.label)
            check_slug(name)
        except ConfigError as e:
            raise _error(400, "bad_name", str(e))
        if slug(label) != name:
            raise _error(400, "name_mismatch", f"humidor {label!r} would be served as {slug(label)!r}, not {name!r}")
        if store.exists(name):
            raise _error(409, "humidor_exists", f"humidor {store.meta(name)['label']!r} already exists")
        service = service_name(name)
        with request_log.context(f"create {name}") as ctx:
            live, live_error = try_live_services(ctx)
            if live is None:
                raise _error(
                    499, "cloud_auth_required", live_error or "could not list services", instructions=AUTH_INSTRUCTIONS
                )
            if service in live:
                raise _error(409, "service_exists", f"A service named {service!r} already exists in the account")
            source, details = source_summary(cfg, ctx)
            store.create(name, label)
            try:
                ask(
                    ctx,
                    ApprovalRequest(
                        action="create",
                        summary=[
                            ("humidor", f"{label}  (service {service})"),
                            ("services", f"{len(live)} in the account now, {len(live) + 1} after"),
                            *source,
                        ],
                        details=details,
                    ),
                )
                result = deploy_one(cfg, name, ctx, None)
            except BaseException:
                store.remove(name)
                raise
            return {"status": "created", **result}

    @app.post("/humidors/{name}/adopt")
    def adopt(name: str, req: CreateRequest) -> dict:
        """Take charge of an existing humidor service from this machine.

        Redeploys it with the current code and a new admin token, keeping its
        comments, and records it here. Works for a humidor this server has never
        seen (made on another machine, or after losing ~/.local/share/humidor),
        and for one it already manages (to replace a token that may have leaked).
        Any other copy of the old token stops working.
        """
        cfg = config()
        try:
            label = check_label(req.label)
            check_slug(name)
        except ConfigError as e:
            raise _error(400, "bad_name", str(e))
        if slug(label) != name:
            raise _error(400, "name_mismatch", f"humidor {label!r} would be served as {slug(label)!r}, not {name!r}")
        before = store.snapshot(name)
        if before is not None and label == name:
            label = store.meta(name)["label"]  # given in URL form; keep the display name we know
        service = service_name(name)
        with request_log.context(f"adopt {name}") as ctx:
            live, live_error = try_live_services(ctx)
            if live is None:
                raise _error(
                    499, "cloud_auth_required", live_error or "could not list services", instructions=AUTH_INSTRUCTIONS
                )
            current = live.get(service)
            if current is None:
                raise _error(
                    404,
                    "not_live",
                    f"No service named {service!r} in this Unison Cloud account; use `humidor create` for a new humidor",
                )
            source, details = source_summary(cfg, ctx)
            store.create(name, label)
            try:
                ask(
                    ctx,
                    ApprovalRequest(
                        action="adopt",
                        summary=[
                            ("humidor", f"{label}  (service {service})"),
                            ("currently live", _describe_live(current, None)),
                            (
                                "this machine",
                                "already manages it; its token will be replaced"
                                if before
                                else "does not manage it yet; it will from now on",
                            ),
                            (
                                "effect",
                                "redeploy with the current code and a new admin token. Comments are kept.\n"
                                "      Any other machine's copy of the old token stops working.",
                            ),
                            *source,
                        ],
                        details=details,
                    ),
                )
                result = deploy_one(cfg, name, ctx, current)
            except BaseException:
                store.restore(name, before)
                raise
            ctx.log("adopted", humidor=name, replaced_local_token=before is not None)
            return {"status": "adopted", "replaced_local_token": before is not None, **result}

    @app.post("/deploy")
    def deploy() -> dict:
        """Redeploy every humidor with the current code and settings."""
        cfg = config()
        names = store.names()
        if not names:
            raise _error(409, "no_humidors", "No humidors yet; create one with `humidor create NAME`")
        with request_log.context("deploy all") as ctx:
            source, details = source_summary(cfg, ctx)
            live, live_error = try_live_services(ctx)
            ask(
                ctx,
                ApprovalRequest(
                    action="deploy",
                    summary=[
                        *[
                            (
                                "humidor",
                                f"{store.meta(n)['label']}: now "
                                f"{_describe_live(live.get(service_name(n)) if live else None, live_error)}",
                            )
                            for n in names
                        ],
                        *source,
                    ],
                    details=details,
                ),
            )
            return {
                "status": "deployed",
                "deployed": [deploy_one(cfg, n, ctx, live.get(service_name(n)) if live else None) for n in names],
            }

    @app.delete("/humidors/{name}")
    def delete(name: str) -> dict:
        cfg = config()
        existing(name)
        label = store.meta(name)["label"]
        with request_log.context(f"delete {name}") as ctx:
            live, live_error = try_live_services(ctx)
            backup_note = backup(name, ctx)
            ask(
                ctx,
                ApprovalRequest(
                    action="delete",
                    summary=[
                        ("humidor", f"{label}  (service {service_name(name)})"),
                        ("currently live", _describe_live(live.get(service_name(name)) if live else None, live_error)),
                        ("backup", backup_note),
                        ("effect", "undeploy it, delete its service name, database and comments. Cannot be undone."),
                    ],
                ),
            )
            result = run_ucm(ctx, ucm.destroy_transcript(cfg, name))
            entry = {
                "action": "delete",
                "humidor": name,
                "service": service_name(name),
                "hash": None,
                "previous_hash": next((rec[0] for rec in result.of_kind("undeployed")), None),
                "git_sha": _git(cfg.root, "rev-parse", "HEAD"),
                "steps": [rec[0] for rec in result.records],
            }
            ledger.append(entry)
            store.remove(name)
            ctx.log("deleted", **entry)
            return {"status": "deleted", "name": label, **entry, "backup": backup_note}

    def backup(name: str, ctx: RequestContext) -> str:
        try:
            resp = admin_call(name, "GET", BACKUP_PATH)
            resp.raise_for_status()
        except (httpx.HTTPError, HTTPException) as e:
            ctx.log("backup_failed", error=str(e))
            return f"FAILED ({e}); nothing was saved"
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = store.backup_dir() / f"{service_name(name)}-{stamp}.json"
        path.write_text(resp.text)
        os.chmod(path, 0o600)
        ctx.log("backed_up", path=str(path), bytes=len(resp.content))
        return f"{len(resp.content)} bytes of comments saved to {path}"

    # --- admin proxy ---------------------------------------------------------

    @app.post("/humidors/{name}/admin")
    def admin(name: str, req: AdminRequest) -> dict:
        """Call a humidor's own API as its admin. Changes need approval."""
        existing(name)
        method = req.method.upper()
        if method not in ("GET", "POST", "PUT", "DELETE"):
            raise _error(400, "bad_method", method)
        path = req.path.lstrip("/")
        if not API_PATH_RE.match(path) or ".." in path.split("/"):
            raise _error(400, "bad_path", f"{req.path!r} is not a plain relative path")
        label = store.meta(name)["label"]
        with request_log.context(f"admin {method} {name} {path}") as ctx:
            if method != "GET":
                try:
                    current_resp = admin_call(name, "GET", path)
                    current: Any = (
                        current_resp.json()
                        if current_resp.status_code == 200
                        else f"(GET returned {current_resp.status_code}: {current_resp.text[:200]})"
                    )
                except (httpx.HTTPError, ValueError) as e:
                    current = f"(could not fetch: {e})"
                ctx.log("admin_current", current=current)
                ask(
                    ctx,
                    ApprovalRequest(
                        action=f"admin {method}",
                        summary=[("humidor", label), ("request", f"{method} {path} as admin")],
                        details=f"current:\n{_pretty(current)}"
                        + (f"\n\nnew body:\n{_pretty(req.body)}" if req.body is not None else ""),
                    ),
                )
            try:
                resp = admin_call(name, method, path, req.body)
            except httpx.HTTPError as e:
                raise _error(502, "upstream_unreachable", str(e))
            try:
                body: Any = resp.json()
            except ValueError:
                body = resp.text
            ctx.log("admin_response", status=resp.status_code, body=body)
            if resp.status_code >= 400:
                ctx.outcome = "error"
                raise _error(502, "upstream_error", f"{resp.status_code}: {_pretty(body)[:1000]}")
            return {"status": resp.status_code, "body": body}

    return app


def setup_checks(cfg: Config, settings: Settings, runner: UcmRunner) -> list[dict]:
    """What a new fork still needs to do, without calling the cloud."""
    checks = []

    def add(name: str, ok: bool, detail: str, fix: str = "") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail, **({"fix": fix} if not ok else {})})

    ucm_path = shutil.which(getattr(runner, "ucm", "ucm"))
    add(
        "ucm installed",
        ucm_path is not None,
        ucm_path or "not on PATH",
        "run the server inside `nix develop`, or install ucm 1.5+",
    )
    if CREDENTIALS.exists():
        mode = stat.S_IMODE(CREDENTIALS.stat().st_mode)
        add("logged in to Unison Cloud", True, str(CREDENTIALS))
        add(
            "login file private",
            mode & 0o077 == 0,
            f"mode {mode:o}",
            f"chmod 600 {CREDENTIALS}  (it controls your whole Unison Cloud account)",
        )
    else:
        add("logged in to Unison Cloud", False, "no credentials file", "run `ucm`, then `auth.login`")
    base = getattr(runner, "base_codebase", None)
    add(
        "base codebase built",
        base is None or base.exists(),
        str(base),
        "built automatically on first use (takes a minute or two)",
    )
    add("page link set", bool(cfg.repo_url), cfg.repo_url or "repo_url is empty", "set repo_url in humidor.toml")
    return checks


def instant_to_iso(text: str) -> str | None:
    """Unison's debug form of an Instant ("Instant +1762796643 642980000") as ISO 8601 UTC."""
    m = re.fullmatch(r"\s*Instant ([+-]?\d+) (\d+)\s*", text)
    if not m:
        return text.strip() or None
    t = datetime.fromtimestamp(int(m.group(1)), UTC).replace(microsecond=int(m.group(2)) // 1000)
    return t.isoformat()


def _describe_live(svc: LiveService | None, live_error: str | None) -> str:
    if live_error:
        return f"unknown ({live_error[:120]})"
    if svc is None:
        return "not registered"
    if svc.hash is None:
        return "name exists, nothing assigned"
    return f"{svc.hash[:16]}… deployed {svc.deployed_at or '?'}"


def _state(live: dict[str, LiveService] | None, svc: LiveService | None, last: dict | None) -> str:
    if live is None:
        return "unknown"
    if svc is None or svc.hash is None:
        return "not-deployed" if not last or last["action"] != "deploy" else "drift"
    if last is None or last["action"] != "deploy":
        return "drift"  # live, but not deployed by this server
    return "deployed" if last["hash"] == svc.hash else "drift"


def _check_http(http: httpx.Client, url: str, check: Check) -> dict:
    try:
        resp = http.get(url)
    except httpx.HTTPError as e:
        return {"status": "fail", "url": url, "message": f"request failed: {e}"}
    problems = []
    if resp.status_code != check.status:
        problems.append(f"status {resp.status_code}, expected {check.status}")
    if check.contains is not None and check.contains not in resp.text:
        problems.append(f"body does not contain {check.contains!r}")
    return {"status": "fail" if problems else "pass", "url": url, "message": "; ".join(problems) or "ok"}


def verify_humidor(
    name: str,
    meta: dict,
    live: dict[str, LiveService] | None,
    live_error: str | None,
    last: dict | None,
    http: httpx.Client,
) -> dict:
    results: list[dict] = []
    service = service_name(name)
    svc = live.get(service) if live is not None else None

    if live is None:
        results.append({"check": "registry", "status": "skip", "message": f"could not list services: {live_error}"})
    elif svc is None or svc.hash is None:
        results.append({"check": "registry", "status": "fail", "message": f"{service!r} has no deployment assigned"})
    else:
        results.append({"check": "registry", "status": "pass", "message": f"assigned to {svc.hash}"})
        if last is None or last["action"] != "deploy" or last["hash"] != svc.hash:
            results.append(
                {
                    "check": "ledger",
                    "status": "fail",
                    "message": f"live hash {svc.hash} is not the one this server last deployed ({(last or {}).get('hash')})",
                }
            )
        else:
            results.append({"check": "ledger", "status": "pass", "message": f"matches deploy at {last['time']}"})

    url = meta.get("url")
    if not url:
        results.append({"check": "url", "status": "fail", "message": "no URL recorded; it was never deployed"})
    for c in CHECKS if url else ():
        results.append({"check": f"GET {c.path or '/'}", **_check_http(http, f"{url}{c.path}", c)})
        if svc is not None and svc.hash:
            hash_url = f"{_base_url(url)}/h/{svc.hash}/{c.path}"
            results.append({"check": f"GET /h/<hash>/{c.path}", **_check_http(http, hash_url, c)})

    # A skipped check means we could not confirm what is deployed, so it is not ok.
    ok = all(res["status"] == "pass" for res in results)
    return {"name": meta["label"], "url": url, "ok": ok, "results": results}
