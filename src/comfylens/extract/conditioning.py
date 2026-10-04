"""Trace a sampler's positive or negative conditioning back to its prompt text."""

from collections.abc import Callable
from dataclasses import dataclass, field

from comfylens.extract import strings
from comfylens.extract.registry import REGISTRY, Role
from comfylens.extract.switches import through_switches
from comfylens.extract.values import read_float
from comfylens.graph.model import Graph, Link, Node
from comfylens.graph.reachability import Reachability
from comfylens.warn import Code, Warn

HEURISTIC_MIN_CHARS = 20


@dataclass(slots=True)
class SideTrace:
    prompt: str | None = None
    encoders: list[str] = field(default_factory=list)  # text encoder ids, topological order
    guidance: float | None = None  # FluxGuidance
    encoder_guidance: float | None = None  # CLIPTextEncodeFlux, used only without FluxGuidance
    warnings: list[Warn] = field(default_factory=list)


def trace_side(graph: Graph, reach: Reachability, links: list[Link]) -> SideTrace:
    out = SideTrace()
    texts: list[tuple[str, str]] = []  # (node id, text)
    zeroed = False
    stack = links[::-1]
    seen: set[Link] = set()
    while stack:
        popped = stack.pop()
        link = through_switches(graph, popped)
        if link is None:
            message = "a switch chooses the conditioning at run time"
            out.warnings.append(Warn(Code.PROMPT_UNRESOLVED, popped.src, message))
            continue
        if link in seen:
            continue
        seen.add(link)
        node = graph.nodes[link.src]
        entry = REGISTRY.get(node.class_type)
        role = entry.role if entry else None

        if role is Role.TEXT_ENCODER and entry is not None:
            out.encoders.append(node.id)
            if out.encoder_guidance is None:
                out.encoder_guidance = read_float(graph, node, entry, "guidance")
            generated: list[str] = []
            text = _encoder_text(graph, node, entry.slots.get(link.slot, ()), generated)
            out.warnings += generated_warnings(graph, generated)
            if text is None:
                out.warnings.append(
                    Warn(Code.PROMPT_UNRESOLVED, node.id, f"no text for output slot {link.slot}")
                )
            else:
                texts.append((node.id, text))
        elif role is Role.CONDITIONING_ZERO:
            zeroed = True  # this branch's prompt is the empty string
        elif role is Role.CONDITIONING_PASS and entry is not None:
            if out.guidance is None:
                out.guidance = read_float(graph, node, entry, "guidance")
            stack += _linked(node, lambda name: name.startswith("conditioning"))
        else:
            literals = [
                v
                for v in node.inputs.values()
                if isinstance(v, str) and len(v) >= HEURISTIC_MIN_CHARS
            ]
            if literals:
                texts.append((node.id, max(literals, key=len)))
                out.warnings.append(
                    Warn(Code.HEURISTIC_PROMPT, node.id, f"prompt guessed from {node.class_type}")
                )
            elif followed := _linked(node, lambda name: "cond" in name):
                stack += followed
            else:
                message = f"cannot read a prompt from {node.class_type}"
                out.warnings.append(Warn(Code.PROMPT_UNRESOLVED, node.id, message))

    out.encoders.sort(key=reach.rank.__getitem__)
    nonempty = sorted((t for t in texts if t[1].strip()), key=lambda t: reach.rank[t[0]])
    if len(nonempty) > 1:
        out.warnings.append(
            Warn(Code.MULTIPLE_PROMPT_SOURCES, None, f"{len(nonempty)} prompt sources joined")
        )
        out.prompt = "\n\n".join(text for _, text in nonempty)
    elif nonempty:
        out.prompt = nonempty[0][1]
    elif texts or zeroed:
        out.prompt = ""
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
