"""Walk upstream from a sampler's model input to the base model loader."""

from dataclasses import dataclass, field

from comfylens.extract.registry import REGISTRY, Role
from comfylens.extract.switches import follow
from comfylens.extract.values import read_float
from comfylens.graph.model import Graph, Link, Node
from comfylens.warn import Code, Warn


@dataclass(slots=True)
class ModelChain:
    loader: Node | None = None  # the base model loader
    lora_nodes: list[str] = field(default_factory=list)  # from the loader outward
    shift: float | None = None
    warnings: list[Warn] = field(default_factory=list)


def trace_model(graph: Graph, link: Link | None, sampler_id: str) -> ModelChain:
    chain = ModelChain()
    outward: list[str] = []  # LoRA nodes from the sampler towards the loader
    last_id = sampler_id
    for node in follow(graph, link, "model"):
        entry = REGISTRY.get(node.class_type)
        role = entry.role if entry else None
        if role is Role.SWITCH:  # a computed condition: the chain cannot be followed
            chain.warnings.append(
                Warn(Code.MODEL_CHAIN_BROKEN, node.id, "a switch chooses the model at run time")
            )
            return _finish(chain, outward)
        last_id = node.id
        if role is Role.MODEL_LOADER:
            chain.loader = node
            break
        if role is Role.LORA:
            outward.append(node.id)
        elif role is Role.MODEL_PATCH and entry is not None:
            if chain.shift is None:  # nearest the sampler is the one in effect
                chain.shift = read_float(graph, node, entry, "shift")
        elif node.link("model") is not None:
            chain.warnings.append(
                Warn(Code.UNKNOWN_MODEL_PATCH, node.id, f"{node.class_type} passes the model on")
            )
    if chain.loader is None:
        chain.warnings.append(
            Warn(Code.MODEL_CHAIN_BROKEN, last_id, "model chain ends before a model loader")
        )
    return _finish(chain, outward)


def _finish(chain: ModelChain, outward: list[str]) -> ModelChain:
    chain.lora_nodes = outward[::-1]
    return chain
