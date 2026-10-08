"""Typed reads of node inputs."""

import math
from typing import Any

from comfylens.extract.constants import source_literal
from comfylens.extract.registry import Entry, Role
from comfylens.graph import Graph, Link, Node


def as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def as_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def number(graph: Graph, node: Node, name: str | None) -> int | float | None:
    """A numeric input, following one link to a primitive source's only numeric literal.

    Covers seed and value nodes such as PrimitiveInt. A computed node
    with one numeric literal among its inputs is not a constant.
    """
    if name is None:
        return None
    value = node.inputs.get(name)
    if isinstance(value, Link):
        return source_literal(graph, value, (Role.PRIMITIVE,), _is_number)
    return value if _is_number(value) else None


def read_int(graph: Graph, node: Node, entry: Entry, field: str) -> int | None:
    return as_int(number(graph, node, entry.fields.get(field)))


def read_float(graph: Graph, node: Node, entry: Entry, field: str) -> float | None:
    return as_float(number(graph, node, entry.fields.get(field)))


def read_str(node: Node, entry: Entry, field: str) -> str | None:
    name = entry.fields.get(field)
    return as_str(node.literal(name)) if name else None
