"""Bytes -> RawMetadata -> Graph -> Extraction, with per-stage error capture."""

from dataclasses import dataclass, field, replace
from typing import Any

from comfylens.config import Config
from comfylens.extract import components, strings
from comfylens.extract.conditioning import SideTrace, generated_warnings, trace_side
from comfylens.extract.family import UNKNOWN, match_family
from comfylens.extract.keys import (
    CHAIN_SEPARATOR,
    NO_LORAS,
    config_key,
    generation_key,
    lora_stack_key,
)
from comfylens.extract.loras import collect_loras
from comfylens.extract.model_chain import ModelChain, trace_model
from comfylens.extract.normalize import model_stem
from comfylens.extract.registry import REGISTRY, SAMPLER_CLASSES, SWITCHES, Role
from comfylens.extract.samplers import StageTrace, stage_nodes, trace_stages
from comfylens.extract.switches import inactive_inputs
from comfylens.extract.types import Extraction, LoraUse, SamplerStage
from comfylens.extract.values import as_str
from comfylens.graph import Graph, GraphCycle, Reachability, analyze_reachability, parse_graph
from comfylens.metadata import RawMetadata, Status, read_metadata
from comfylens.warn import Code, Warn


@dataclass(slots=True)
class Outcome:
    """Extraction from an API prompt. Parts after a failed stage are None."""

    status: Status  # ok, or error
    error: str | None = None  # "<exception type>: <message>" when status is error
    graph: Graph | None = None
    reach: Reachability | None = None
    extraction: Extraction | None = None
    warnings: list[Warn] = field(default_factory=list)  # extraction stage only


def extract_outcome(api_prompt: dict[str, Any], config: Config) -> Outcome:
    """Never raises: a cycle or any other failure becomes status `error`."""
    out = Outcome("ok")
    try:
        out.graph = parse_graph(api_prompt)
        out.reach = analyze_reachability(
            out.graph,
            config.graph.output_classes,
            config.graph.output_name_regex,
            SAMPLER_CLASSES,
            inactive_inputs(out.graph, SWITCHES),
        )
        out.extraction = extract(out.graph, out.reach, api_prompt, config)
    except GraphCycle as e:
        out.status, out.error = "error", f"GRAPH_CYCLE: {e}"
        out.warnings.append(Warn(Code.GRAPH_CYCLE, None, str(e)))
    except Exception as e:
        out.status, out.error = "error", describe(e)
        out.warnings = list(out.reach.warnings) if out.reach else []
    else:
        out.warnings = out.extraction.warnings
    return out


@dataclass(slots=True)
class Analysis:
    """Everything known about one file's bytes. Parts after a failed stage are None."""

    status: Status
    error: str | None = None
    raw: RawMetadata | None = None
    graph: Graph | None = None
    reach: Reachability | None = None
    extraction: Extraction | None = None
    warnings: list[Warn] = field(default_factory=list)


def analyze(data: bytes | memoryview, config: Config) -> Analysis:
    """Read and extract one file. Never raises: failures become status `error`."""
    try:
        raw = read_metadata(data)
    except Exception as e:
        return Analysis("error", describe(e))
    if raw.api_prompt is None:
        return Analysis(raw.status, raw=raw, warnings=list(raw.warnings))
    out = extract_outcome(raw.api_prompt, config)
    return Analysis(
        out.status,
        out.error,
        raw,
        out.graph,
        out.reach,
        out.extraction,
        raw.warnings + out.warnings,
    )


def describe(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"


def extract(
    graph: Graph, reach: Reachability, api_prompt: dict[str, Any], config: Config
) -> Extraction:
    warnings = list(reach.warnings)
    decimals = config.analysis.config_round_decimals

    traces = trace_stages(graph, reach)
    if not traces:
        warnings.append(Warn(Code.NO_SAMPLER, None, "no reachable sampler node"))

    chains = [trace_model(graph, t.first("model"), t.stage.node_id) for t in traces]
    for chain in chains:
        warnings += chain.warnings
    loras, lora_warnings = collect_loras(graph, chains, config.lora.step_suffix_regex)
    warnings += lora_warnings

    stages: list[SamplerStage] = []
    encoders: list[list[str]] = []  # text encoder stems, per stage
    for trace, chain in zip(traces, chains, strict=True):
        index = trace.stage.index
        identity = _identity(
            graph,
            reach,
            trace,
            chain,
            config,
            stage_nodes(graph, trace.stage.node_id),
            [u for u in loras if u.stage_index == index],
        )
        warnings += identity.warnings
        encoders.append(identity.text_encoders)
        stages.append(replace(trace.stage, **identity.fields))
    primary = stages[0] if stages else None

    if primary is None:
        generator = _generator_prompt(graph, reach)
        warnings += generator.warnings if generator else []
        positive = generator.prompt if generator else None
        family = match_family(
            config.families,
            loader_kind=None,
            loader_name=None,
            clip_type=None,
            class_types={graph.nodes[n].class_type for n in reach.reachable},
        )
    else:
        positive = primary.positive_prompt
        family = _pipeline_family(graph, reach, stages, chains[0], config)
    latent_source, batch_size = components.latent(graph, traces[0] if traces else None)

    stack_key = primary.lora_stack_key if primary else NO_LORAS
    base_model = primary.base_model if primary else None
    guidance = primary.guidance if primary else None
    shift = primary.shift if primary else None
    return Extraction(
        stages=stages,
        model_family=family,
        base_model=base_model,
        text_encoders=encoders[0] if encoders else [],
        clip_type=primary.clip_type if primary else None,
        vae=components.vae(graph, reach),
        loras=loras,
        positive_prompt=positive,
        negative_prompt=primary.negative_prompt if primary else None,
        guidance=guidance,
        shift=shift,
        latent_source=latent_source,
        batch_size=batch_size,
        input_images=components.input_images(graph, reach),
        lora_stack_key=stack_key,
        config_key=config_key(family, base_model, stack_key, primary, guidance, shift, decimals),
        generation_key=generation_key(api_prompt),
        warnings=list(dict.fromkeys(warnings)),  # stages sharing a chain repeat its warnings
    )


@dataclass(slots=True)
class _Identity:
    fields: dict[str, Any]  # SamplerStage fields beyond the sampler's own
    text_encoders: list[str]
    warnings: list[Warn]


def _identity(
    graph: Graph,
    reach: Reachability,
    trace: StageTrace,
    chain: ModelChain,
    config: Config,
    nodes: set[str],
    loras: list[LoraUse],
) -> _Identity:
    """What one stage ran with: model, text encoder, LoRAs, prompts and guidance."""
    positive = trace_side(graph, reach, trace.links.get("positive", []))
    negative = trace_side(graph, reach, trace.links.get("negative", []))
    sides = (positive, negative)
    text_encoders, clip_type = components.text_encoders(
        graph, [e for side in sides for e in side.encoders]
    )
    loader_kind, loader_name = _loader(chain)
    family = match_family(
        config.families,
        loader_kind=loader_kind,
        loader_name=loader_name,
        clip_type=clip_type,
        class_types={graph.nodes[n].class_type for n in nodes},
    )
    latent_source, _batch_size = components.latent(graph, trace)
    fields: dict[str, Any] = {
        "model_family": family,
        "base_model": model_stem(loader_name) if loader_name else None,
        "text_encoder": " + ".join(text_encoders) or None,
        "clip_type": clip_type,
        "lora_stack_key": lora_stack_key(loras, config.analysis.config_round_decimals),
        "positive_prompt": positive.prompt,
        "negative_prompt": negative.prompt,
        "guidance": _first([s.guidance for s in sides] + [s.encoder_guidance for s in sides]),
        "shift": chain.shift,
        "latent_source": latent_source,
    }
    return _Identity(fields, text_encoders, positive.warnings + negative.warnings)


def _loader(chain: ModelChain) -> tuple[str | None, str | None]:
    """The base model loader's kind ("unet" or "ckpt") and file name, if the chain has one."""
    if chain.loader is None:
        return None, None
    entry = REGISTRY[chain.loader.class_type]
    return entry.kind, as_str(chain.loader.literal(entry.names[0]))


def _pipeline_family(
    graph: Graph,
    reach: Reachability,
    stages: list[SamplerStage],
    primary_chain: ModelChain,
    config: Config,
) -> str:
    """Stage families in order, repeats in a row collapsed: "krea-2 + qwen-image-2.1".

    When no stage is recognized, the whole graph is matched instead, so a family marked
    only by a node outside every stage (an upstream image generator) is still found.
    """
    families = [s.model_family for s in stages]
    if all(f == UNKNOWN for f in families):
        loader_kind, loader_name = _loader(primary_chain)
        return match_family(
            config.families,
            loader_kind=loader_kind,
            loader_name=loader_name,
            clip_type=stages[0].clip_type,
            class_types={graph.nodes[n].class_type for n in reach.reachable},
        )
    collapsed = [f for i, f in enumerate(families) if i == 0 or f != families[i - 1]]
    return CHAIN_SEPARATOR.join(collapsed)


def _generator_prompt(graph: Graph, reach: Reachability) -> SideTrace | None:
    """Without a sampler, the prompt of a node that makes the image itself (a hosted API)."""
    generators = [
        (node, entry)
        for node_id in reach.order
        if (entry := REGISTRY.get((node := graph.nodes[node_id]).class_type))
        and entry.role is Role.GENERATOR
    ]
    if not generators:
        return None
    side = SideTrace()
    texts = []
    for node, entry in generators:
        generated: list[str] = []
        text = strings.resolve(graph, node.inputs.get(entry.fields["prompt"]), generated=generated)
        side.warnings += generated_warnings(graph, generated)
        if text is None:
            side.warnings.append(Warn(Code.PROMPT_UNRESOLVED, node.id, "no prompt text"))
        elif text.strip():
            texts.append(text)
    if len(texts) > 1:
        message = f"{len(texts)} prompt sources joined"
        side.warnings.append(Warn(Code.MULTIPLE_PROMPT_SOURCES, None, message))
    side.prompt = "\n\n".join(texts) if texts else None
    return side


def _first[T](values: list[T | None]) -> T | None:
    return next((v for v in values if v is not None), None)
