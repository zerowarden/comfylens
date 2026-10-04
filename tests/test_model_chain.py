from graph_builder import basic_txt2img

from comfylens.warn import Code


def with_chain(*nodes: tuple[str, str, dict]):
    """basic_txt2img with nodes inserted between the UNET loader (1) and the sampler (7)."""
    g = basic_txt2img()
    upstream = "1"
    for node_id, class_type, inputs in nodes:
        g.node(node_id, class_type, inputs=inputs, model=(upstream, 0))
        upstream = node_id
    g.prompt["7"]["inputs"]["model"] = [upstream, 0]
    return g


def test_lora_order_from_the_base_model_outward(config):
    g = with_chain(
        ("20", "LoraLoaderModelOnly", {"lora_name": "a.safetensors", "strength_model": 0.8}),
        ("21", "LoraLoaderModelOnly", {"lora_name": "sub/b.safetensors", "strength_model": 1}),
    )
    e = g.extract(config)
    assert [(u.position, u.node_id, u.name, u.strength_model) for u in e.loras] == [
        (0, "20", "a", 0.8),
        (1, "21", "b", 1.0),
    ]
    assert e.lora_stack_key == "a@0.8 + b@1.0"
    assert e.base_model == "flux1-dev"


def test_lora_loader_clip_strength(config):
    g = with_chain(
        (
            "20",
            "LoraLoader",
            {
                "lora_name": "style_2025.safetensors",
                "strength_model": 0.7,
                "strength_clip": 0.3,
                "clip": ["2", 0],
            },
        ),
    )
    (use,) = g.extract(config).loras
    assert (use.strength_model, use.strength_clip) == (0.7, 0.3)
    assert (use.base_name, use.step) == ("style_2025", None)


def test_power_lora_loader_with_one_entry_off(config):
    power = {
        "PowerLoraLoaderHeaderWidget": {"type": "PowerLoraLoaderHeaderWidget"},
        "lora_1": {"on": True, "lora": "one.safetensors", "strength": 0.5},
        "lora_2": {"on": False, "lora": "two.safetensors", "strength": 1.0},
        "lora_3": {"on": True, "lora": "three.safetensors", "strength": 0.9, "strengthTwo": 0.4},
        "lora_4": {"on": True, "lora": "None", "strength": 1.0},
        "➕ Add Lora": "",  # noqa: RUF001 (rgthree's real key)
    }
    g = with_chain(
        ("20", "LoraLoaderModelOnly", {"lora_name": "first.safetensors", "strength_model": 1}),
        ("21", "Power Lora Loader (rgthree)", power),
    )
    e = g.extract(config)
    assert [(u.position, u.entry, u.name, u.enabled, u.strength_clip) for u in e.loras] == [
        (0, "", "first", True, None),
        (1, "lora_1", "one", True, 0.5),
        (None, "lora_2", "two", False, 1.0),
        (2, "lora_3", "three", True, 0.4),
    ]
    assert e.lora_stack_key == "first@1.0 + one@0.5 + three@0.9"
    assert all(u.reachable for u in e.loras)


def test_model_sampling_shift(config):
    g = with_chain(
        ("20", "ModelSamplingAuraFlow", {"shift": 3.1}),
        ("21", "LoraLoaderModelOnly", {"lora_name": "a.safetensors", "strength_model": 1}),
    )
    e = g.extract(config)
    assert e.shift == 3.1
    assert e.warnings == []


def test_model_sampling_flux_is_generic_only(config):
    g = with_chain(("20", "ModelSamplingFlux", {"max_shift": 1.15, "base_shift": 0.5}))
    e = g.extract(config)
    assert e.shift is None
    assert e.warnings == []
    assert ("max_shift", 1.15) in {(i.input_name, i.value) for i in e.generic_inputs}


def test_unknown_patch_with_model_input_is_followed(config):
    g = with_chain(
        ("20", "LoraLoaderModelOnly", {"lora_name": "a.safetensors", "strength_model": 1}),
        ("21", "TeaCache", {"rel_l1_thresh": 0.4}),
    )
    e = g.extract(config)
    assert e.base_model == "flux1-dev"
    assert [u.name for u in e.loras] == ["a"]
    assert [(w.code, w.node_id) for w in e.warnings] == [(Code.UNKNOWN_MODEL_PATCH, "21")]


def test_broken_chain(config):
    g = basic_txt2img()
    g.node("20", "SomeModelSource", path="x")
    g.prompt["7"]["inputs"]["model"] = ["20", 0]
    e = g.extract(config)
    assert e.base_model is None
    assert e.model_family == "flux"  # still matched through clip_type
    assert [(w.code, w.node_id) for w in e.warnings] == [(Code.MODEL_CHAIN_BROKEN, "20")]


def test_unused_lora_is_kept_with_warning(config):
    g = with_chain(
        ("20", "LoraLoaderModelOnly", {"lora_name": "used.safetensors", "strength_model": 1}),
    )
    g.node(
        "25",
        "LoraLoaderModelOnly",
        lora_name="dead_000004956.safetensors",
        strength_model=0.97,
        model=("20", 0),
    )
    e = g.extract(config)
    unused = e.loras[-1]
    assert (unused.node_id, unused.position, unused.reachable) == ("25", None, False)
    assert (unused.base_name, unused.step) == ("dead", 4956)
    assert e.lora_stack_key == "used@1.0"
    assert [(w.code, w.node_id) for w in e.warnings] == [(Code.UNUSED_LORA, "25")]


def test_no_loras(config):
    assert basic_txt2img().extract(config).lora_stack_key == "(none)"
