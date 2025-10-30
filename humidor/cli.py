from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import typer

from humidor import config
from humidor.client import DEFAULT_URL, request

app = typer.Typer(
    help="humidor: run a fleet of marker humidor feedback pages on Unison Cloud.\n\n"
    "Each humidor gets a page, at a URL its QR code points to, where people leave comments. "
    "`humidor serve` (run by the owner) holds the Unison Cloud login and each humidor's admin token, and asks the "
    "owner, in its terminal, before anything is created, deployed, deleted or moderated. Every other command talks "
    f"to that server; point them elsewhere with HUMIDOR_SERVER_URL (default {DEFAULT_URL}).\n\n"
    "Names work in either form: a humidor called Chucho is served at .../s/marker-humidor-chucho/.",
    no_args_is_help=True,
)

Name = Annotated[str, typer.Argument(help="Humidor name, e.g. Chucho (or its URL form, chucho)")]
CommentId = Annotated[str, typer.Argument(metavar="COMMENT_ID", help="From `humidor comments NAME`")]
QrDir = Annotated[Path, typer.Option("--qr-dir", help="Where to write the printable sheet (NAME.pdf and NAME.png)")]
QR_BOTTOM = "scan to leave feedback"


def _print(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _waiting(what: str) -> None:
    print(f"Waiting for the owner to approve {what} in the humidor server's terminal...", file=sys.stderr)


def _slug(name: str) -> str:
    s = config.slug(name)
    if not s:
        raise typer.BadParameter(f"{name!r} has no letters or digits to put in a URL")
    return s


def _write_qr(url: str, label: str, qr_dir: Path) -> dict[str, str]:
    """Write the printable sheet: the QR card with the message card under it."""
    from humidor.qrcard import write_sheet

    repo = Path(os.environ.get("HUMIDOR_REPO", "."))
    try:
        message = config.load_config(repo).message_for(label)
    except config.ConfigError:
        message = config.Config(repo, "").message_for(label)  # not in the repo: use the default message
    stem = f"{config.SERVICE_PREFIX}-{config.slug(label)}"
    return write_sheet(url, f"humidor name: {label}", QR_BOTTOM, message, qr_dir, stem)


def _admin(name: str, method: str, path: str, body: dict | None = None) -> dict:
    return request(
        "POST",
        f"/humidors/{_slug(name)}/admin",
        json={"method": method, "path": path, "body": body},
        timeout=1800,
    )


@app.command()
def serve(
    host: Annotated[
        str, typer.Option(help="Interface to bind. Keep 127.0.0.1 unless clients are remote.")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on")] = 8100,
    rebuild_base: Annotated[bool, typer.Option(help="Rebuild the base codebase from unison/base.md first")] = False,
) -> None:
    """Start the humidor server. Owner only; run it in a terminal you watch.

    \b
    Approval prompts appear in this terminal. If it has no terminal (e.g.
    started with &), every change is denied. Needs ucm on PATH (`nix develop`
    provides it) and a Unison Cloud login (`ucm`, then `auth.login`).
    Env: HUMIDOR_REPO (default .), HUMIDOR_HOME (default ~/.local/share/humidor).
    """
    import uvicorn

    from humidor.server.main import Settings, create_app

    settings = Settings.from_env()
    server_app = create_app(settings)
    if rebuild_base:
        from humidor.server.ucm import UcmRunner

        typer.echo("Rebuilding base codebase...")
        UcmRunner(settings.home / "base-codebase", settings.root / "unison" / "base.md").ensure_base(rebuild=True)
    uvicorn.run(server_app, host=host, port=port)


@app.command()
def check() -> None:
    """Check the server and its setup; each problem comes with a fix. Exits 1 if anything is missing."""
    health = request("GET", "/health", timeout=30)
    _print(health)
    if not all(c["ok"] for c in health["setup"]):
        raise typer.Exit(code=1)


@app.command()
def ls() -> None:
    """List humidors and what is live.

    \b
    state is one of:
      deployed      live, and it is what this server last deployed
      not-deployed  nothing is assigned to its service name
      drift         live state differs from this server's records; run `humidor verify`
      unknown       could not list cloud services (see live_error)
    strays are marker-humidor services in the account that this server does not manage.
    """
    _print(request("GET", "/humidors"))


@app.command()
def verify(names: Annotated[list[str] | None, typer.Argument(help="Humidors to check (default: all)")] = None) -> None:
    """Test that every humidor is live and is what we think it is.

    \b
    registry  its service name has a deployment assigned
    ledger    that deployment is the one this server last deployed
    GET ...   its page and API answer, at its name URL and at its hash URL
    Exits 1 if any check fails or cannot run.
    """
    slugs = [_slug(n) for n in names] if names else list(request("GET", "/health", timeout=30)["humidors"])
    results = [request("POST", f"/humidors/{s}/verify") for s in slugs]
    ok = bool(results) and all(r["ok"] for r in results)
    _print({"ok": ok, "humidors": results})
    if not ok:
        raise typer.Exit(code=1)


@app.command()
def create(name: Name, qr_dir: QrDir = Path("qr")) -> None:
    """Deploy a page for a new humidor and write its printable sheet. Needs approval.

    The server creates the service, its database and an admin token (kept on the
    server). The sheet is drawn here: the QR card (for the URL the cloud assigned)
    with the message card from humidor.toml under it, ready to print and cut apart.
    """
    _waiting(f"creating {name}")
    result = request("POST", f"/humidors/{_slug(name)}", json={"label": name}, timeout=1800)
    result["sheet"] = _write_qr(result["url"], result["label"], qr_dir)
    _print(result)


@app.command()
def adopt(name: Name, qr_dir: QrDir = Path("qr")) -> None:
    """Take charge of an existing humidor from this machine. Needs approval.

    \b
    Use it to:
      - manage a humidor that was created on another machine,
      - recover after losing ~/.local/share/humidor on this one,
      - replace a humidor's admin token if it may have leaked.
    It redeploys the humidor with the current code and a new admin token,
    keeping its comments, and writes its printable sheet. Any other machine's
    copy of the old token stops working. Give the name as the page shows it
    (e.g. Chucho), so the page keeps its capitalization.
    """
    _waiting(f"adopting {name}")
    result = request("POST", f"/humidors/{_slug(name)}/adopt", json={"label": name}, timeout=1800)
    result["sheet"] = _write_qr(result["url"], result["label"], qr_dir)
    _print(result)


@app.command()
def qr(name: Name, qr_dir: QrDir = Path("qr")) -> None:
    """(Re)write an existing humidor's printable sheet (QR card + message card). Needs no approval."""
    rows = {config.slug(r["name"]): r for r in request("GET", "/humidors")["humidors"]}
    row = rows.get(_slug(name))
    if row is None or not row["url"]:
        known = ", ".join(r["name"] for r in rows.values()) or "(none)"
        raise typer.BadParameter(f"no deployed humidor {name!r}; existing: {known}")
    _print({"url": row["url"], "sheet": _write_qr(row["url"], row["name"], qr_dir)})


@app.command()
def deploy() -> None:
    """Redeploy every humidor with the current code and humidor.toml. Needs approval."""
    _waiting("redeploying every humidor")
    _print(request("POST", "/deploy", timeout=3600))


@app.command()
def delete(name: Name) -> None:
    """Remove a humidor and its comments. Needs approval.

    The server first saves a backup of the comments (in ~/.local/share/humidor/backups
    on the server), then undeploys the page and deletes its data. Its QR card stops working.
    """
    _waiting(f"deleting {name}")
    _print(request("DELETE", f"/humidors/{_slug(name)}", timeout=1800))


@app.command()
def comments(name: Name) -> None:
    """List a humidor's comments as admin, newest first. 'owner' is a session fingerprint."""
    _print(_admin(name, "GET", "api/comments")["body"])


@app.command()
def edit(
    name: Name,
    comment_id: CommentId,
    text: Annotated[str, typer.Argument(help="Replacement text (max 2000 characters)")],
) -> None:
    """Replace any comment's text as admin. Needs approval."""
    _waiting("the edit")
    _print(_admin(name, "PUT", f"api/comments/{quote(comment_id, safe='')}", {"text": text})["body"])


@app.command()
def rm(name: Name, comment_id: CommentId) -> None:
    """Delete any comment as admin. Needs approval."""
    _waiting("the deletion")
    _print(_admin(name, "DELETE", f"api/comments/{quote(comment_id, safe='')}")["body"])


def main() -> None:
    app()
