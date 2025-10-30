"""Typecheck the generated Unison programs against the app and the real pinned libraries.

Slow (forks the base codebase, and builds it on first run). Skipped when ucm is
absent or HUMIDOR_SKIP_UCM_TESTS is set. Nothing here talks to Unison Cloud.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from humidor.config import load_config
from humidor.server import ucm
from humidor.server.ucm import UcmRunner
from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.skipif(
    shutil.which("ucm") is None or bool(os.environ.get("HUMIDOR_SKIP_UCM_TESTS")),
    reason="needs ucm (nix develop); set HUMIDOR_SKIP_UCM_TESTS to skip",
)


@pytest.fixture(scope="module")
def runner() -> UcmRunner:
    home = Path(os.environ.get("HUMIDOR_HOME", Path.home() / ".local/share/humidor")).expanduser()
    return UcmRunner(home / "base-codebase", REPO_ROOT / "unison" / "base.md")


def test_app_and_deploy_program_typecheck(runner):
    result = runner.run(ucm.typecheck_transcript(load_config(REPO_ROOT)))
    assert any(d.startswith("markerHumidor.deploy :") for d in result.added_definitions()), result.output


def test_destroy_and_list_programs_typecheck(runner):
    config = load_config(REPO_ROOT)
    transcript = (
        ucm._load_sources(config)
        + ucm._unison_block(ucm.destroy_program("x") + ucm.LIST_PROGRAM)
        + ucm._ucm_block("update")
    )
    result = runner.run(transcript)
    assert "humidor.op.destroy" in result.output and "humidor.op.list" in result.output
