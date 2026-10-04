"""Output nodes, the reachable set and topological order.

ComfyUI executes only ancestors of output nodes, so only those contribute to statistics.
"""

import heapq
import re
from collections import deque
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field

from comfylens.graph.model import Graph, Link
from comfylens.warn import Code, Warn


class GraphCycle(ValueError):
    """The reachable part of the graph contains a cycle."""


@dataclass(frozen=True, slots=True)
class Switch:
    """A lazy switch: ComfyUI evaluates only the input its boolean selects."""

    condition: str
    on_true: str
    on_false: str
    soft: bool = False  # an unconnected selected input falls back to the other one


@dataclass(slots=True)
class Reachability:
    outputs: list[str]
    reachable: set[str]
    order: list[str]  # reachable nodes in topological order
    rank: dict[str, int]  # node id -> position in `order`
    warnings: list[Warn] = field(default_factory=list)


def upstream(graph: Graph, node_id: str) -> Iterable[Link]:
    """Links into a node, except those a constant switch left unevaluated."""
    node = graph.nodes.get(node_id)
    if node is not None:
        for name, value in node.inputs.items():
            if isinstance(value, Link) and (node_id, name) not in graph.inactive:
                yield value


def analyze_reachability(
    graph: Graph,
    output_classes: Collection[str],
    output_name_regex: re.Pattern[str],
    sampler_classes: Collection[str],
    inactive: Collection[tuple[str, str]] = (),
) -> Reachability:
    """Raises GraphCycle when the reachable nodes cannot be ordered.

    `inactive` holds the links a constant switch left unevaluated (see extract.switches);
    every upstream walk skips them.
    """
    warnings: list[Warn] = []
    graph.inactive = set(inactive)
    outputs = sorted(
        n.id
        for n in graph.nodes.values()
        if n.class_type in output_classes
        or (n.id not in graph.consumers and output_name_regex.search(n.class_type))
    )
    roots = outputs
    if not outputs:
        roots = sorted(n.id for n in graph.nodes.values() if n.class_type in sampler_classes)
        warnings.append(
            Warn(Code.NO_OUTPUT_NODE, None, "no output node found; samplers used as roots")
        )

    reachable = _ancestors(graph, roots)
    order = _toposort(graph, reachable)

    branches = {frozenset(s) for s in (_nearest(graph, o, sampler_classes) for o in outputs) if s}
    if len(branches) > 1:
        warnings.append(
            Warn(
                Code.MULTIPLE_OUTPUT_BRANCHES,
                None,
                "output nodes lead back to different samplers; the first stage is primary",
            )
        )
    rank = {n: i for i, n in enumerate(order)}
    return Reachability(outputs, reachable, order, rank, warnings)


def _ancestors(graph: Graph, roots: Iterable[str]) -> set[str]:
    """Reverse breadth-first search over links, inclusive of the roots."""
    seen = set(roots)
    queue = deque(seen)
    while queue:
        for link in upstream(graph, queue.popleft()):
            if link.src not in seen:
                seen.add(link.src)
                queue.append(link.src)
    return seen


def _toposort(graph: Graph, reachable: set[str]) -> list[str]:
    """Kahn's algorithm; ties are broken by node id string order for determinism."""
    indegree = {n: 0 for n in reachable}
    for node_id in reachable:
        for _link in upstream(graph, node_id):
            indegree[node_id] += 1
    ready = [n for n, d in indegree.items() if d == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        node_id = heapq.heappop(ready)
        order.append(node_id)
        for dst, name, _slot in graph.consumers.get(node_id, ()):
            if dst not in indegree or (dst, name) in graph.inactive:
                continue
            indegree[dst] -= 1
            if indegree[dst] == 0:
                heapq.heappush(ready, dst)
    if len(order) < len(reachable):
        stuck = sorted(reachable - set(order))
        raise GraphCycle(f"cycle among nodes {', '.join(stuck[:10])}")
    return order


def _nearest(graph: Graph, output: str, sampler_classes: Collection[str]) -> set[str]:
    """Samplers reachable upstream of `output` without passing through another sampler."""
    found: set[str] = set()
    seen = {output}
    queue = deque([output])
    while queue:
        for link in upstream(graph, queue.popleft()):
            if link.src in seen:
                continue
            seen.add(link.src)
            if graph.nodes[link.src].class_type in sampler_classes:
                found.add(link.src)
            else:
                queue.append(link.src)
    return found
