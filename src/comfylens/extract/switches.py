"""Follow constant switches to the input they selected (see graph.reachability)."""

from collections.abc import Iterator, Mapping
from typing import Any

from comfylens.extract.constants import source_literal
from comfylens.extract.registry import REGISTRY, Role
from comfylens.graph.model import Graph, Link, Node
from comfylens.graph.reachability import Switch


def inactive_inputs(graph: Graph, switches: Mapping[str, Switch]) -> set[tuple[str, str]]:
    """The inputs a constant switch did not select; every upstream walk skips them."""
    inactive: set[tuple[str, str]] = set()
    for node in graph.nodes.values():
        switch = switches.get(node.class_type)
        if switch is None:
            continue
        condition = constant_bool(graph, node, switch.condition)
        if condition is None:
            continue  # computed at run time: either branch may have run
        chosen, other = (
            (switch.on_true, switch.on_false) if condition else (switch.on_false, switch.on_true)
        )
        if switch.soft and node.link(chosen) is None:
            chosen, other = other, chosen
        inactive.add((node.id, other))
    return inactive


def through_switches(graph: Graph, link: Link | None) -> Link | None:
    """The link past any chain of switches; None when a switch's choice is made at run time
    (a computed condition) or the selected input is not connected."""
    seen: set[str] = set()
    while link is not None and link.src not in seen:
        node = graph.nodes.get(link.src)
        entry = REGISTRY.get(node.class_type) if node else None
        if node is None or entry is None or entry.role is not Role.SWITCH:
            return link
        seen.add(node.id)
        active = [
            selected
            for name in (entry.fields["on_true"], entry.fields["on_false"])
            if (node.id, name) not in graph.inactive and (selected := node.link(name))
        ]
        link = active[0] if len(active) == 1 else None
    return link


def follow(graph: Graph, link: Link | None, input_name: str) -> Iterator[Node]:
    """Yield the nodes upstream along `input_name`, resolving constant switches.

    Stops at the end of the chain or at a cycle. A yielded switch node means the walk stopped
    there because its choice is made at run time; the caller reports that in its own terms.
    """
    seen: set[str] = set()
    while link is not None:
        followed = through_switches(graph, link)
        if followed is None:
            yield graph.nodes[link.src]  # a runtime switch: the chain ends here
            return
        if followed.src in seen:
            return
        seen.add(followed.src)
        node = graph.nodes[followed.src]
        yield node
        link = node.link(input_name)


def constant_bool(graph: Graph, node: Node, name: str) -> bool | None:
    """A literal bool, or one link to a primitive node whose only bool is that literal."""
    value = node.inputs.get(name)
    if isinstance(value, Link):
        return source_literal(graph, value, (Role.PRIMITIVE,), _is_bool)
    return value if isinstance(value, bool) else None


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)
