"""LoRA uses, on and off the model chains."""

import re
from collections.abc import Sequence
from typing import Any

from comfylens.extract.model_chain import ModelChain
from comfylens.extract.normalize import lora_base_step, model_stem
from comfylens.extract.registry import REGISTRY, Role, role_of
from comfylens.extract.types import LoraUse
from comfylens.extract.values import as_float, read_float, read_str
from comfylens.graph import Graph, Node
from comfylens.warn import Code, Warn


def collect_loras(
    graph: Graph, chains: Sequence[ModelChain], step_suffix: re.Pattern[str]
) -> tuple[list[LoraUse], list[Warn]]:
    """Each stage's LoRAs in chain order, then every LoRA node on no stage's chain.

    `chains[i]` is stage i's. A LoRA on several stages' chains (a hires fix sharing one
    model) is listed once per stage. Positions count enabled entries from the stage's base
    model outward.
    """
    uses: list[LoraUse] = []
    for stage_index, chain in enumerate(chains):
        position = 0
        for node_id in chain.lora_nodes:
            for use in _uses(graph, graph.nodes[node_id], step_suffix, stage_index):
                if use.enabled:
                    use.position = position
                    position += 1
                uses.append(use)

    on_chain = {node_id for chain in chains for node_id in chain.lora_nodes}
    warnings: list[Warn] = []
    for node in graph.nodes.values():
        if role_of(node.class_type) is Role.LORA and node.id not in on_chain:
            uses += _uses(graph, node, step_suffix, None)
            warnings.append(
                Warn(Code.UNUSED_LORA, node.id, "LoRA loaded but not connected to any sampler")
            )
    return uses, warnings


# (entry, name_raw, strength_model, strength_clip, enabled)
type _Raw = tuple[str, str, float | None, float | None, bool]


def _uses(
    graph: Graph, node: Node, step_suffix: re.Pattern[str], stage_index: int | None
) -> list[LoraUse]:
    return [_use(node, raw, step_suffix, stage_index) for raw in _read(graph, node)]


def _use(node: Node, raw: _Raw, step_suffix: re.Pattern[str], stage_index: int | None) -> LoraUse:
    entry, name_raw, strength_model, strength_clip, enabled = raw
    name = model_stem(name_raw)
    base_name, step = lora_base_step(name, step_suffix)
    return LoraUse(
        position=None,
        stage_index=stage_index,
        node_id=node.id,
        entry=entry,
        class_type=node.class_type,
        name_raw=name_raw,
        name=name,
        base_name=base_name,
        step=step,
        strength_model=strength_model,
        strength_clip=strength_clip,
        enabled=enabled,
        reachable=stage_index is not None,
    )


def _read(graph: Graph, node: Node) -> list[_Raw]:
    entry = REGISTRY[node.class_type]
    if entry.kind != "power":
        name = read_str(node, entry, "name")
        if not name:
            return []
        strength_model = read_float(graph, node, entry, "strength_model")
        strength_clip = read_float(graph, node, entry, "strength_clip")
        return [("", name, strength_model, strength_clip, True)]

    # Widget order is chain order within the node.
    return [
        _power_raw(key, value) for key, value in node.inputs.items() if is_power_entry(key, value)
    ]


def _power_raw(key: str, value: dict[str, Any]) -> _Raw:
    strength = as_float(value["strength"])
    # strengthTwo exists only when rgthree shows separate model and clip strengths.
    clip = as_float(value["strengthTwo"]) if "strengthTwo" in value else strength
    return key, value["lora"], strength, clip, bool(value["on"])


def is_power_entry(key: str, value: object) -> bool:
    # rgthree matches keys case-insensitively and requires on, lora and strength.
    return (
        key.upper().startswith("LORA_")
        and isinstance(value, dict)
        and {"on", "lora", "strength"} <= value.keys()
        and isinstance(value["lora"], str)
        and value["lora"] not in ("", "None")
    )
