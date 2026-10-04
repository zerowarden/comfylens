"""Build API prompts compactly: `g.node("5", "KSampler", seed=1, model=("4", 0))`.

A tuple (node id, slot) becomes a link; every other value is a literal. Inputs whose names
are not identifiers ("images.image_1", "lora_1" dicts are fine) go in `inputs=`.
"""

from typing import Any

from comfylens.config import Config
from comfylens.extract.pipeline import extract_outcome
from comfylens.extract.types import Extraction
from comfylens.graph.model import Graph
from comfylens.graph.reachability import Reachability


class GraphBuilder:
    def __init__(self) -> None:
        self.prompt: dict[str, Any] = {}

    def node(
        self,
        node_id: str,
        class_type: str,
        *,
        inputs: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> GraphBuilder:
        values = {**(inputs or {}), **kwargs}
        self.prompt[node_id] = {
            "inputs": {k: list(v) if isinstance(v, tuple) else v for k, v in values.items()},
            "class_type": class_type,
            "_meta": {"title": class_type},
            **(extra or {}),
        }
        return self

    def extract(self, config: Config) -> Extraction:
        return self.run(config)[2]

    def run(self, config: Config) -> tuple[Graph, Reachability, Extraction]:
        out = extract_outcome(self.prompt, config)
        assert out.graph is not None and out.reach is not None and out.extraction is not None, (
            out.error
        )
        return out.graph, out.reach, out.extraction


def basic_txt2img(g: GraphBuilder | None = None) -> GraphBuilder:
    """UNET -> KSampler <- two CLIPTextEncode, EmptyLatentImage; VAEDecode -> SaveImage."""
    return (
        (g or GraphBuilder())
        .node("1", "UNETLoader", unet_name="flux1-dev.safetensors", weight_dtype="default")
        .node("2", "CLIPLoader", clip_name="t5xxl.safetensors", type="flux")
        .node("3", "VAELoader", vae_name="ae.safetensors")
        .node("4", "CLIPTextEncode", text="a red fox in the snow", clip=("2", 0))
        .node("5", "CLIPTextEncode", text="blurry", clip=("2", 0))
        .node("6", "EmptyLatentImage", width=1024, height=1024, batch_size=4)
        .node(
            "7",
            "KSampler",
            seed=42,
            steps=20,
            cfg=3.5,
            sampler_name="euler",
            scheduler="simple",
            denoise=1.0,
            model=("1", 0),
            positive=("4", 0),
            negative=("5", 0),
            latent_image=("6", 0),
        )
        .node("8", "VAEDecode", samples=("7", 0), vae=("3", 0))
        .node("9", "SaveImage", images=("8", 0), filename_prefix="ComfyUI")
    )


KREA2_SYSTEM = "You are an expert prompt engineer for text-to-image models. Rewrite the idea."


def krea2_turbo(
    *,
    prompt: str = "a red fox in the snow",
    enhance: bool = False,
    lora: bool = False,
    style: str = "muted minimalist sketch style",
    seed: int = 594361197674106,
) -> GraphBuilder:
    """The API prompt of ComfyUI's "Text to Image (Krea-2 Turbo)" template (subgraph 30).

    `enhance` routes the prompt through TextGenerate (an LLM rewrite); `lora` switches the
    LoRA into the model chain and appends the style suffix to the prompt.
    """
    s = "30:"
    g = GraphBuilder()
    g.node("49", "ResolutionSelector", aspect_ratio="1:1 (Square)", megapixels=1, multiple=8)
    g.node(
        s + "10",
        "UNETLoader",
        unet_name="krea2_turbo_fp8_scaled.safetensors",
        weight_dtype="default",
    )
    g.node(
        s + "11",
        "CLIPLoader",
        clip_name="qwen3vl_4b_fp8_scaled.safetensors",
        type="krea2",
        device="default",
    )
    g.node(s + "12", "VAELoader", vae_name="qwen_image_vae.safetensors")
    g.node(
        s + "15",
        "LoraLoaderModelOnly",
        lora_name="krea2_darkbrush.safetensors",
        strength_model=0.8,
        model=(s + "10", 0),
    )
    g.node(s + "23", "PrimitiveBoolean", value=lora)
    g.node(s + "24", "PrimitiveBoolean", value=enhance)
    g.node(
        s + "22",
        "ComfySwitchNode",
        switch=(s + "23", 0),
        on_false=(s + "10", 0),
        on_true=(s + "15", 0),
    )
    g.node(s + "18", "PrimitiveStringMultiline", value=KREA2_SYSTEM)
    g.node(s + "19", "PrimitiveStringMultiline", value=prompt)
    g.node(
        s + "17", "StringConcatenate", string_a=(s + "18", 0), string_b=(s + "19", 0), delimiter=" "
    )
    g.node(
        s + "16",
        "TextGenerate",
        inputs={"sampling_mode": "on", "sampling_mode.temperature": 0.7, "sampling_mode.top_k": 64},
        clip=(s + "11", 0),
        prompt=(s + "17", 0),
        max_length=512,
        thinking=False,
    )
    g.node(
        s + "21",
        "ComfySwitchNode",
        switch=(s + "24", 0),
        on_false=(s + "19", 0),
        on_true=(s + "16", 0),
    )
    g.node(s + "20", "PreviewAny", source=(s + "21", 0))
    g.node(s + "27", "StringConcatenate", string_a=(s + "20", 0), string_b=style, delimiter=", ")
    g.node(
        s + "28",
        "ComfySwitchNode",
        switch=(s + "23", 0),
        on_false=(s + "20", 0),
        on_true=(s + "27", 0),
    )
    g.node(s + "6", "CLIPTextEncode", text=(s + "28", 0), clip=(s + "11", 0))
    g.node(s + "13", "ConditioningZeroOut", conditioning=(s + "6", 0))
    g.node(s + "5", "EmptyLatentImage", width=("49", 0), height=("49", 1), batch_size=1)
    g.node(
        s + "3",
        "KSampler",
        seed=seed,
        steps=8,
        cfg=1,
        sampler_name="euler",
        scheduler="simple",
        denoise=1,
        model=(s + "22", 0),
        positive=(s + "6", 0),
        negative=(s + "13", 0),
        latent_image=(s + "5", 0),
    )
    g.node(s + "8", "VAEDecode", samples=(s + "3", 0), vae=(s + "12", 0))
    g.node("29", "SaveImage", filename_prefix="Krea2_turbo", images=(s + "8", 0))
    return g  # fmt: skip


def krea2_api(prompt: str = "high fashion editorial close-up portrait", seed: int = 1981045336):
    """The API prompt of ComfyUI's api_krea2_t2i template: the image is made remotely."""
    return (
        GraphBuilder()
        .node(
            "1",
            "Krea2ImageNode",
            inputs={
                "model": "Krea 2 Medium",
                "model.aspect_ratio": "1:1",
                "model.resolution": "1K",
            },
            prompt=prompt,
            seed=seed,
        )
        .node("2", "SaveImage", images=("1", 0), filename_prefix="Krea2")
    )


REALISM_PROMPT = "make it a realistic photograph"


def krea2_qwen_realism(*, krea_lora: bool = True, denoise: float = 0.35) -> GraphBuilder:
    """Krea 2 Turbo, then a Qwen Image 2.1 realism pass on its decoded image, in one run.

    The Qwen encoder takes the Krea image as its reference and makes the latent from it, as
    in the golden graph; only the final image is saved.
    """
    g = krea2_turbo(lora=krea_lora)
    del g.prompt["29"]  # the Krea image goes on to the realism pass instead
    g.node(
        "101",
        "UNETLoader",
        unet_name="qwen_image_2.1_int8_convrot.safetensors",
        weight_dtype="default",
    )
    g.node(
        "102",
        "CLIPLoader",
        clip_name="qwen3vl_8b_int8_convrot.safetensors",
        type="qwen_image",
        device="default",
    )
    g.node("103", "VAELoader", vae_name="qwen_image_2.1_vae_bf16.safetensors")
    g.node(
        "111",
        "LoraLoaderModelOnly",
        lora_name="qwen2.1-lenovo-ultrareal.safetensors",
        strength_model=1.06,
        model=("101", 0),
    )
    g.node(
        "109",
        "TextEncodeQwenImage21",
        inputs={"images.image_1": ("30:8", 0)},
        prompt=REALISM_PROMPT,
        negative_prompt="plastic, blur",
        resolution=1216,
        clip=("102", 0),
        vae=("103", 0),
    )
    g.node(
        "106",
        "KSampler",
        seed=42,
        steps=25,
        cfg=2.0,
        sampler_name="euler",
        scheduler="simple",
        denoise=denoise,
        model=("111", 0),
        positive=("109", 0),
        negative=("109", 1),
        latent_image=("109", 2),
    )
    g.node("107", "VAEDecode", samples=("106", 0), vae=("103", 0))
    g.node("112", "SaveImage", filename_prefix="qwen_realism", images=("107", 0))
    return g  # fmt: skip
