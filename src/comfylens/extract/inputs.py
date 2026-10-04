"""The generic layer: every literal input of every node."""

import json
from typing import Any

from comfylens.extract.types import GenericInput, GenericKind
from comfylens.graph.model import Graph, Link

MAX_STR_CHARS = 4000


def generic_inputs(graph: Graph, reachable: set[str]) -> list[GenericInput]:
    out: list[GenericInput] = []
    for node in graph.nodes.values():
        for name, value in node.inputs.items():
            if not isinstance(value, Link):
                _emit(out, node.id, node.class_type, name, value, node.id in reachable)
    return out


def _emit(
    out: list[GenericInput], node_id: str, class_type: str, name: str, value: Any, reachable: bool
) -> None:
    if isinstance(value, dict) and value:
        for key, item in value.items():
            _emit(out, node_id, class_type, f"{name}.{key}", item, reachable)
        return
    kind: GenericKind
    if isinstance(value, bool):
        kind = "bool"
    elif isinstance(value, int | float):
        kind = "num"
    elif isinstance(value, str):
        kind, value = "str", value[:MAX_STR_CHARS]
    else:
        kind, value = "json", json.dumps(value, ensure_ascii=False)
    out.append(GenericInput(node_id, class_type, name, kind, value, reachable))
