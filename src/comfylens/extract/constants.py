"""Literal values read through one link to a registered source node."""

from collections.abc import Callable, Collection
from typing import Any

from comfylens.extract.registry import REGISTRY, Role
from comfylens.graph import Graph, Link


def source_literal(
    graph: Graph, link: Link, roles: Collection[Role], is_kind: Callable[[Any], bool]
) -> Any | None:
    """The source node's only literal of the requested kind, when its role allows it.

    Only registered source roles count. A computed node can carry exactly one literal of a
    kind among its inputs (e.g. StringContains.case_sensitive), and following such a link
    would treat a run-time value as a constant.
    """
    source = graph.nodes.get(link.src)
    if source is None:
        return None
    entry = REGISTRY.get(source.class_type)
    if entry is None or entry.role not in roles:
        return None
    found = [value for value in source.inputs.values() if is_kind(value)]
    return found[0] if len(found) == 1 else None
