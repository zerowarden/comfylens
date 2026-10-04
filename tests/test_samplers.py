from graph_builder import GraphBuilder, basic_txt2img

from comfylens.warn import Code


def test_ksampler(config):
    e = basic_txt2img().extract(config)
    (stage,) = e.stages
    assert (stage.index, stage.node_id, stage.class_type) == (0, "7", "KSampler")
    assert (stage.seed, stage.steps, stage.cfg, stage.denoise) == (42, 20, 3.5, 1.0)
    assert (stage.sampler_name, stage.scheduler) == ("euler", "simple")
    assert (stage.start_step, stage.end_step) == (None, None)


def test_ksampler_advanced(config):
    g = basic_txt2img()
    g.node(
        "7",
        "KSamplerAdvanced",
        add_noise="enable",
        noise_seed=7,
        steps=30,
        cfg=4,
        sampler_name="dpmpp_2m",
        scheduler="karras",
        start_at_step=0,
        end_at_step=10000,
        return_with_leftover_noise="disable",
        model=("1", 0),
        positive=("4", 0),
        negative=("5", 0),
        latent_image=("6", 0),
    )
    stage = g.extract(config).stages[0]
    assert (stage.seed, stage.steps, stage.cfg, stage.denoise) == (7, 30, 4.0, None)
    assert (stage.sampler_name, stage.scheduler) == ("dpmpp_2m", "karras")
    assert (stage.start_step, stage.end_step) == (0, 10000)


def custom_advanced(*, sampler_class="KSamplerSelect", sigmas_class="BasicScheduler"):
    g = basic_txt2img()
    del g.prompt["7"]
    g.node("10", "RandomNoise", noise_seed=123)
    g.node("11", "CFGGuider", cfg=2.5, model=("1", 0), positive=("4", 0), negative=("5", 0))
    g.node("12", sampler_class, sampler_name="res_2s", eta=0.5)
    g.node("13", sigmas_class, scheduler="beta", steps=28, denoise=0.9, model=("1", 0))
    g.node(
        "7",
        "SamplerCustomAdvanced",
        noise=("10", 0),
        guider=("11", 0),
        sampler=("12", 0),
        sigmas=("13", 0),
        latent_image=("6", 0),
    )
    return g


def test_sampler_custom_advanced_resolves_satellites(config):
    e = custom_advanced().extract(config)
    stage = e.stages[0]
    assert (stage.seed, stage.cfg, stage.sampler_name) == (123, 2.5, "res_2s")
    assert (stage.scheduler, stage.steps, stage.denoise) == ("beta", 28, 0.9)
    assert e.base_model == "flux1-dev"
    assert (e.positive_prompt, e.negative_prompt) == ("a red fox in the snow", "blurry")
    assert e.latent_source == "EmptyLatentImage"


def test_unregistered_satellites_fall_back_to_class_names(config):
    g = custom_advanced(sampler_class="SamplerEulerAncestral", sigmas_class="AlignYourSteps")
    stage = g.extract(config).stages[0]
    assert (stage.sampler_name, stage.scheduler, stage.steps) == (
        "SamplerEulerAncestral",
        "AlignYourSteps",
        28,
    )
    assert stage.denoise is None


def test_disable_noise_gives_no_seed(config):
    g = custom_advanced()
    g.node("10", "DisableNoise")
    assert g.extract(config).stages[0].seed is None


def test_basic_and_dual_cfg_guiders(config):
    g = custom_advanced()
    g.node("11", "BasicGuider", model=("1", 0), conditioning=("4", 0))
    e = g.extract(config)
    assert (e.stages[0].cfg, e.positive_prompt, e.negative_prompt) == (
        None,
        "a red fox in the snow",
        None,
    )

    g.node("14", "CLIPTextEncode", text="second positive", clip=("2", 0))
    g.node(
        "11",
        "DualCFGGuider",
        cfg_conds=5.0,
        cfg_cond2_negative=2.0,
        style="regular",
        model=("1", 0),
        cond1=("4", 0),
        cond2=("14", 0),
        negative=("5", 0),
    )
    e = g.extract(config)
    assert e.stages[0].cfg == 5.0
    # Joined in topological order, ties broken by id string ("14" < "4"), not input order.
    assert e.positive_prompt == "second positive\n\na red fox in the snow"
    assert Code.MULTIPLE_PROMPT_SOURCES in [w.code for w in e.warnings]


def test_two_stage_hires_ordering(config):
    g = basic_txt2img()
    g.node("15", "LatentUpscaleBy", upscale_method="nearest-exact", scale_by=1.5, samples=("7", 0))
    g.node(
        "16",
        "KSampler",
        seed=99,
        steps=12,
        cfg=3.5,
        sampler_name="euler",
        scheduler="normal",
        denoise=0.45,
        model=("1", 0),
        positive=("4", 0),
        negative=("5", 0),
        latent_image=("15", 0),
    )
    g.node("8", "VAEDecode", samples=("16", 0), vae=("3", 0))
    e = g.extract(config)
    assert [(s.index, s.node_id, s.denoise) for s in e.stages] == [(0, "7", 1.0), (1, "16", 0.45)]
    assert e.primary is not None and e.primary.node_id == "7"
    assert e.latent_source == "EmptyLatentImage"  # from the primary stage


def test_seed_through_a_primitive_node(config):
    g = basic_txt2img()
    g.node("30", "PrimitiveInt", value=2**63)
    g.prompt["7"]["inputs"]["seed"] = ["30", 0]
    assert g.extract(config).stages[0].seed == 2**63


def test_a_number_literal_on_a_computed_node_is_not_a_constant(config):
    # One numeric literal among a computed node's inputs must not be read as its output.
    g = basic_txt2img()
    g.node("30", "MathOp", a=1.5, op="sin")
    g.prompt["7"]["inputs"]["seed"] = ["30", 0]
    assert g.extract(config).stages[0].seed is None


def test_no_sampler_is_informational(config):
    g = GraphBuilder()
    g.node("1", "IdeogramV4", prompt="a poster", aspect_ratio="1:1", seed=5)
    g.node("2", "SaveImage", images=("1", 0))
    e = g.extract(config)
    assert e.stages == []
    assert [w.code for w in e.warnings] == [Code.NO_SAMPLER]
    assert e.model_family == "ideogram"
    assert {(i.input_name, i.value) for i in e.generic_inputs} >= {("aspect_ratio", "1:1")}
