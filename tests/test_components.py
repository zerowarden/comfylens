from graph_builder import basic_txt2img

SHA = "D22BC0FC91F29D00BF88AEFCA945C5BB16F6DE426DB9025788902C04E45AC099"


def test_text_encoder_through_lora_to_dual_clip_loader(config):
    g = basic_txt2img()
    g.node(
        "2",
        "DualCLIPLoader",
        clip_name1="clip_l.safetensors",
        clip_name2="t5/t5xxl_fp16.safetensors",
        type="flux",
    )
    g.node(
        "20",
        "LoraLoader",
        lora_name="x.safetensors",
        strength_model=1,
        strength_clip=1,
        model=("1", 0),
        clip=("2", 0),
    )
    g.node("21", "CLIPSetLastLayer", stop_at_clip_layer=-2, clip=("20", 1))
    g.prompt["4"]["inputs"]["clip"] = ["21", 0]
    g.prompt["5"]["inputs"]["clip"] = ["20", 1]
    g.prompt["7"]["inputs"]["model"] = ["20", 0]
    e = g.extract(config)
    assert e.text_encoders == ["clip_l", "t5xxl_fp16"]
    assert e.text_encoder == "clip_l + t5xxl_fp16"
    assert e.clip_type == "flux"


def test_checkpoint_is_model_text_encoder_and_vae(config):
    g = basic_txt2img()
    del g.prompt["2"], g.prompt["3"]
    g.node("1", "CheckpointLoaderSimple", ckpt_name="sdxl/juggernaut.safetensors")
    for encoder in ("4", "5"):
        g.prompt[encoder]["inputs"]["clip"] = ["1", 1]
    g.prompt["8"]["inputs"]["vae"] = ["1", 2]
    e = g.extract(config)
    assert (e.base_model, e.text_encoder, e.vae) == ("juggernaut", "juggernaut", "juggernaut")
    assert e.clip_type is None
    assert e.model_family == "unknown"


def test_vae_from_the_decode_feeding_the_output(config):
    g = basic_txt2img()
    g.node("30", "VAELoader", vae_name="other.safetensors")
    g.node("31", "VAEDecode", samples=("7", 0), vae=("30", 0))
    g.node("32", "SomethingElse", images=("31", 0))
    g.prompt["9"]["inputs"]["images"] = ["32", 0]
    g.prompt["8"]["inputs"]["vae"] = ["30", 0]
    assert g.extract(config).vae == "other"


def test_vae_falls_back_to_any_reachable_loader(config):
    g = basic_txt2img()
    g.node("8", "ImageDecodeCustom", samples=("7", 0), vae=("3", 0))
    assert g.extract(config).vae == "ae"


def test_img2img_latent_source(config):
    g = basic_txt2img()
    g.node("6", "VAEEncode", pixels=("40", 0), vae=("3", 0))
    g.node("40", "LoadImage", image="in.png", extra={"is_changed": [SHA]})
    e = g.extract(config)
    assert (e.latent_source, e.batch_size) == ("VAEEncode", None)
    (image,) = e.input_images
    assert (image.node_id, image.filename, image.sha256) == ("40", "in.png", SHA.lower())


def test_input_image_without_valid_hash(config):
    g = basic_txt2img()
    g.node("6", "VAEEncode", pixels=("40", 0), vae=("3", 0))
    g.node("40", "LoadImage", image="pasted-image.png", extra={"is_changed": ["not-a-hash"]})
    assert g.extract(config).input_images[0].sha256 is None


def test_vae_through_a_pass_through_node(config):
    g = basic_txt2img()
    del g.prompt["2"], g.prompt["3"]
    g.node("1", "CheckpointLoaderSimple", ckpt_name="aio.safetensors")
    g.node("30", "Context (rgthree)", model=("1", 0), clip=("1", 1), vae=("1", 2))
    for encoder in ("4", "5"):
        g.prompt[encoder]["inputs"]["clip"] = ["30", 2]
    g.prompt["7"]["inputs"]["model"] = ["30", 1]
    g.prompt["8"]["inputs"]["vae"] = ["30", 3]
    e = g.extract(config)
    assert (e.base_model, e.text_encoder, e.vae) == ("aio", "aio", "aio")
