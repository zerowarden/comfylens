"""Resolve text inputs that are links to registered string nodes."""

from typing import Any

from comfylens.extract.registry import REGISTRY, Role
from comfylens.extract.switches import through_switches
from comfylens.graph import Graph, Link


def resolve(
    graph: Graph, value: Any, depth: int = 8, generated: list[str] | None = None
) -> str | None:
    """A string literal as-is; a link through switches and registered string nodes.

    A text generator (an LLM node) writes its output at run time, so its input stands in for
    it and its node id is appended to `generated`. A computed node's lone string input is not
    a constant, so it is not followed. None when the text cannot be determined.
    """
    if isinstance(value, str):
        return value
    if not isinstance(value, Link) or depth <= 0:
        return None
    link = through_switches(graph, value)
    node = graph.nodes.get(link.src) if link else None
    if node is None:
        return None
    entry = REGISTRY.get(node.class_type)
    if entry is not None and entry.role in (Role.STRING_PASS, Role.TEXT_GENERATOR):
        if entry.role is Role.TEXT_GENERATOR and generated is not None:
            generated.append(node.id)
        return resolve(graph, node.inputs.get(entry.names[0]), depth - 1, generated)
    if entry is not None and entry.role is Role.STRING_SOURCE:
        parts = [
            resolve(graph, node.inputs.get(name), depth - 1, generated) for name in entry.names
        ]
        delimiter_input = entry.fields.get("delimiter")
        delimiter = (
            resolve(graph, node.inputs.get(delimiter_input, ""), depth - 1, generated)
            if delimiter_input
            else ""
        )
        if delimiter is None or any(p is None for p in parts):
            return None
        return delimiter.join(p for p in parts if p is not None)
    return None
