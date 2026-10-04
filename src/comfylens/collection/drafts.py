"""Drafts: an image's bytes become a stored original plus the prompt fields its metadata holds.

Saving a library image and uploading a file both come through here, so the two give the same
draft. Nothing is saved as a prompt until the user confirms the draft.
"""

import contextlib
import json
import re
from io import BytesIO
from typing import Any

from PIL import Image

from comfylens.collection.store import CollectionStore, OriginalFormat
from comfylens.config import Config
from comfylens.extract.normalize import prompt_ws
from comfylens.extract.pipeline import analyze
from comfylens.extract.types import Extraction
from comfylens.index.thumbs import make_thumbnail
from comfylens.paths import thumb_path, thumbs_dir

MAX_UPLOAD_BYTES = 64 * 1024 * 1024
TITLE_CHARS = 60
_PIL_FORMATS: dict[str, OriginalFormat] = {"PNG": "png", "JPEG": "jpeg", "WEBP": "webp"}
_FIRST_SENTENCE = re.compile(r"[^\n.!?]*")


class UnsupportedImage(ValueError):
    """The bytes are not a PNG, JPEG or WebP image."""


def suggest_title(positive: str) -> str:
    """The prompt's first sentence, cut at a word boundary; "Untitled" for an empty prompt."""
    match = _FIRST_SENTENCE.match(prompt_ws(positive))
    first = (match.group(0) if match else "").strip(" ,;:")
    if not first:
        return "Untitled"
    if len(first) <= TITLE_CHARS:
        return first
    cut = first[: TITLE_CHARS + 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    return (cut or first[:TITLE_CHARS]) + "…"


def empty_settings() -> dict[str, Any]:
    keys = ("base_model", "seed", "steps", "cfg", "sampler_name", "scheduler", "denoise")
    return {**dict.fromkeys(keys), "guidance": None, "shift": None, "loras": []}


def settings_of(e: Extraction) -> dict[str, Any]:
    """The primary stage's sampler settings and the LoRAs that took effect, in chain order."""
    p = e.primary
    loras: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for lora in e.loras:
        # A LoRA on several stages' chains appears once per stage.
        if not (lora.reachable and lora.enabled) or (lora.node_id, lora.entry) in seen:
            continue
        seen.add((lora.node_id, lora.entry))
        loras.append(
            {
                "name": lora.name,
                "strength_model": lora.strength_model,
                "strength_clip": lora.strength_clip,
            }
        )
    return {
        "base_model": e.base_model,
        "seed": str(p.seed) if p and p.seed is not None else None,
        "steps": p.steps if p else None,
        "cfg": p.cfg if p else None,
        "sampler_name": p.sampler_name if p else None,
        "scheduler": p.scheduler if p else None,
        "denoise": p.denoise if p else None,
        "guidance": e.guidance,
        "shift": e.shift,
        "loras": loras,
    }


def text_draft(positive: str, negative: str = "") -> dict[str, Any]:
    """A draft without an image, e.g. a prompt typed in or picked from prompt analysis."""
    return {
        "original": None,
        "title": suggest_title(positive),
        "positive": positive,
        "negative": negative,
        "model_family": None,
        "settings": empty_settings(),
        "metadata": "none",
    }


def _identify(data: bytes) -> tuple[OriginalFormat, int, int]:
    try:
        with Image.open(BytesIO(data)) as img:
            fmt = _PIL_FORMATS.get(img.format or "")
            width, height = img.size
            img.verify()
    except Exception as e:
        raise UnsupportedImage("not a PNG, JPEG or WebP image") from e
    if fmt is None:
        raise UnsupportedImage("not a PNG, JPEG or WebP image")
    return fmt, width, height


def build_draft(data: bytes, store: CollectionStore, config: Config) -> dict[str, Any]:
    """Store the bytes as an original and read a draft from their metadata.

    Raises UnsupportedImage. The original's `library_ids` is left for the caller to fill in.
    """
    fmt, width, height = _identify(data)
    draft = text_draft("")
    api_prompt = workflow = None
    if fmt != "webp":  # the metadata readers know PNG and JPEG only
        analysis = analyze(data, config)
        if analysis.raw is not None:
            api_prompt = analysis.raw.api_prompt
            workflow = analysis.raw.workflow
        e = analysis.extraction
        if e is not None:
            positive = e.positive_prompt or ""
            draft |= {
                "title": suggest_title(positive),
                "positive": positive,
                "negative": e.negative_prompt or "",
                "model_family": e.model_family,
                "settings": settings_of(e),
                "metadata": "comfyui",
            }

    content_hash = store.put_original(
        data,
        fmt,
        width,
        height,
        json.dumps(api_prompt) if api_prompt is not None else None,
        json.dumps(workflow) if workflow is not None else None,
    )
    with contextlib.suppress(Exception):  # the /thumbs route rebuilds it on request
        _thumbnail(data, content_hash, config)
    draft["original"] = {
        "content_hash": content_hash,
        "role": "reference",
        "format": fmt,
        "width": width,
        "height": height,
        "has_workflow": api_prompt is not None or workflow is not None,
        "library_ids": [],
    }
    return draft


def _thumbnail(data: bytes, content_hash: str, config: Config) -> None:
    thumbs = config.thumbs
    make_thumbnail(data, thumb_path(thumbs_dir(), content_hash), thumbs.long_edge, thumbs.quality)


def rebuild_thumbnail(store: CollectionStore, content_hash: str, config: Config) -> bool:
    """Write a collection original's missing thumbnail; False when it is not an original or
    cannot be read."""
    original = store.original(content_hash)
    if original is None:
        return False
    try:
        _thumbnail(original["path"].read_bytes(), content_hash, config)
    except Exception:
        return False
    return True
