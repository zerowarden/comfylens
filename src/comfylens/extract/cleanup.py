"""Unused LoRAs, and the API prompt and UI workflow without them.

Only what cannot change a run is removed:
- LoRA nodes upstream of no output whose output feeds nothing, or only other such nodes.
  ComfyUI never runs them, and no node that stays is left with a dangling input.
- Power Lora Loader entries switched off, which rgthree skips.

A change the workflow cannot mirror (a node it does not hold, as inside a subgraph) is left out
of both documents, so the two always agree.
"""

from dataclasses import dataclass, field, replace
from typing import Any

from comfylens.extract.loras import is_power_entry
from comfylens.extract.registry import Role, role_of
from comfylens.graph import Graph, Reachability


@dataclass(frozen=True, slots=True)
class Cleanup:
    nodes: dict[str, str] = field(default_factory=dict)  # node id -> class_type, removed whole
    # node id -> {input name: value} of the switched-off Power Lora Loader entries it loses
    entries: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.nodes or self.entries)


def plan_cleanup(graph: Graph, reach: Reachability) -> Cleanup:
    removed = _dangling_loras(graph, reach)
    entries = {
        node.id: off
        for node in graph.nodes.values()
        if node.id not in removed
        and (off := {k: v for k, v in node.inputs.items() if is_power_entry(k, v) and not v["on"]})
    }
    return Cleanup({n: graph.nodes[n].class_type for n in sorted(removed)}, entries)


def _dangling_loras(graph: Graph, reach: Reachability) -> set[str]:
    """Unreachable LoRA nodes, less any whose output reaches a node that stays, to a fixpoint."""
    removed = {
        node.id
        for node in graph.nodes.values()
        if role_of(node.class_type) is Role.LORA and node.id not in reach.reachable
    }
    while True:
        kept = {
            n for n in removed if all(dst in removed for dst, _, _ in graph.consumers.get(n, []))
        }
        if kept == removed:
            return removed
        removed = kept


def clean_prompt(prompt: dict[str, Any], cleanup: Cleanup) -> dict[str, Any]:
    return {
        node_id: _without_inputs(node, cleanup.entries.get(node_id, {}))
        for node_id, node in prompt.items()
        if node_id not in cleanup.nodes
    }


def _without_inputs(node: dict[str, Any], names: dict[str, Any]) -> dict[str, Any]:
    if not names:
        return node
    return {**node, "inputs": {k: v for k, v in node["inputs"].items() if k not in names}}


# --- UI workflow -------------------------------------------------------------------------------
# Format 0.4 lists links as [id, origin, origin slot, target, target slot, type]; format 1 as
# objects. Node ids are numbers there, strings in the API prompt.


def _ends(link: Any) -> tuple[Any, str, str]:
    """A link's id, origin node id and target node id."""
    if isinstance(link, dict):
        return link.get("id"), str(link.get("origin_id")), str(link.get("target_id"))
    return link[0], str(link[1]), str(link[3])


def _is_entry(value: Any, entry: dict[str, Any]) -> bool:
    return isinstance(value, dict) and all(value.get(k) == entry[k] for k in ("on", "lora"))


def _widget_matches(node: dict[str, Any] | None, entries: dict[str, Any]) -> dict[str, int]:
    """Each entry's index among the node's widget values, a distinct one per entry; entries
    without one are left out."""
    widgets = node.get("widgets_values") if node else None
    values = list(enumerate(widgets)) if isinstance(widgets, list) else []
    matches: dict[str, int] = {}
    for name, entry in entries.items():
        taken = set(matches.values())
        found = next((i for i, v in values if i not in taken and _is_entry(v, entry)), None)
        if found is not None:
            matches[name] = found
    return matches


def mirrored(workflow: dict[str, Any], cleanup: Cleanup) -> Cleanup:
    """`cleanup` less what the workflow does not hold in the same form."""
    by_id = {str(n.get("id")): n for n in workflow.get("nodes", []) if isinstance(n, dict)}
    nodes = {n: t for n, t in cleanup.nodes.items() if by_id.get(n, {}).get("type") == t}
    entries = {
        node_id: {name: off[name] for name in matches}
        for node_id, off in cleanup.entries.items()
        if (matches := _widget_matches(by_id.get(node_id), off))
    }
    return replace(cleanup, nodes=nodes, entries=entries)


def clean_workflow(workflow: dict[str, Any], cleanup: Cleanup) -> dict[str, Any]:
    """The workflow without the removed nodes, their links and the switched-off entries.
    Expects a `mirrored` cleanup."""
    gone = {
        link_id
        for link in workflow.get("links", [])
        for link_id, origin, target in [_ends(link)]
        if origin in cleanup.nodes or target in cleanup.nodes
    }
    nodes = [
        _clean_node(n, gone, cleanup.entries.get(str(n.get("id")), {}))
        for n in workflow.get("nodes", [])
        if str(n.get("id")) not in cleanup.nodes
    ]
    links = [link for link in workflow.get("links", []) if _ends(link)[0] not in gone]
    return {**workflow, "nodes": nodes, "links": links, **_clean_extra(workflow, gone)}


def _clean_node(node: dict[str, Any], gone: set[Any], entries: dict[str, Any]) -> dict[str, Any]:
    outputs = [
        {**o, "links": [i for i in o["links"] if i not in gone]} if o.get("links") else o
        for o in node.get("outputs", [])
    ]
    inputs = [{**i, "link": None} if i.get("link") in gone else i for i in node.get("inputs", [])]
    cleaned = {**node, "inputs": inputs, "outputs": outputs}
    if entries:
        dropped = set(_widget_matches(node, entries).values())
        widgets = node["widgets_values"]
        cleaned["widgets_values"] = [v for i, v in enumerate(widgets) if i not in dropped]
    return cleaned


def _clean_extra(workflow: dict[str, Any], gone: set[Any]) -> dict[str, Any]:
    """Native reroutes and link extensions that name removed links."""
    extra = workflow.get("extra")
    if not isinstance(extra, dict) or not gone:
        return {}
    cleaned = {**extra}
    if isinstance(extra.get("linkExtensions"), list):
        cleaned["linkExtensions"] = [e for e in extra["linkExtensions"] if e.get("id") not in gone]
    if isinstance(extra.get("reroutes"), list):
        cleaned["reroutes"] = [
            {**r, "linkIds": [i for i in r.get("linkIds", []) if i not in gone]}
            for r in extra["reroutes"]
        ]
    return {"extra": cleaned}
