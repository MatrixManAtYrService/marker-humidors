from __future__ import annotations

import os
import sys

import httpx

DEFAULT_URL = "http://127.0.0.1:8100"


def server_url() -> str:
    return os.environ.get("HUMIDOR_SERVER_URL", DEFAULT_URL).rstrip("/")


def request(method: str, path: str, json: dict | None = None, timeout: float = 600) -> dict:
    """Call the humidor server and return its JSON body.

    Exit codes: 1 cannot reach server, 2 a human must act (499),
    3 request denied (403), 4 other server error.
    """
    url = f"{server_url()}{path}"
    try:
        resp = httpx.request(method, url, json=json, timeout=timeout)
    except httpx.ConnectError:
        print(
            f"Error: cannot reach the humidor server at {server_url()}.\nThe owner starts it with: humidor serve",
            file=sys.stderr,
        )
        sys.exit(1)
    except httpx.ReadTimeout:
        print(f"Error: humidor server did not answer within {timeout}s ({method} {path}).", file=sys.stderr)
        sys.exit(4)

    try:
        data = resp.json()
    except ValueError:
        print(f"Error: non-JSON response (HTTP {resp.status_code}):\n{resp.text[:500]}", file=sys.stderr)
        sys.exit(4)

    if resp.status_code == 499:
        print(f"Action required: {data.get('message', data.get('error'))}", file=sys.stderr)
        if "instructions" in data:
            print(data["instructions"], file=sys.stderr)
        sys.exit(2)
    if resp.status_code == 403:
        print(f"Denied: {data.get('reason', data)}", file=sys.stderr)
        sys.exit(3)
    if resp.status_code >= 400:
        print(f"Error ({resp.status_code}): {data.get('error')}: {data.get('message', '')}", file=sys.stderr)
        sys.exit(4)
    return data
