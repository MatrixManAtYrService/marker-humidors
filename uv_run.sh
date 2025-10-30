#!/usr/bin/env bash
# Run a command in this repo's Python environment via uv (the non-nix path).
#   ./uv_run.sh humidor ls
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

if ! command -v uv &>/dev/null; then
    echo "Error: uv is not installed." >&2
    echo "Install it from: https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

# Sync quietly; only show uv's output if it fails.
sync_stderr=$(mktemp)
uv sync --project "$REPO_ROOT" 2>"$sync_stderr" || {
    rc=$?
    cat "$sync_stderr" >&2
    rm -f "$sync_stderr"
    exit $rc
}
rm -f "$sync_stderr"

exec uv run --project "$REPO_ROOT" "$@"
