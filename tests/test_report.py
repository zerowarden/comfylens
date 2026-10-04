import json
from pathlib import Path

import pytest
from conftest import golden_png, png_with_text
from graph_builder import basic_txt2img
from typer.testing import CliRunner

from comfylens.cli import app
from comfylens.config import Config
from comfylens.db.connection import connect_readonly
from comfylens.index.indexer import Indexer
from comfylens.paths import catalog_path
from comfylens.report import build_report

runner = CliRunner()


def flux_png(seed: int, *, lora: float | None = None, patch: bool = False) -> bytes:
    g = basic_txt2img()
    g.prompt["7"]["inputs"]["seed"] = seed
    if lora is not None:
        g.node("20", "LoraLoaderModelOnly", lora_name="fox.safetensors", strength_model=lora,
               model=("1", 0))  # fmt: skip
        g.prompt["7"]["inputs"]["model"] = ["20", 0]
    if patch:
        g.node("21", "TeaCache", rel_l1_thresh=0.4, model=g.prompt["7"]["inputs"]["model"])
        g.prompt["7"]["inputs"]["model"] = ["21", 0]
    return png_with_text({"prompt": g.prompt}, (16, 24))


@pytest.fixture
def library(tmp_path: Path, config: Config) -> Path:
    root = tmp_path / "library"
    root.mkdir()
    (root / "golden.png").write_bytes(golden_png())
    (root / "golden copy.png").write_bytes(golden_png())  # identical content
    (root / "a.png").write_bytes(flux_png(1))
    (root / "b.png").write_bytes(flux_png(2, lora=0.8))
    (root / "c.png").write_bytes(flux_png(3, lora=1.0, patch=True))
    (root / "plain.png").write_bytes(png_with_text({}))
    (root / "broken.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    Indexer(root, config, workers=1).run()
    return root


def report(root: Path, config: Config, **kwargs) -> dict:
    conn = connect_readonly(catalog_path(root))
    try:
        return json.loads(json.dumps(build_report(conn, config, **kwargs)))
    finally:
        conn.close()


def test_files_families_classes_and_warnings(library: Path, config: Config):
    r = report(library, config)
    assert r["library"]["root"] == str(library)
    assert r["library"]["stale"] is False
    assert r["files"] == {
        "total": 7,
        "ok": 5,
        "parse_success_rate": 5 / 7,
        "by_status_format": [
            {"status": "ok", "format": "png", "files": 5},
            {"status": "error", "format": "png", "files": 1},
            {"status": "no_metadata", "format": "png", "files": 1},
        ],
    }
    assert r["families"] == {
        "counts": [{"family": "flux", "files": 3}, {"family": "qwen-image-2.1", "files": 2}],
        "unknown_base_models": [],
    }
    assert r["unregistered"] == [{"class_type": "TeaCache", "files": 1}]
    codes = {
        row["code"]: (row["count"], row["files"], row["informational"])
        for row in r["warnings"]["codes"]
    }
    assert codes == {
        "UNUSED_LORA": (2, 2, True),
        "UNKNOWN_MODEL_PATCH": (1, 1, True),
        "THUMBNAIL_FAILED": (1, 1, False),
    }
    assert r["warnings"]["unused_loras"] == [{"name": "qwen2.1-exampleV01_000004956", "files": 2}]
    assert r["timestamp_clusters"] == []


def test_per_family_statistics(library: Path, config: Config):
    r = report(library, config)
    assert [(f["family"], f["images"]) for f in r["per_family"]] == [
        ("flux", 3),
        ("qwen-image-2.1", 1),  # identical copies count once
    ]
    flux = r["per_family"][0]
    steps = flux["numeric"]["steps"]
    assert (steps["n"], steps["mode"], steps["mode_share"], steps["median"]) == (3, [20.0], 1.0, 20)
    # The same snapshot-derived values the UI shows: 3-decimal megapixels and rounded aspect.
    assert flux["numeric"]["megapixels"]["mode"] == [0.0]
    assert flux["numeric"]["aspect"]["mode"] == [0.667]
    assert flux["numeric"]["guidance"]["n"] == 0
    (fox,) = flux["loras"]
    assert (fox["name"], fox["images"], fox["share"]) == ("fox", 2, 2 / 3)
    # Strength statistics cover users only: no zero for the image without the LoRA.
    assert (fox["strength_model"]["n"], fox["strength_model"]["mean"]) == (2, 0.9)
    assert [c["count"] for c in flux["configs"]] == [1, 1, 1]
    assert flux["configs"][0]["fields"]["sampler_name"] == "euler"

    qwen = r["per_family"][1]
    assert qwen["configs"][0]["fields"]["lora_stack_key"] == (
        "qwen2.1-anime2real-sunburst@1.13 + qwen2.1-lenovo-ultrareal@1.06"
    )


def test_aspect_is_the_ui_value_not_a_second_implementation(tmp_path: Path, config: Config):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "tall.png").write_bytes(png_with_text({"prompt": basic_txt2img().prompt}, (832, 1216)))
    Indexer(root, config, workers=1).run()
    r = report(root, config)
    assert r["per_family"][0]["numeric"]["aspect"]["mode"] == [0.684]


def test_family_filter_and_timing(library: Path, config: Config):
    r = report(library, config, family="qwen-image-2.1")
    assert [f["family"] for f in r["per_family"]] == ["qwen-image-2.1"]
    assert r["timing"]["processed"] == 7
    assert r["timing"]["total_files_per_s"] > 0


def test_cli_index_and_report(tmp_path: Path):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "golden.png").write_bytes(golden_png())

    missing = runner.invoke(app, ["report", str(root)])
    assert missing.exit_code == 1
    assert "Run: comfylens index" in missing.output

    indexed = runner.invoke(app, ["index", str(root), "--workers", "1"])
    assert indexed.exit_code == 0, indexed.output
    assert "1 new" in indexed.output

    text = runner.invoke(app, ["report", str(root)], env={"COLUMNS": "200"})
    assert text.exit_code == 0, text.output
    for heading in ("1. Files", "3. Reachable classes", "6. Per family", "7. Timing"):
        assert heading in text.output
    assert "Parse success: 1 of 1 (100.0%)" in text.output

    as_json = runner.invoke(app, ["report", str(root), "--json"])
    assert json.loads(as_json.stdout)["files"]["ok"] == 1


def test_report_leaves_no_open_transaction(library: Path, config: Config):
    conn = connect_readonly(catalog_path(library))
    try:
        first = build_report(conn, config)
        assert not conn.in_transaction
        assert build_report(conn, config)["per_family"] == first["per_family"]
    finally:
        conn.close()
