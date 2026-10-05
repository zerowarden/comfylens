import io

import pytest
from conftest import png_with_text
from graph_builder import basic_txt2img
from PIL import Image

from comfylens.collection.a1111 import loras, parse_parameters, settings_pairs
from comfylens.collection.drafts import build_draft
from comfylens.collection.store import CollectionStore
from comfylens.config import Config

PARAMETERS = """a red fox in the snow, <lora:fox_v2:0.8>
golden hour
Negative prompt: blurry, lowres
watermark
Steps: 28, Sampler: DPM++ 2M, Schedule type: Karras, CFG scale: 6.5, Seed: 1234567890123, \
Size: 832x1216, Model hash: abc123, Model: juggernautXL_v9, Denoising strength: 0.35, \
Lora hashes: "fox_v2: 1a2b, other: 3c4d", Version: v1.10.1"""


def test_full_block():
    parsed = parse_parameters(PARAMETERS)
    assert parsed is not None
    assert parsed["positive"] == "a red fox in the snow, <lora:fox_v2:0.8>\ngolden hour"
    assert parsed["negative"] == "blurry, lowres\nwatermark"
    assert parsed["settings"] == {
        "base_model": "juggernautXL_v9",
        "seed": "1234567890123",
        "steps": 28,
        "cfg": 6.5,
        "sampler_name": "DPM++ 2M",
        "scheduler": "Karras",
        "denoise": 0.35,
        "guidance": None,
        "shift": None,
        "loras": [{"name": "fox_v2", "strength_model": 0.8, "strength_clip": 0.8}],
    }


def test_quoted_values_keep_their_commas():
    pairs = settings_pairs('Steps: 4, Lora hashes: "a: 1, b: 2", Seed: 7, Note: "say \\"hi\\""')
    assert pairs == {"Steps": "4", "Lora hashes": "a: 1, b: 2", "Seed": "7", "Note": 'say "hi"'}


def test_without_negative_or_settings():
    parsed = parse_parameters("just a prompt\r\nover two lines")
    assert parsed is not None
    assert (parsed["positive"], parsed["negative"]) == ("just a prompt\nover two lines", "")
    assert parsed["settings"]["steps"] is None
    no_negative = parse_parameters("a cat\nSteps: 20, Sampler: Euler a, Seed: 1")
    assert no_negative is not None and no_negative["positive"] == "a cat"
    assert no_negative["settings"]["sampler_name"] == "Euler a"


def test_forge_flux_guidance_and_bad_numbers():
    parsed = parse_parameters(
        "x\nSteps: 20, Sampler: Euler, CFG scale: 1, Distilled CFG Scale: 3.5, Seed: -1"
    )
    assert parsed is not None
    assert parsed["settings"]["guidance"] == 3.5
    assert parsed["settings"]["seed"] is None  # -1 means random, not a seed
    odd = parse_parameters("x\nSteps: 20, CFG scale: high")
    assert odd is not None and odd["settings"]["cfg"] is None


def test_nothing_to_read():
    assert parse_parameters("") is None
    assert parse_parameters("\n\n") is None


def test_lora_tags():
    assert loras("<lora:a:0.5> <LORA:b> <lyco:c:0.4:0.9> <lora:d:te=0.2:unet=0.7> <lora:e:x>") == [
        {"name": "a", "strength_model": 0.5, "strength_clip": 0.5},
        {"name": "b", "strength_model": 1.0, "strength_clip": 1.0},
        {"name": "c", "strength_model": 0.9, "strength_clip": 0.4},
        {"name": "d", "strength_model": 0.7, "strength_clip": 0.2},
        {"name": "e", "strength_model": 1.0, "strength_clip": 1.0},
    ]


def _user_comment_image(fmt: str, text: str) -> bytes:
    exif = Image.Exif()
    exif.get_ifd(0x8769)[0x9286] = b"UNICODE\0" + text.encode("utf-16-be")
    buf = io.BytesIO()
    Image.new("RGB", (12, 12), (9, 9, 9)).save(buf, fmt, exif=exif.tobytes())
    return buf.getvalue()


@pytest.mark.parametrize(
    "data",
    [
        png_with_text({"parameters": PARAMETERS}),
        _user_comment_image("JPEG", PARAMETERS),
        _user_comment_image("WEBP", PARAMETERS),
    ],
    ids=["png", "jpeg", "webp"],
)
def test_drafts_read_a1111(data: bytes, store: CollectionStore, config: Config):
    draft = build_draft(data, store, config)
    assert draft["metadata"] == "a1111"
    assert draft["title"] == "a red fox in the snow"
    assert draft["negative"] == "blurry, lowres\nwatermark"
    assert draft["settings"]["steps"] == 28
    assert draft["model_family"] is None
    assert not draft["original"]["has_workflow"]


def test_comfyui_metadata_wins(store: CollectionStore, config: Config):
    data = png_with_text({"prompt": basic_txt2img().prompt, "parameters": "other\nSteps: 3"})
    assert build_draft(data, store, config)["metadata"] == "comfyui"
