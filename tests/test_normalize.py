import re

import pytest

from comfylens.extract.normalize import (
    aspect,
    lora_base_step,
    model_stem,
    prompt_ws,
    round_key,
    size_facts,
)

STEP = re.compile(r"^(?P<base>.+?)[_-](?P<step>\d{6,})$")


@pytest.mark.parametrize(
    "raw,stem",
    [
        ("qwen/qwen_image_2.1_int8_convrot.safetensors", "qwen_image_2.1_int8_convrot"),
        ("C:\\models\\unet\\flux.gguf", "flux"),
        ("model.CKPT", "model"),
        ("a.pt", "a"),
        ("a.pth", "a"),
        ("a.bin", "a"),
        ("a.sft", "a"),
        ("no_extension", "no_extension"),
        ("weird.name.v2", "weird.name.v2"),
    ],
)
def test_model_stem(raw, stem):
    assert model_stem(raw) == stem


@pytest.mark.parametrize(
    "name,expected",
    [
        ("qwen2.1-mystyle_000004000", ("qwen2.1-mystyle", 4000)),
        ("foo-123456", ("foo", 123456)),
        ("style_2025", ("style_2025", None)),  # fewer than six digits
        ("plain", ("plain", None)),
    ],
)
def test_lora_base_step(name, expected):
    assert lora_base_step(name, STEP) == expected


def test_round_key():
    assert round_key(1.1300000001, 4) == 1.13
    value = round_key(-0.00001, 2)
    assert value == 0.0 and str(value) == "0.0"


@pytest.mark.parametrize(
    "size,expected",
    [
        ((896, 1632), (0.549, "9:16")),
        ((1024, 1024), (1.0, "1:1")),
        ((1632, 896), (1.821, "16:9")),
        ((832, 1216), (0.684, "2:3")),
        ((1000, 1250), (0.8, "4:5")),
        ((900, 2100), (0.429, "9:21")),
        ((1000, 700), (1.429, "other")),
    ],
)
def test_aspect(size, expected):
    assert aspect(*size) == expected


def test_prompt_ws():
    assert prompt_ws("  a\t\tb  c\r\nd  ") == "a b c\nd"


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (832, 1216, {"megapixels": 1.012, "aspect": 0.684, "aspect_label": "2:3"}),
        (1024, 1024, {"megapixels": 1.049, "aspect": 1.0, "aspect_label": "1:1"}),
        (None, 1024, {"megapixels": None, "aspect": None, "aspect_label": None}),
        (1024, 0, {"megapixels": None, "aspect": None, "aspect_label": None}),
    ],
)
def test_size_facts(width, height, expected):
    assert size_facts(width, height) == expected
