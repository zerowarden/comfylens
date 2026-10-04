"""Opt-in: run your own ComfyUI outputs through `inspect`. Skipped when the folder is empty.

Copy images into tests/fixtures/private/ (gitignored). Nothing is ever written there.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from comfylens.cli import app

PRIVATE = Path(__file__).parent / "fixtures" / "private"
FILES = sorted(p for p in PRIVATE.rglob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg"))


@pytest.mark.private
@pytest.mark.skipif(not FILES, reason="tests/fixtures/private holds no images")
@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_private_file_inspects_ok(path: Path):
    result = CliRunner().invoke(app, ["inspect", "--json", str(path)])
    assert result.exception is None, result.output
    assert json.loads(result.stdout)["status"] == "ok"
