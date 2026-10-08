"""A1111 "parameters" text, as written by Stable Diffusion web UI, Forge and Civitai:

    a red fox in the snow <lora:fox:0.8>
    Negative prompt: blurry
    Steps: 20, Sampler: DPM++ 2M, Schedule type: Karras, CFG scale: 7, Seed: 42, ...

Only collection drafts read it; the indexer keeps ignoring it (see metadata.blobs).
"""

import re
from typing import Any

from comfylens.collection.models import saved_lora

_SETTINGS_LINE = re.compile(r"^Steps: \d+")
_NEGATIVE = "Negative prompt:"
# "Key: value" pairs; a quoted value may hold commas ("Lora hashes": "a: 1, b: 2").
_PAIR = re.compile(r'\s*([^:,]+?):\s*("(?:\\.|[^"\\])*"|[^,]*)(?:,|$)')
_LORA = re.compile(r"<(?:lora|lyco):([^:>]+)((?::[^:>]*)*)>", re.IGNORECASE)
_NUMBER = re.compile(r"-?(?:\d+(?:\.\d*)?|\.\d+)")


def _float(text: str | None) -> float | None:
    if text is None:
        return None
    m = _NUMBER.fullmatch(text.strip())
    return float(m.group(0)) if m else None


def _int(text: str | None) -> int | None:
    value = _float(text)
    return int(value) if value is not None and value.is_integer() else None


def settings_pairs(line: str) -> dict[str, str]:
    """The settings line as key -> value, quotes removed; later duplicates are ignored."""
    pairs: dict[str, str] = {}
    for key, value in _PAIR.findall(line):
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1].replace('\\"', '"')
        pairs.setdefault(key.strip(), value)
    return pairs


def loras(positive: str) -> list[dict[str, Any]]:
    """`<lora:name:weight>` tags, in order. A bare tag has weight 1; `te=` and `unet=` name the
    text-encoder (clip) and model strengths."""
    return [_lora(name, args.split(":")[1:]) for name, args in _LORA.findall(positive)]


def _lora(name: str, args: list[str]) -> dict[str, Any]:
    named = {
        key.strip().lower(): _float(value)
        for key, _, value in (arg.partition("=") for arg in args)
        if value
    }
    positional = [n for arg in args if "=" not in arg and (n := _float(arg)) is not None]
    model, clip = _strengths(named.get("unet"), named.get("te"), positional)
    return saved_lora(name.strip(), model, clip)


def _strengths(
    model: float | None, clip: float | None, positional: list[float]
) -> tuple[float | None, float | None]:
    """A1111's reading: the first positional weight stands for any strength not named, and a
    second one is the model ("unet") strength. With no weight at all, both are 1."""
    first = positional[0] if positional else None
    model = positional[1] if len(positional) > 1 else first if model is None else model
    clip = first if clip is None else clip
    return (1.0, 1.0) if model is None and clip is None else (model, clip)


def parse_parameters(text: str) -> dict[str, Any] | None:
    """positive, negative and settings (PromptSettings fields); None when there is no prompt."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").strip().split("\n")
    settings_at = next(
        (i for i in range(len(lines) - 1, -1, -1) if _SETTINGS_LINE.match(lines[i])), None
    )
    body = lines if settings_at is None else lines[:settings_at]
    pairs = settings_pairs(lines[settings_at]) if settings_at is not None else {}

    negative_at = next((i for i, line in enumerate(body) if line.startswith(_NEGATIVE)), None)
    if negative_at is None:
        positive, negative = "\n".join(body), ""
    else:
        positive = "\n".join(body[:negative_at])
        negative = "\n".join(
            [body[negative_at][len(_NEGATIVE) :].lstrip(), *body[negative_at + 1 :]]
        )
    positive, negative = positive.strip(), negative.strip()
    if not positive and not pairs:
        return None

    seed = pairs.get("Seed")
    return {
        "positive": positive,
        "negative": negative,
        "settings": {
            "base_model": pairs.get("Model") or None,
            "seed": seed if seed and seed.isdigit() else None,
            "steps": _int(pairs.get("Steps")),
            "cfg": _float(pairs.get("CFG scale")),
            "sampler_name": pairs.get("Sampler") or None,
            "scheduler": pairs.get("Schedule type") or None,
            "denoise": _float(pairs.get("Denoising strength")),
            # Forge's Flux guidance.
            "guidance": _float(pairs.get("Distilled CFG Scale")),
            "shift": _float(pairs.get("Shift")),
            "loras": loras(positive),
        },
    }
