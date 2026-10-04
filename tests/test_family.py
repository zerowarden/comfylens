import pytest
from graph_builder import basic_txt2img

from comfylens.config import build_config
from comfylens.extract.family import match_family


@pytest.mark.parametrize(
    "unet,family",
    [
        ("qwen/qwen_image_2.1_int8.safetensors", "qwen-image-2.1"),
        ("Qwen-Image-2.1-fp8.safetensors", "qwen-image-2.1"),
        ("qwen_image_fp8_e4m3fn.safetensors", "qwen-image"),
        ("krea2_turbo_fp8_scaled.safetensors", "krea-2"),
        ("Krea-2-Medium.safetensors", "krea-2"),
        ("flux1-krea-dev_fp8_scaled.safetensors", "flux1-krea"),  # precedes flux
        ("flux1-dev.safetensors", "flux"),
        ("sd3.5_large.safetensors", "unknown"),
    ],
)
def test_unet_rules_in_order(config, unet, family):
    g = basic_txt2img()
    g.prompt["1"]["inputs"]["unet_name"] = unet
    g.prompt["2"]["inputs"]["type"] = "stable_diffusion"
    assert g.extract(config).model_family == family


def test_clip_type_and_class_rules(config):
    g = basic_txt2img()
    g.prompt["1"]["inputs"]["unet_name"] = "mystery.safetensors"
    g.prompt["2"]["inputs"]["type"] = "qwen_image"
    assert g.extract(config).model_family == "qwen-image"

    g.node("4", "TextEncodeQwenImage21", prompt="x", negative_prompt="", clip=("2", 0))
    assert g.extract(config).model_family == "qwen-image-2.1"


def test_unknown_keeps_base_model(config):
    g = basic_txt2img()
    g.prompt["1"]["inputs"]["unet_name"] = "mystery.safetensors"
    g.prompt["2"]["inputs"]["type"] = "stable_diffusion"
    e = g.extract(config)
    assert (e.model_family, e.base_model) == ("unknown", "mystery")


def test_condition_keys_must_all_match():
    config = build_config(
        {
            "families": [
                {"name": "both", "any": [{"unet_regex": "flux", "clip_type": "qwen_image"}]},
                {"name": "ckpt", "any": [{"ckpt_regex": "(?i)juggernaut"}]},
            ]
        }
    )
    rules = config.families
    common = {"loader_kind": "unet", "loader_name": "flux.safetensors", "class_types": set()}
    assert match_family(rules, clip_type="flux", **common) == "unknown"
    assert match_family(rules, clip_type="qwen_image", **common) == "both"
    assert (
        match_family(
            rules,
            loader_kind="ckpt",
            loader_name="Juggernaut.safetensors",
            clip_type=None,
            class_types=set(),
        )
        == "ckpt"
    )
    # unet_regex never matches a checkpoint name.
    common["loader_kind"] = "ckpt"
    assert match_family(rules, clip_type="qwen_image", **common) == "unknown"
