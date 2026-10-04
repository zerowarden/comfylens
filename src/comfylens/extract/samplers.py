from collections import deque
from dataclasses import dataclass, field

from comfylens.extract.registry import REGISTRY, Entry, Role, role_of
from comfylens.extract.types import SamplerStage
from comfylens.extract.values import as_int, number, read_float, read_int, read_str
from comfylens.graph.model import Graph, Link, Node
from comfylens.graph.reachability import Reachability, upstream

# Satellite link of SamplerCustom* -> the role its source should have.
_SATELLITES = {
    "noise": Role.NOISE,
    "guider": Role.GUIDER,
    "sampler": Role.SAMPLER_SELECT,
    "sigmas": Role.SIGMAS,
}


@dataclass(slots=True)
class StageTrace:
    """A stage plus the links the other tracers start from."""

    stage: SamplerStage
    links: dict[str, list[Link]] = field(default_factory=dict)

    def first(self, name: str) -> Link | None:
        found = self.links.get(name)
        return found[0] if found else None


def trace_stages(graph: Graph, reach: Reachability) -> list[StageTrace]:
    """Reachable samplers in topological order; index 0 is the primary stage."""
    nodes = [graph.nodes[n] for n in reach.order]
    samplers = [n for n in nodes if role_of(n.class_type) is Role.SAMPLER]
    return [_trace(graph, node, index) for index, node in enumerate(samplers)]


def stage_nodes(graph: Graph, sampler_id: str) -> set[str]:
    """The sampler and its ancestors, stopping before other samplers and image generators.

    These identify the stage's own model: a pass that made its input image is excluded.
    """
    seen = {sampler_id}
    queue = deque(seen)
    while queue:
        for link in upstream(graph, queue.popleft()):
            if link.src in seen:
                continue
            if role_of(graph.nodes[link.src].class_type) in (Role.SAMPLER, Role.GENERATOR):
                continue
            seen.add(link.src)
            queue.append(link.src)
    return seen


def _trace(graph: Graph, node: Node, index: int) -> StageTrace:
    values: dict[str, int | float | str | None] = {}
    links: dict[str, list[Link]] = {}
    _read(graph, node, REGISTRY[node.class_type], values, links)

    for satellite, role in _SATELLITES.items():
        link = links.get(satellite, [None])[0]
        source = graph.nodes.get(link.src) if link else None
        if source is None:
            continue
        entry = REGISTRY.get(source.class_type)
        if entry is not None and entry.role is role:
            _read(graph, source, entry, values, links)
        elif satellite == "sampler":
            # Sampler objects other than KSamplerSelect (SamplerEulerAncestral, ...).
            _put(values, "sampler_name", source.class_type)
        elif satellite == "sigmas":
            _put(values, "steps", as_int(number(graph, source, "steps")))
            _put(values, "scheduler", source.class_type)

    def get[T](name: str, kind: type[T]) -> T | None:
        value = values.get(name)
        return value if isinstance(value, kind) else None

    stage = SamplerStage(
        index=index,
        node_id=node.id,
        class_type=node.class_type,
        seed=get("seed", int),
        steps=get("steps", int),
        cfg=get("cfg", float),
        sampler_name=get("sampler_name", str),
        scheduler=get("scheduler", str),
        denoise=get("denoise", float),
        start_step=get("start_step", int),
        end_step=get("end_step", int),
    )
    return StageTrace(stage, links)


def _read(
    graph: Graph,
    node: Node,
    entry: Entry,
    values: dict[str, int | float | str | None],
    links: dict[str, list[Link]],
) -> None:
    """Merge a node's fields and links; values already found take precedence."""
    for name in entry.fields:
        if name in ("seed", "steps", "start_step", "end_step"):
            value = read_int(graph, node, entry, name)
        elif name in ("cfg", "denoise"):
            value = read_float(graph, node, entry, name)
        else:
            value = read_str(node, entry, name)
        _put(values, name, value)
    for name, inputs in entry.links.items():
        found = [link for i in inputs if (link := node.link(i)) is not None]
        if found and name not in links:
            links[name] = found


def _put(values: dict[str, int | float | str | None], name: str, value: int | float | str | None):
    if values.get(name) is None:
        values[name] = value
