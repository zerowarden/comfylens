"""Trace a sampler's positive or negative conditioning back to its prompt text."""

from collections.abc import Callable
from dataclasses import dataclass, field

from comfylens.extract import strings
from comfylens.extract.registry import REGISTRY, Entry, Role
from comfylens.extract.switches import through_switches
from comfylens.extract.values import read_float
from comfylens.graph import Graph, Link, Node, Reachability
from comfylens.warn import Code, Warn

HEURISTIC_MIN_CHARS = 20


@dataclass(slots=True)
class SideTrace:
    prompt: str | None = None
    encoders: list[str] = field(default_factory=list)  # text encoder ids, topological order
    guidance: float | None = None  # FluxGuidance
    encoder_guidance: float | None = None  # CLIPTextEncodeFlux, used only without FluxGuidance
    warnings: list[Warn] = field(default_factory=list)


@dataclass(slots=True)
class _Walk:
    graph: Graph
    out: SideTrace = field(default_factory=SideTrace)
    texts: list[tuple[str, str]] = field(default_factory=list)  # (node id, text)
    zeroed: bool = False  # a branch's prompt is the empty string

    def warn(self, code: Code, node_id: str | None, message: str) -> None:
        self.out.warnings.append(Warn(code, node_id, message))


def trace_side(graph: Graph, reach: Reachability, links: list[Link]) -> SideTrace:
    """Depth first from the sampler's links, each link once; each node read by its role."""
    walk = _Walk(graph)
    stack, seen = links[::-1], set[Link]()
    while stack:
        popped = stack.pop()
        link = through_switches(graph, popped)
        if link is None:
            walk.warn(
                Code.PROMPT_UNRESOLVED, popped.src, "a switch chooses the conditioning at run time"
            )
        elif link not in seen:
            seen.add(link)
            stack += _visit(walk, graph.nodes[link.src], link)
    return _finish(walk, reach)


def _visit(walk: _Walk, node: Node, link: Link) -> list[Link]:
    """Read one node into `walk`; returns the links to follow from it."""
    entry = REGISTRY.get(node.class_type)
    visitor = _VISITORS.get(entry.role) if entry else None
    return visitor(walk, node, entry, link) if visitor and entry else _visit_unknown(walk, node)


def _visit_encoder(walk: _Walk, node: Node, entry: Entry, link: Link) -> list[Link]:
    walk.out.encoders.append(node.id)
    if walk.out.encoder_guidance is None:
        walk.out.encoder_guidance = read_float(walk.graph, node, entry, "guidance")
    generated: list[str] = []
    text = _encoder_text(walk.graph, node, entry.slots.get(link.slot, ()), generated)
    walk.out.warnings += generated_warnings(walk.graph, generated)
    if text is None:
        walk.warn(Code.PROMPT_UNRESOLVED, node.id, f"no text for output slot {link.slot}")
    else:
        walk.texts.append((node.id, text))
    return []


def _visit_zero(walk: _Walk, node: Node, entry: Entry, link: Link) -> list[Link]:
    walk.zeroed = True
    return []


def _visit_pass(walk: _Walk, node: Node, entry: Entry, link: Link) -> list[Link]:
    if walk.out.guidance is None:  # nearest the sampler is the one in effect
        walk.out.guidance = read_float(walk.graph, node, entry, "guidance")
    return _linked(node, lambda name: name.startswith("conditioning"))


_VISITORS: dict[Role, Callable[[_Walk, Node, Entry, Link], list[Link]]] = {
    Role.TEXT_ENCODER: _visit_encoder,
    Role.CONDITIONING_ZERO: _visit_zero,
    Role.CONDITIONING_PASS: _visit_pass,
}


def _visit_unknown(walk: _Walk, node: Node) -> list[Link]:
    """A node of no known role: its longest long-enough string input is taken as the prompt,
    else its conditioning-like inputs are followed."""
    literals = [
        v for v in node.inputs.values() if isinstance(v, str) and len(v) >= HEURISTIC_MIN_CHARS
    ]
    if literals:
        walk.texts.append((node.id, max(literals, key=len)))
        walk.warn(Code.HEURISTIC_PROMPT, node.id, f"prompt guessed from {node.class_type}")
        return []
    followed = _linked(node, lambda name: "cond" in name)
    if not followed:
        walk.warn(Code.PROMPT_UNRESOLVED, node.id, f"cannot read a prompt from {node.class_type}")
    return followed


def _finish(walk: _Walk, reach: Reachability) -> SideTrace:
    """Encoders and non-empty texts in graph order; several texts are joined. Texts that are all
    empty, or a zeroed branch, give the empty prompt."""
    out = walk.out
    out.encoders.sort(key=reach.rank.__getitem__)
    nonempty = sorted((t for t in walk.texts if t[1].strip()), key=lambda t: reach.rank[t[0]])
    if len(nonempty) > 1:
        out.warnings.append(
            Warn(Code.MULTIPLE_PROMPT_SOURCES, None, f"{len(nonempty)} prompt sources joined")
        )
    has_prompt = bool(walk.texts) or walk.zeroed
    out.prompt = "\n\n".join(text for _, text in nonempty) if has_prompt else None
    return out


def generated_warnings(graph: Graph, generated: list[str]) -> list[Warn]:
    """One informational warning per text generator a prompt was resolved through."""
    return [
        Warn(
            Code.GENERATED_PROMPT,
            generator,
            f"rewritten at run time by {graph.nodes[generator].class_type};"
            " the prompt shown is its input",
        )
        for generator in dict.fromkeys(generated)
    ]


def _encoder_text(
    graph: Graph, node: Node, fields: tuple[str, ...], generated: list[str]
) -> str | None:
    """The first non-empty text among `fields`, else the first that resolved at all."""
    resolved = [
        text
        for name in fields
        if name in node.inputs
        and (text := strings.resolve(graph, node.inputs[name], generated=generated)) is not None
    ]
    return next((t for t in resolved if t.strip()), resolved[0] if resolved else None)


def _linked(node: Node, wanted: Callable[[str], bool]) -> list[Link]:
    return [v for name, v in node.inputs.items() if isinstance(v, Link) and wanted(name)][::-1]
