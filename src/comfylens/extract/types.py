"""Results of semantic extraction."""

from dataclasses import dataclass
from typing import Literal

from comfylens.warn import Warn

GenericKind = Literal["num", "str", "bool", "json"]


@dataclass(slots=True)
class LoraUse:
    position: int | None  # in its stage's chain, 0 = nearest the base model; None if off
    stage_index: int | None  # the stage whose chain this is; None if on no chain
    node_id: str
    entry: str  # "" or "lora_N" for Power Lora Loader
    class_type: str
    name_raw: str  # as in the graph, e.g. "subdir/foo.safetensors"
    name: str  # name_raw without directory or model-file extension
    base_name: str  # name without a training-step suffix
    step: int | None
    strength_model: float | None
    strength_clip: float | None
    enabled: bool  # Power Lora Loader "on"; True otherwise
    reachable: bool  # on some sampler's model chain


@dataclass(slots=True)
class SamplerStage:
    index: int  # topological order among samplers; 0 = primary
    node_id: str
    class_type: str
    seed: int | None  # may be up to 2**64 - 1
    steps: int | None
    cfg: float | None
    sampler_name: str | None
    scheduler: str | None
    denoise: float | None
    start_step: int | None
    end_step: int | None
    # What this stage ran with, traced from its own inputs; the pipeline fills these in.
    model_family: str = "unknown"  # matched on this stage's nodes only
    base_model: str | None = None
    text_encoder: str | None = None  # clip file stems joined with " + "
    clip_type: str | None = None
    lora_stack_key: str = "(none)"
    positive_prompt: str | None = None
    negative_prompt: str | None = None
    guidance: float | None = None
    shift: float | None = None
    latent_source: str | None = None


@dataclass(slots=True)
class InputImage:
    node_id: str
    filename: str | None
    sha256: str | None


@dataclass(slots=True)
class GenericInput:
    node_id: str
    class_type: str
    input_name: str  # dict inputs flattened with dots: "lora_1.strength"
    kind: GenericKind
    value: bool | int | float | str  # json kind: serialized JSON
    reachable: bool


@dataclass(slots=True)
class Extraction:
    """Image-level fields are the primary stage's, except `model_family`, which names every
    stage's family in order: "krea-2 + qwen-image-2.1" for a pass through two models."""

    stages: list[SamplerStage]
    model_family: str
    base_model: str | None
    text_encoders: list[str]
    clip_type: str | None
    vae: str | None
    loras: list[LoraUse]  # each stage's chain in order, then unreachable
    positive_prompt: str | None
    negative_prompt: str | None
    guidance: float | None
    shift: float | None
    latent_source: str | None
    batch_size: int | None
    input_images: list[InputImage]
    generic_inputs: list[GenericInput]
    lora_stack_key: str
    config_key: str
    generation_key: str
    warnings: list[Warn]

    @property
    def text_encoder(self) -> str | None:
        return " + ".join(self.text_encoders) or None

    @property
    def primary(self) -> SamplerStage | None:
        return self.stages[0] if self.stages else None

    @property
    def stage_prompts(self) -> str | None:
        """Later stages' prompts that differ from the primary's, joined for prompt search."""
        seen = {self.positive_prompt, self.negative_prompt}
        found: list[str] = []
        for stage in self.stages[1:]:
            for text in (stage.positive_prompt, stage.negative_prompt):
                if text and text.strip() and text not in seen:
                    seen.add(text)
                    found.append(text)
        return "\n\n".join(found) or None
