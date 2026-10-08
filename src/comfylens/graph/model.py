"""Graph model of a ComfyUI API prompt."""

from dataclasses import dataclass, field
from typing import Any

from comfylens.metadata import is_api_node


@dataclass(frozen=True, slots=True)
class Link:
    src: str  # node id (opaque string)
    slot: int  # output index on src


@dataclass(slots=True)
class Node:
    id: str
    class_type: str
    title: str | None  # _meta.title
    inputs: dict[str, Any]  # literal values or Link
    extra: dict[str, Any]  # other node-level keys, e.g. is_changed

    def link(self, name: str) -> Link | None:
        value = self.inputs.get(name)
        return value if isinstance(value, Link) else None

    def literal(self, name: str) -> Any:
        """The literal value of input `name`; None when absent or linked."""
        value = self.inputs.get(name)
        return None if isinstance(value, Link) else value


@dataclass(slots=True)
class Graph:
    nodes: dict[str, Node]
    # src id -> [(dst id, input name, slot)]
    consumers: dict[str, list[tuple[str, str, int]]] = field(default_factory=dict)
    # (node id, input name) of links that never executed: the branch a constant switch did not
    # select. Set by reachability analysis; every upstream walk skips them.
    inactive: set[tuple[str, str]] = field(default_factory=set)


def parse_graph(prompt: dict[str, Any]) -> Graph:
    """Build a Graph from an API prompt. Entries that are not nodes are skipped."""
    raw = {str(k): v for k, v in prompt.items() if is_api_node(v)}
    nodes: dict[str, Node] = {}
    consumers: dict[str, list[tuple[str, str, int]]] = {}
    for node_id, value in raw.items():
        inputs: dict[str, Any] = {}
        for name, v in value["inputs"].items():
            if _is_link(v, raw):
                inputs[name] = link = Link(v[0], v[1])
                consumers.setdefault(link.src, []).append((node_id, name, link.slot))
            else:
                inputs[name] = v
        meta = value.get("_meta")
        title = meta.get("title") if isinstance(meta, dict) else None
        nodes[node_id] = Node(
            id=node_id,
            class_type=value["class_type"],
            title=title if isinstance(title, str) else None,
            inputs=inputs,
            extra={k: v for k, v in value.items() if k not in ("class_type", "inputs", "_meta")},
        )
    return Graph(nodes, consumers)


def _is_link(value: Any, nodes: dict[str, Any]) -> bool:
    # Exactly [node id in this graph, int]. Every other value is literal, including other lists.
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and value[0] in nodes
        and isinstance(value[1], int)
        and not isinstance(value[1], bool)
    )
