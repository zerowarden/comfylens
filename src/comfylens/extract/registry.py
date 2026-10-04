"""class_type -> role and the inputs each role reads.

Register a class only when it affects a normalized field; the generic layer covers the rest.
Input names match ComfyUI core and rgthree-comfy.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from comfylens.graph.reachability import Switch

Kind = Literal["", "unet", "ckpt", "power", "soft"]


class Role(StrEnum):
    SAMPLER = "sampler"
    NOISE = "noise"
    GUIDER = "guider"
    SAMPLER_SELECT = "sampler_select"
    SIGMAS = "sigmas"
    MODEL_LOADER = "model_loader"
    LORA = "lora"
    MODEL_PATCH = "model_patch"
    CLIP_LOADER = "clip_loader"
    VAE_LOADER = "vae_loader"
    VAE_DECODE = "vae_decode"
    TEXT_ENCODER = "text_encoder"
    CONDITIONING_PASS = "conditioning_pass"
    CONDITIONING_ZERO = "conditioning_zero"
    LATENT_SOURCE = "latent_source"
    IMAGE_INPUT = "image_input"
    STRING_SOURCE = "string_source"
    PRIMITIVE = "primitive"  # a constant read through links: seeds, switch conditions
    SWITCH = "switch"
    STRING_PASS = "string_pass"  # passes the string on its input through (PreviewAny)
    TEXT_GENERATOR = "text_generator"  # writes text at run time from a prompt (an LLM)
    GENERATOR = "generator"  # makes the image itself, no sampler (hosted API nodes)


@dataclass(frozen=True)
class Entry:
    role: Role
    # Normalized field -> input name, e.g. {"seed": "noise_seed"}.
    fields: Mapping[str, str] = field(default_factory=dict)
    # Link role -> input names, e.g. {"positive": ("cond1", "cond2")}.
    links: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    # Loaders: file-name inputs. String sources: the parts joined by the `delimiter` field.
    names: tuple[str, ...] = ()
    # Text encoders: output slot -> text inputs, the first non-empty one wins.
    slots: Mapping[int, tuple[str, ...]] = field(default_factory=dict)
    # Model loaders: "unet" or "ckpt". LoRAs: "power" for rgthree's lora_N dict entries.
    # Switches: "soft" when an unconnected selected input falls back to the other one.
    kind: Kind = ""


_SAMPLER_LINKS = {
    "model": ("model",),
    "positive": ("positive",),
    "negative": ("negative",),
    "latent": ("latent_image",),
}
_KSAMPLER_FIELDS = {
    "steps": "steps",
    "cfg": "cfg",
    "sampler_name": "sampler_name",
    "scheduler": "scheduler",
}
_SWITCH_FIELDS = {"condition": "switch", "on_true": "on_true", "on_false": "on_false"}
_SET_AREA = (
    "ConditioningSetArea",
    "ConditioningSetAreaPercentage",
    "ConditioningSetAreaStrength",
    "ConditioningSetAreaPercentageVideo",
)

REGISTRY: dict[str, Entry] = {
    # Samplers. SamplerCustom* resolve the noise / guider / sampler / sigmas satellites.
    "KSampler": Entry(
        Role.SAMPLER,
        {"seed": "seed", **_KSAMPLER_FIELDS, "denoise": "denoise"},
        _SAMPLER_LINKS,
    ),
    "KSamplerAdvanced": Entry(
        Role.SAMPLER,
        {
            "seed": "noise_seed",
            **_KSAMPLER_FIELDS,
            "start_step": "start_at_step",
            "end_step": "end_at_step",
        },
        _SAMPLER_LINKS,
    ),
    "SamplerCustom": Entry(
        Role.SAMPLER,
        {"seed": "noise_seed", "cfg": "cfg"},
        {**_SAMPLER_LINKS, "sampler": ("sampler",), "sigmas": ("sigmas",)},
    ),
    "SamplerCustomAdvanced": Entry(
        Role.SAMPLER,
        links={
            "noise": ("noise",),
            "guider": ("guider",),
            "sampler": ("sampler",),
            "sigmas": ("sigmas",),
            "latent": ("latent_image",),
        },
    ),
    "RandomNoise": Entry(Role.NOISE, {"seed": "noise_seed"}),
    "DisableNoise": Entry(Role.NOISE),
    "CFGGuider": Entry(
        Role.GUIDER,
        {"cfg": "cfg"},
        {"model": ("model",), "positive": ("positive",), "negative": ("negative",)},
    ),
    "BasicGuider": Entry(Role.GUIDER, links={"model": ("model",), "positive": ("conditioning",)}),
    "DualCFGGuider": Entry(
        Role.GUIDER,
        {"cfg": "cfg_conds"},
        {"model": ("model",), "positive": ("cond1", "cond2"), "negative": ("negative",)},
    ),
    "KSamplerSelect": Entry(Role.SAMPLER_SELECT, {"sampler_name": "sampler_name"}),
    "BasicScheduler": Entry(
        Role.SIGMAS, {"scheduler": "scheduler", "steps": "steps", "denoise": "denoise"}
    ),
    # Model chain.
    "UNETLoader": Entry(Role.MODEL_LOADER, names=("unet_name",), kind="unet"),
    "UnetLoaderGGUF": Entry(Role.MODEL_LOADER, names=("unet_name",), kind="unet"),
    "CheckpointLoaderSimple": Entry(Role.MODEL_LOADER, names=("ckpt_name",), kind="ckpt"),
    "LoraLoaderModelOnly": Entry(
        Role.LORA, {"name": "lora_name", "strength_model": "strength_model"}
    ),
    "LoraLoader": Entry(
        Role.LORA,
        {"name": "lora_name", "strength_model": "strength_model", "strength_clip": "strength_clip"},
    ),
    "Power Lora Loader (rgthree)": Entry(Role.LORA, kind="power"),
    "ModelSamplingAuraFlow": Entry(Role.MODEL_PATCH, {"shift": "shift"}),
    "ModelSamplingSD3": Entry(Role.MODEL_PATCH, {"shift": "shift"}),
    "ModelSamplingFlux": Entry(Role.MODEL_PATCH),
    # Text encoders and VAE.
    "CLIPLoader": Entry(Role.CLIP_LOADER, {"clip_type": "type"}, names=("clip_name",)),
    "DualCLIPLoader": Entry(
        Role.CLIP_LOADER, {"clip_type": "type"}, names=("clip_name1", "clip_name2")
    ),
    "TripleCLIPLoader": Entry(Role.CLIP_LOADER, names=("clip_name1", "clip_name2", "clip_name3")),
    "VAELoader": Entry(Role.VAE_LOADER, names=("vae_name",)),
    "VAEDecode": Entry(Role.VAE_DECODE),
    "VAEDecodeTiled": Entry(Role.VAE_DECODE),
    # Conditioning.
    "CLIPTextEncode": Entry(Role.TEXT_ENCODER, slots={0: ("text",)}),
    "CLIPTextEncodeFlux": Entry(
        Role.TEXT_ENCODER, {"guidance": "guidance"}, slots={0: ("t5xxl", "clip_l")}
    ),
    # Slot 2 of TextEncodeQwenImage21 is a latent, not conditioning.
    "TextEncodeQwenImage21": Entry(
        Role.TEXT_ENCODER, slots={0: ("prompt",), 1: ("negative_prompt",)}
    ),
    "TextEncodeQwenImageEdit": Entry(Role.TEXT_ENCODER, slots={0: ("prompt",)}),
    "TextEncodeQwenImageEditPlus": Entry(Role.TEXT_ENCODER, slots={0: ("prompt",)}),
    "FluxGuidance": Entry(Role.CONDITIONING_PASS, {"guidance": "guidance"}),
    "ConditioningZeroOut": Entry(Role.CONDITIONING_ZERO),
    "ConditioningCombine": Entry(Role.CONDITIONING_PASS),
    "ConditioningConcat": Entry(Role.CONDITIONING_PASS),
    "ConditioningSetTimestepRange": Entry(Role.CONDITIONING_PASS),
    **{name: Entry(Role.CONDITIONING_PASS) for name in _SET_AREA},
    "ReferenceLatent": Entry(Role.CONDITIONING_PASS),
    # Latents and inputs.
    "EmptyLatentImage": Entry(Role.LATENT_SOURCE, {"batch_size": "batch_size"}),
    "EmptySD3LatentImage": Entry(Role.LATENT_SOURCE, {"batch_size": "batch_size"}),
    "VAEEncode": Entry(Role.LATENT_SOURCE),
    "VAEEncodeForInpaint": Entry(Role.LATENT_SOURCE),
    "LoadImage": Entry(Role.IMAGE_INPUT, {"filename": "image"}),
    "PrimitiveString": Entry(Role.STRING_SOURCE, names=("value",)),
    "PrimitiveStringMultiline": Entry(Role.STRING_SOURCE, names=("value",)),
    "StringConcatenate": Entry(
        Role.STRING_SOURCE, {"delimiter": "delimiter"}, names=("string_a", "string_b")
    ),
    "PrimitiveBoolean": Entry(Role.PRIMITIVE),
    "PrimitiveInt": Entry(Role.PRIMITIVE),
    "PrimitiveFloat": Entry(Role.PRIMITIVE),
    # Lazy switches: only the selected branch executes (ComfyUI core, comfyui-easy-use).
    "ComfySwitchNode": Entry(Role.SWITCH, _SWITCH_FIELDS),
    "ComfySoftSwitchNode": Entry(Role.SWITCH, _SWITCH_FIELDS, kind="soft"),
    "easy ifElse": Entry(Role.SWITCH, {**_SWITCH_FIELDS, "condition": "boolean"}),
    # Krea 2: the prompt passes through PreviewAny, may be rewritten by TextGenerate, and
    # Krea2ImageNode generates the image remotely.
    "PreviewAny": Entry(Role.STRING_PASS, names=("source",)),
    "TextGenerate": Entry(Role.TEXT_GENERATOR, names=("prompt",)),
    "Krea2ImageNode": Entry(Role.GENERATOR, {"prompt": "prompt"}),
}

SAMPLER_CLASSES = frozenset(k for k, e in REGISTRY.items() if e.role is Role.SAMPLER)
SWITCHES = {
    k: Switch(e.fields["condition"], e.fields["on_true"], e.fields["on_false"], e.kind == "soft")
    for k, e in REGISTRY.items()
    if e.role is Role.SWITCH
}


def role_of(class_type: str) -> Role | None:
    entry = REGISTRY.get(class_type)
    return entry.role if entry else None


def unregistered(class_types: Collection[str], output_classes: Collection[str]) -> list[str]:
    """Classes with no registry entry, excluding output classes."""
    return sorted({c for c in class_types if c not in REGISTRY and c not in output_classes})
