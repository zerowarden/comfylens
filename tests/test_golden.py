"""Golden end-to-end test on a reference Qwen Image 2.1 graph.

The expected document is `inspect --json`. After an intended extraction change, regenerate
it and review its diff:
    COMFYLENS_UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py
test_indexer.test_golden_rows checks the same values once written to the catalog.
"""

import json
import os
from pathlib import Path

import pytest
from conftest import GOLDEN, load_golden, png_with_text

from comfylens.analytics.text import sentences
from comfylens.config import Config
from comfylens.extract.pipeline import Analysis, analyze
from comfylens.index.worker import Job, ParsedFile, Settings, process_file
from comfylens.inspect_data import to_dict
from comfylens.paths import thumb_path, thumbs_dir
from comfylens.warn import Code

PROMPT = load_golden("sample_qwen21.prompt.json")
WORKFLOW = load_golden("sample_qwen21.workflow.json")
EXPECTED = GOLDEN / "sample_qwen21.expected.json"
INSTRUCTION = (
    "Convert the image into a realistic photograph.\n\n"
    "Preserve the character's identity, pose, facial expression, hairstyle,\n"
    "clothing design, colors, accessories, composition, camera angle, and\n"
    "spatial arrangement from the reference image.\n\n\n"
)


@pytest.fixture
def golden(config) -> Analysis:
    return analyze(png_with_text({"prompt": PROMPT, "workflow": WORKFLOW}), config)


def test_matches_expected_document(config, golden):
    doc = json.loads(json.dumps(to_dict(golden, config.graph.output_classes)))
    if os.environ.get("COMFYLENS_UPDATE_GOLDEN"):
        EXPECTED.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", "utf-8")
    assert doc == json.loads(EXPECTED.read_text("utf-8"))


@pytest.fixture
def worked(config: Config, tmp_path: Path) -> ParsedFile:
    data = png_with_text({"prompt": PROMPT, "workflow": WORKFLOW})
    (tmp_path / "golden.png").write_bytes(data)
    job = Job("golden.png", len(data), 0)
    return process_file(job, Settings(tmp_path, thumbs_dir(), config))


def test_key_values_through_the_index_worker(worked: ParsedFile):
    """Key values stated directly, so a regenerated expected document cannot hide a change."""
    assert worked.extracted.status == "ok"
    assert thumb_path(thumbs_dir(), worked.content_hash).is_file()
    e = worked.extracted.extraction
    assert e is not None

    reachable = sorted((n for n, _, r in worked.extracted.nodes if r), key=int)
    assert reachable == ["1", "2", "3", "6", "7", "9", "11", "12", "27", "29"]
    assert sorted(n for n, _, r in worked.extracted.nodes if not r) == ["25", "28"]
    # Node 21 is bypassed in the UI and therefore absent from the API prompt.
    assert "21" not in {n for n, _, _ in worked.extracted.nodes}

    assert (e.model_family, e.base_model) == ("qwen-image-2.1", "qwen_image_2.1_int8_convrot")
    assert (e.text_encoder, e.clip_type, e.vae) == (
        "qwen3vl_8b_int8_convrot",
        "qwen_image",
        "qwen_image_2.1_vae_bf16",
    )
    (stage,) = e.stages
    assert (len(e.stages), stage.seed, stage.steps, stage.cfg) == (1, 898921074692413, 25, 2.0)
    assert (stage.sampler_name, stage.scheduler, stage.denoise) == ("euler", "simple", 0.97)

    used = [(u.position, u.name, u.strength_model) for u in e.loras if u.reachable]
    assert used == [
        (0, "qwen2.1-anime2real-sunburst", 1.13),
        (1, "qwen2.1-lenovo-ultrareal", 1.06),
    ]
    (unused,) = [u for u in e.loras if not u.reachable]
    assert (unused.node_id, unused.name, unused.strength_model) == (
        "25",
        "qwen2.1-exampleV01_000004956",
        0.97,
    )
    assert (unused.base_name, unused.step, unused.position) == ("qwen2.1-exampleV01", 4956, None)
    warnings = worked.read_warnings + worked.extracted.warnings
    assert [(w.code, w.node_id) for w in warnings] == [(Code.UNUSED_LORA, "25")]
    assert e.lora_stack_key == "qwen2.1-anime2real-sunburst@1.13 + qwen2.1-lenovo-ultrareal@1.06"

    assert e.positive_prompt == INSTRUCTION
    assert e.negative_prompt == "plastic, blur, low quality, text"
    (image,) = e.input_images
    assert (image.node_id, image.filename, image.sha256) == (
        "27",
        "pasted-image.png",
        "d22bc0fc91f29d00bf88aefca945c5bb16f6de426db9025788902c04e45ac099",
    )
    assert e.latent_source == "TextEncodeQwenImage21"
    assert (e.guidance, e.shift) == (None, None)
    assert len(sentences(e.positive_prompt)) == 2  # despite the line wrapping


def test_dimensions_come_from_the_file_header(config):
    data = png_with_text({"prompt": PROMPT}, size=(896, 1632))
    doc = to_dict(analyze(data, config), config.graph.output_classes)
    assert doc["file"] == {
        "format": "png",
        "width": 896,
        "height": 1632,
        "megapixels": 1.462,
        "aspect": 0.549,
        "aspect_label": "9:16",
    }
