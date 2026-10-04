from graph_builder import basic_txt2img

from comfylens.warn import Code


def codes(e):
    return [w.code for w in e.warnings]


def test_flux_guidance(config):
    g = basic_txt2img()
    g.node("10", "FluxGuidance", guidance=3.5, conditioning=("4", 0))
    g.prompt["7"]["inputs"]["positive"] = ["10", 0]
    e = g.extract(config)
    assert (e.guidance, e.positive_prompt) == (3.5, "a red fox in the snow")


def test_conditioning_zero_out(config):
    g = basic_txt2img()
    g.node("10", "ConditioningZeroOut", conditioning=("4", 0))
    g.prompt["7"]["inputs"]["negative"] = ["10", 0]
    e = g.extract(config)
    assert e.negative_prompt == ""
    assert e.warnings == []


def test_conditioning_combine_with_two_texts(config):
    g = basic_txt2img()
    g.node("10", "CLIPTextEncode", text="golden hour", clip=("2", 0))
    g.node("11", "ConditioningCombine", conditioning_1=("4", 0), conditioning_2=("10", 0))
    g.prompt["7"]["inputs"]["positive"] = ["11", 0]
    e = g.extract(config)
    # "10" sorts before "4" in topological order.
    assert e.positive_prompt == "golden hour\n\na red fox in the snow"
    assert codes(e) == [Code.MULTIPLE_PROMPT_SOURCES]


def test_prompt_via_string_concatenate(config):
    g = basic_txt2img()
    g.node("10", "PrimitiveStringMultiline", value="a red fox")
    g.node("11", "PrimitiveString", value="in the snow")
    g.node("12", "StringConcatenate", string_a=("10", 0), string_b=("11", 0), delimiter=", ")
    g.prompt["4"]["inputs"]["text"] = ["12", 0]
    assert g.extract(config).positive_prompt == "a red fox, in the snow"


def test_text_from_unregistered_node_is_unresolved(config):
    # An unregistered node computes its output, even with one string literal input.
    g = basic_txt2img()
    g.node("10", "WildcardProcessor", wildcard_text="__animal__", seed=5)
    g.prompt["4"]["inputs"]["text"] = ["10", 0]
    e = g.extract(config)
    assert e.positive_prompt is None
    assert [(w.code, w.node_id) for w in e.warnings] == [(Code.PROMPT_UNRESOLVED, "4")]


def test_heuristic_unknown_encoder(config):
    g = basic_txt2img()
    g.node("10", "FancyTextEncode", style="short", text="a long prompt about a fox", clip=("2", 0))
    g.prompt["7"]["inputs"]["positive"] = ["10", 0]
    e = g.extract(config)
    assert e.positive_prompt == "a long prompt about a fox"
    assert [(w.code, w.node_id) for w in e.warnings] == [(Code.HEURISTIC_PROMPT, "10")]


def test_unknown_pass_through_follows_cond_inputs(config):
    g = basic_txt2img()
    g.node("10", "StyleModelApply", strength=1.0, conditioning=("4", 0), style_model=("2", 0))
    g.prompt["7"]["inputs"]["positive"] = ["10", 0]
    assert g.extract(config).positive_prompt == "a red fox in the snow"


def test_unknown_node_without_text_or_cond_is_unresolved(config):
    g = basic_txt2img()
    g.node("10", "Mystery", x=1)
    g.prompt["7"]["inputs"]["positive"] = ["10", 0]
    e = g.extract(config)
    assert e.positive_prompt is None
    assert [(w.code, w.node_id) for w in e.warnings] == [(Code.PROMPT_UNRESOLVED, "10")]


def test_qwen_encoder_slot_map(config):
    g = basic_txt2img()
    del g.prompt["5"], g.prompt["6"]
    g.node(
        "4",
        "TextEncodeQwenImage21",
        prompt="make it a photo",
        negative_prompt="blur",
        resolution=1216,
        clip=("2", 0),
    )
    g.prompt["7"]["inputs"].update(positive=["4", 0], negative=["4", 1], latent_image=["4", 2])
    e = g.extract(config)
    assert (e.positive_prompt, e.negative_prompt) == ("make it a photo", "blur")
    assert e.latent_source == "TextEncodeQwenImage21"
    assert e.warnings == []


def test_clip_text_encode_flux_guidance_is_a_fallback(config):
    g = basic_txt2img()
    g.node("4", "CLIPTextEncodeFlux", clip_l="fox", t5xxl="a red fox", guidance=4.0, clip=("2", 0))
    e = g.extract(config)
    assert (e.positive_prompt, e.guidance) == ("a red fox", 4.0)

    g.node("10", "FluxGuidance", guidance=2.5, conditioning=("4", 0))
    g.prompt["7"]["inputs"]["positive"] = ["10", 0]
    assert g.extract(config).guidance == 2.5


def test_prompt_is_stored_exactly(config):
    g = basic_txt2img()
    g.prompt["4"]["inputs"]["text"] = "  line one\r\nline two\n\n\n"
    assert g.extract(config).positive_prompt == "  line one\r\nline two\n\n\n"
