"""Text encoders, VAE, latent source and input images."""

import re
from collections import deque

from comfylens.extract.normalize import model_stem
from comfylens.extract.registry import REGISTRY, Role, role_of
from comfylens.extract.samplers import StageTrace
from comfylens.extract.switches import follow, through_switches
from comfylens.extract.types import InputImage
from comfylens.extract.values import as_int, as_str, read_str
from comfylens.graph.model import Graph, Node
from comfylens.graph.reachability import Reachability, upstream

_SHA256 = re.compile(r"[0-9a-fA-F]{64}")


def text_encoders(graph: Graph, encoder_ids: list[str]) -> tuple[list[str], str | None]:
    """Clip file stems and clip type, walking each encoder's `clip` input to its loader.

    LoRA nodes (and anything else with a `clip` input) pass CLIP through.
    """
    names: list[str] = []
    clip_type: str | None = None
    for encoder_id in encoder_ids:
        link = graph.nodes[encoder_id].link("clip")
        for node in follow(graph, link, "clip"):
            entry = REGISTRY.get(node.class_type)
            if entry is not None and (
                entry.role is Role.CLIP_LOADER
                or (entry.role is Role.MODEL_LOADER and entry.kind == "ckpt")
            ):
                for name in entry.names:
                    value = as_str(node.literal(name))
                    if value and model_stem(value) not in names:
                        names.append(model_stem(value))
                clip_type = clip_type or read_str(node, entry, "clip_type")
                break
    return names, clip_type


def vae(graph: Graph, reach: Reachability) -> str | None:
    """The VAE of the decode node nearest an output, else any reachable VAELoader.

    Nodes with a `vae` input (rgthree Context, ...) pass the VAE through.
    """
    for output in reach.outputs:
        decode = _nearest(graph, output, Role.VAE_DECODE)
        link = decode.link("vae") if decode else None
        for source in follow(graph, link, "vae"):
            entry = REGISTRY.get(source.class_type)
            if entry and entry.role in (Role.VAE_LOADER, Role.MODEL_LOADER):
                value = as_str(source.literal(entry.names[0]))
                return model_stem(value) if value else None
    for node_id in reach.order:
        node = graph.nodes[node_id]
        if role_of(node.class_type) is Role.VAE_LOADER:
            value = as_str(node.literal(REGISTRY[node.class_type].names[0]))
            if value:
                return model_stem(value)
    return None


def latent(graph: Graph, primary: StageTrace | None) -> tuple[str | None, int | None]:
    """The class feeding the primary stage's latent input, and its batch size if any."""
    link = through_switches(graph, primary.first("latent")) if primary else None
    source = graph.nodes.get(link.src) if link else None
    if source is None:
        return None, None
    return source.class_type, as_int(source.literal("batch_size"))


def input_images(graph: Graph, reach: Reachability) -> list[InputImage]:
    images = []
    for node_id in reach.order:
        node = graph.nodes[node_id]
        if role_of(node.class_type) is not Role.IMAGE_INPUT:
            continue
        # LoadImage's is_changed holds the SHA-256 of the input file.
        changed = node.extra.get("is_changed")
        first = changed[0] if isinstance(changed, list) and changed else None
        sha256 = first.lower() if isinstance(first, str) and _SHA256.fullmatch(first) else None
        filename = read_str(node, REGISTRY[node.class_type], "filename")
        images.append(InputImage(node_id, filename, sha256))
    return images


def _nearest(graph: Graph, start: str, role: Role) -> Node | None:
    seen = {start}
    queue = deque([start])
    while queue:
        for link in upstream(graph, queue.popleft()):
            if link.src in seen:
                continue
            seen.add(link.src)
            node = graph.nodes[link.src]
            if role_of(node.class_type) is role:
                return node
            queue.append(link.src)
    return None
