"""Walk upstream from a sampler's model input to the base model loader."""

from dataclasses import dataclass, field

from comfylens.extract.registry import REGISTRY, Entry, Role
from comfylens.extract.switches import follow
from comfylens.extract.values import read_float
from comfylens.graph import Graph, Link, Node
from comfylens.warn import Code, Warn


@dataclass(slots=True)
class ModelChain:
    loader: Node | None = None  # the base model loader
    lora_nodes: list[str] = field(default_factory=list)  # from the loader outward
    shift: float | None = None
    warnings: list[Warn] = field(default_factory=list)


def trace_model(graph: Graph, link: Link | None, sampler_id: str) -> ModelChain:
    passed, end = _until_loader(graph, link)
    patches = [(n, e) for n, e in passed if e is not None and e.role is Role.MODEL_PATCH]
    # A node that passes the model on in a way the registry does not know.
    unknown = [
        Warn(Code.UNKNOWN_MODEL_PATCH, node.id, f"{node.class_type} passes the model on")
        for node, entry in passed
        if _role(entry) not in (Role.LORA, Role.MODEL_PATCH) and node.link("model") is not None
    ]
    last_id = passed[-1][0].id if passed else sampler_id
    return ModelChain(
        loader=end[0] if end and end[1] is Role.MODEL_LOADER else None,
        lora_nodes=[node.id for node, entry in reversed(passed) if _role(entry) is Role.LORA],
        # The patch nearest the sampler is the one in effect.
        shift=next(
            (
                v
                for node, entry in patches
                if (v := read_float(graph, node, entry, "shift")) is not None
            ),
            None,
        ),
        warnings=[*unknown, *_end_warnings(end, last_id)],
    )


def _role(entry: Entry | None) -> Role | None:
    return entry.role if entry else None


def _until_loader(
    graph: Graph, link: Link | None
) -> tuple[list[tuple[Node, Entry | None]], tuple[Node, Role] | None]:
    """The nodes from the sampler towards the loader, and the loader or switch that ends the
    walk; None when the chain just ends."""
    passed: list[tuple[Node, Entry | None]] = []
    for node in follow(graph, link, "model"):
        entry = REGISTRY.get(node.class_type)
        if entry and entry.role in (Role.SWITCH, Role.MODEL_LOADER):
            return passed, (node, entry.role)
        passed.append((node, entry))
    return passed, None


def _end_warnings(end: tuple[Node, Role] | None, last_id: str) -> list[Warn]:
    if end is None:
        return [Warn(Code.MODEL_CHAIN_BROKEN, last_id, "model chain ends before a model loader")]
    node, role = end
    if role is Role.SWITCH:  # a computed condition: the chain cannot be followed
        return [Warn(Code.MODEL_CHAIN_BROKEN, node.id, "a switch chooses the model at run time")]
    return []
