"""Krea 2 recognition, on graphs modeled on ComfyUI v0.38.2's own Krea 2 templates."""

import pytest
from graph_builder import KREA2_SYSTEM, krea2_api, krea2_turbo

from comfylens.warn import INFORMATIONAL_CODES, Code


def codes(e):
    return [(w.code, w.node_id) for w in e.warnings]


def test_krea2_turbo_plain(config):
    _graph, reach, e = krea2_turbo().run(config)
    assert e.model_family == "krea-2"
    assert (e.base_model, e.text_encoder, e.clip_type, e.vae) == (
        "krea2_turbo_fp8_scaled",
        "qwen3vl_4b_fp8_scaled",
        "krea2",
        "qwen_image_vae",
    )
    (stage,) = e.stages
    assert (stage.steps, stage.cfg, stage.sampler_name, stage.scheduler, stage.denoise) == (
        8,
        1.0,
        "euler",
        "simple",
        1.0,
    )
    assert (e.positive_prompt, e.negative_prompt) == ("a red fox in the snow", "")
    assert (e.latent_source, e.batch_size) == ("EmptyLatentImage", 1)
    # The switch left the LoRA out of the chain: it never ran.
    assert e.lora_stack_key == "(none)"
    assert codes(e) == [(Code.UNUSED_LORA, "30:15")]
    assert "30:16" not in reach.reachable  # TextGenerate did not run either


def test_krea2_turbo_with_lora_and_style(config):
    e = krea2_turbo(lora=True).extract(config)
    assert e.lora_stack_key == "krea2_darkbrush@0.8"
    assert e.base_model == "krea2_turbo_fp8_scaled"
    assert e.positive_prompt == "a red fox in the snow, muted minimalist sketch style"
    assert codes(e) == []


def test_krea2_turbo_with_prompt_rewrite(config):
    e = krea2_turbo(enhance=True).extract(config)
    # The LLM's output is not stored; its input stands in, with an informational warning.
    assert e.positive_prompt == f"{KREA2_SYSTEM} a red fox in the snow"
    assert codes(e) == [(Code.UNUSED_LORA, "30:15"), (Code.GENERATED_PROMPT, "30:16")]
    assert Code.GENERATED_PROMPT in INFORMATIONAL_CODES


def test_krea2_api_node(config):
    e = krea2_api().extract(config)
    assert e.model_family == "krea-2-api"
    assert e.stages == [] and e.base_model is None
    assert e.positive_prompt == "high fashion editorial close-up portrait"
    assert e.negative_prompt is None
    assert codes(e) == [(Code.NO_SAMPLER, None)]
    assert ("model.aspect_ratio", "1:1") in {(i.input_name, i.value) for i in e.generic_inputs}


def test_a_generator_prompt_rewritten_by_an_llm_is_flagged(config):
    g = krea2_api()
    g.node("3", "PrimitiveStringMultiline", value="a red fox")
    g.node("4", "TextGenerate", prompt=("3", 0))
    g.prompt["1"]["inputs"]["prompt"] = ["4", 0]
    e = g.extract(config)
    assert e.positive_prompt == "a red fox"
    assert codes(e) == [(Code.NO_SAMPLER, None), (Code.GENERATED_PROMPT, "4")]


def test_a_computed_model_switch_breaks_the_chain(config):
    g = krea2_turbo()
    g.node("30:23", "CompareNumbers", a=1, b=2)  # the LoRA toggle is computed at run time
    e = g.extract(config)
    assert e.base_model is None
    assert (Code.MODEL_CHAIN_BROKEN, "30:22") in codes(e)
    assert e.model_family == "krea-2"  # still known from the text encoder type


@pytest.mark.parametrize("enhance,lora", [(False, False), (True, True)])
def test_krea2_switch_states_affect_reachability(config, enhance, lora):
    _graph, reach, _e = krea2_turbo(enhance=enhance, lora=lora).run(config)
    assert ("30:16" in reach.reachable) is enhance
    assert ("30:15" in reach.reachable) is lora
