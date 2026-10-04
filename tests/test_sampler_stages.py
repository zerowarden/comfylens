"""Each sampler stage (e.g. a hires or refine pass) keeps its own model, LoRAs and prompts."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import png_with_text, wait_for, write_file
from fastapi.testclient import TestClient
from graph_builder import REALISM_PROMPT, basic_txt2img, krea2_api, krea2_qwen_realism

from comfylens.api.app import create_app
from comfylens.config import Config
from comfylens.db.connection import connect_readonly
from comfylens.db.read import loras_frame
from comfylens.index.indexer import Indexer
from comfylens.paths import catalog_path
from comfylens.warn import Code


def hires(*, extra_lora: bool = False):
    """basic_txt2img with a LoRA, then a second KSampler on the upscaled latent."""
    g = basic_txt2img()
    g.node("20", "LoraLoaderModelOnly", lora_name="fox.safetensors", strength_model=0.8,
           model=("1", 0))  # fmt: skip
    g.prompt["7"]["inputs"]["model"] = ["20", 0]
    second_model = ("20", 0)
    if extra_lora:  # the second pass adds a detail LoRA on top of the same chain
        g.node("21", "LoraLoaderModelOnly", lora_name="detail.safetensors", strength_model=0.5,
               model=("20", 0))  # fmt: skip
        second_model = ("21", 0)
    g.node("15", "LatentUpscaleBy", upscale_method="nearest-exact", scale_by=1.5,
           samples=("7", 0))  # fmt: skip
    g.node("16", "KSampler", seed=99, steps=12, cfg=3.5, sampler_name="euler",
           scheduler="normal", denoise=0.45, model=second_model, positive=("4", 0),
           negative=("5", 0), latent_image=("15", 0))  # fmt: skip
    g.node("8", "VAEDecode", samples=("16", 0), vae=("3", 0))
    return g


def test_each_pass_keeps_its_own_model_loras_and_prompts(config):
    e = krea2_qwen_realism().extract(config)
    krea, qwen = e.stages
    assert (krea.model_family, krea.base_model, krea.clip_type) == (
        "krea-2",
        "krea2_turbo_fp8_scaled",
        "krea2",
    )
    assert (qwen.model_family, qwen.base_model, qwen.clip_type) == (
        "qwen-image-2.1",
        "qwen_image_2.1_int8_convrot",
        "qwen_image",
    )
    assert (krea.text_encoder, qwen.text_encoder) == (
        "qwen3vl_4b_fp8_scaled",
        "qwen3vl_8b_int8_convrot",
    )
    assert (krea.lora_stack_key, qwen.lora_stack_key) == (
        "krea2_darkbrush@0.8",
        "qwen2.1-lenovo-ultrareal@1.06",
    )
    assert (krea.positive_prompt, krea.negative_prompt) == (
        "a red fox in the snow, muted minimalist sketch style",
        "",
    )
    assert (qwen.positive_prompt, qwen.negative_prompt) == (REALISM_PROMPT, "plastic, blur")
    assert (krea.latent_source, qwen.latent_source) == ("EmptyLatentImage", "TextEncodeQwenImage21")
    assert (qwen.steps, qwen.cfg, qwen.denoise) == (25, 2.0, 0.35)


def test_a_pass_through_another_model_names_the_pipeline(config):
    e = krea2_qwen_realism().extract(config)
    assert e.model_family == "krea-2 + qwen-image-2.1"
    # Everything else at image level is the primary stage's.
    assert (e.base_model, e.clip_type, e.text_encoder) == (
        "krea2_turbo_fp8_scaled",
        "krea2",
        "qwen3vl_4b_fp8_scaled",
    )
    assert e.lora_stack_key == "krea2_darkbrush@0.8"
    assert e.positive_prompt == "a red fox in the snow, muted minimalist sketch style"
    assert e.config_key.startswith('["krea-2 + qwen-image-2.1","krea2_turbo_fp8_scaled",')
    assert e.stage_prompts == f"{REALISM_PROMPT}\n\nplastic, blur"
    assert e.warnings == []


def test_loras_carry_their_stage_and_position_in_its_chain(config):
    e = krea2_qwen_realism().extract(config)
    assert [(u.stage_index, u.position, u.name) for u in e.loras] == [
        (0, 0, "krea2_darkbrush"),
        (1, 0, "qwen2.1-lenovo-ultrareal"),
    ]


def test_hires_fix_on_one_model_keeps_a_plain_family(config):
    e = hires().extract(config)
    assert e.model_family == "flux"
    assert [s.model_family for s in e.stages] == ["flux", "flux"]
    assert [s.lora_stack_key for s in e.stages] == ["fox@0.8", "fox@0.8"]
    # The shared LoRA is listed once per stage, each at its place in that stage's chain.
    assert [(u.stage_index, u.position, u.name) for u in e.loras] == [(0, 0, "fox"), (1, 0, "fox")]
    assert e.stage_prompts is None  # both stages share the primary's prompts


def test_a_later_stage_can_extend_the_chain(config):
    e = hires(extra_lora=True).extract(config)
    assert [s.lora_stack_key for s in e.stages] == ["fox@0.8", "fox@0.8 + detail@0.5"]
    assert e.lora_stack_key == "fox@0.8"
    assert [(u.stage_index, u.position, u.name) for u in e.loras] == [
        (0, 0, "fox"),
        (1, 0, "fox"),
        (1, 1, "detail"),
    ]


def test_a_stage_family_ignores_the_pass_that_made_its_input(config):
    # The realism pass's nodes reach back through the Krea image, but its family comes from
    # its own model and encoder only, and vice versa.
    g = krea2_qwen_realism()
    g.prompt["101"]["inputs"]["unet_name"] = "mystery_model.safetensors"
    g.prompt["102"]["inputs"]["type"] = "mystery"
    g.prompt["109"]["class_type"] = "TextEncodeMystery"
    e = g.extract(config)
    assert [s.model_family for s in e.stages] == ["krea-2", "unknown"]
    assert e.model_family == "krea-2 + unknown"


def test_unrecognized_stages_fall_back_to_the_whole_graph(config):
    # A sampler pass over a hosted Krea 2 image: the stage alone is unrecognized, so the
    # generator upstream names the family.
    g = basic_txt2img()
    g.prompt["1"]["inputs"]["unet_name"] = "mystery_model.safetensors"
    g.prompt["2"]["inputs"]["type"] = "mystery"
    g.prompt["30"] = krea2_api().prompt["1"]
    g.node("31", "VAEEncode", pixels=("30", 0), vae=("3", 0))
    g.prompt["7"]["inputs"]["latent_image"] = ["31", 0]
    e = g.extract(config)
    assert [s.model_family for s in e.stages] == ["unknown"]
    assert e.model_family == "krea-2-api"


def test_conditioning_warnings_come_from_every_stage(config):
    g = krea2_qwen_realism()
    del g.prompt["109"]["inputs"]["prompt"]
    e = g.extract(config)
    assert e.stages[1].positive_prompt is None
    assert (Code.PROMPT_UNRESOLVED, "109") in [(w.code, w.node_id) for w in e.warnings]


@pytest.fixture
def library(tmp_path: Path, config: Config) -> Path:
    root = tmp_path / "library"
    write_file(root, "realism.png", png_with_text({"prompt": krea2_qwen_realism().prompt}), 1)
    write_file(root, "hires.png", png_with_text({"prompt": hires().prompt}), 2)
    Indexer(root, config, workers=1).run()
    return root


def query(root: Path, sql: str) -> list[tuple]:
    conn = connect_readonly(catalog_path(root))
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_stages_and_their_loras_are_stored(library: Path):
    assert query(
        library,
        "SELECT f.rel_path, s.stage_index, s.model_family, s.base_model, s.lora_stack_key,"
        " s.positive_prompt FROM sampler_stages s JOIN files f ON f.id = s.file_id"
        " ORDER BY f.rel_path, s.stage_index",
    ) == [
        ("hires.png", 0, "flux", "flux1-dev", "fox@0.8", "a red fox in the snow"),
        ("hires.png", 1, "flux", "flux1-dev", "fox@0.8", "a red fox in the snow"),
        ("realism.png", 0, "krea-2", "krea2_turbo_fp8_scaled", "krea2_darkbrush@0.8",
         "a red fox in the snow, muted minimalist sketch style"),
        ("realism.png", 1, "qwen-image-2.1", "qwen_image_2.1_int8_convrot",
         "qwen2.1-lenovo-ultrareal@1.06", REALISM_PROMPT),
    ]  # fmt: skip
    assert query(
        library,
        "SELECT f.rel_path, g.model_family FROM generations g JOIN files f ON f.id = g.file_id"
        " ORDER BY f.rel_path",
    ) == [("hires.png", "flux"), ("realism.png", "krea-2 + qwen-image-2.1")]


def test_a_lora_shared_by_stages_counts_once_in_statistics(library: Path):
    assert query(library, "SELECT COUNT(*) FROM loras WHERE name = 'fox'") == [(2,)]
    conn = connect_readonly(catalog_path(library))
    try:
        frame = loras_frame(conn)
    finally:
        conn.close()
    assert sorted(frame["name"].to_list()) == ["fox", "krea2_darkbrush", "qwen2.1-lenovo-ultrareal"]


@pytest.fixture
def client(library: Path, config: Config) -> Iterator[TestClient]:
    app = create_app(library, config, index_on_start=False, web_dir=None)
    with TestClient(app) as c:
        wait_for(lambda: c.get("/api/library").json()["prompts_ready"])
        yield c


def test_detail_serves_each_stage(client: TestClient):
    items = client.post("/api/images/query", json={"limit": 10}).json()["items"]
    (realism,) = [i for i in items if i["rel_path"] == "realism.png"]
    d = client.get(f"/api/images/{realism['id']}").json()
    assert d["generation"]["model_family"] == "krea-2 + qwen-image-2.1"
    assert [(s["model_family"], s["lora_stack_key"]) for s in d["stages"]] == [
        ("krea-2", "krea2_darkbrush@0.8"),
        ("qwen-image-2.1", "qwen2.1-lenovo-ultrareal@1.06"),
    ]
    assert d["stages"][1]["positive_prompt"] == REALISM_PROMPT
    assert [(lora["stage_index"], lora["name"]) for lora in d["loras"]] == [
        (0, "krea2_darkbrush"),
        (1, "qwen2.1-lenovo-ultrareal"),
    ]


def test_prompt_search_covers_later_stages(library: Path, client: TestClient):
    found = query(
        library,
        "SELECT f.rel_path FROM prompts_fts JOIN files f ON f.id = prompts_fts.rowid"
        " WHERE prompts_fts MATCH '\"realistic photograph\"'",
    )
    assert found == [("realism.png",)]
    filters = {"filters": {"text": "realistic photograph"}}
    assert client.post("/api/images/query", json=filters).json()["total"] == 1
