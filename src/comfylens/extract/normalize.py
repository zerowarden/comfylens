import re
from typing import Any

_MODEL_EXTENSIONS = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".sft")
_ASPECTS = [(1, 1), (4, 5), (3, 4), (2, 3), (9, 16), (9, 21)]
_ASPECTS += [(h, w) for w, h in _ASPECTS if w != h]
_ASPECT_TOLERANCE = 0.03
_SPACES = re.compile(r"[ \t]+")


def model_stem(name: str) -> str:
    """Strip directories (both separators) and a known model-file extension."""
    stem = name.replace("\\", "/").rsplit("/", 1)[-1]
    lower = stem.lower()
    for ext in _MODEL_EXTENSIONS:
        if lower.endswith(ext):
            return stem[: -len(ext)]
    return stem


lora_name = model_stem


def lora_base_step(name: str, step_suffix: re.Pattern[str]) -> tuple[str, int | None]:
    """Split a training-step suffix off a LoRA name: `foo_000004956` -> (`foo`, 4956)."""
    m = step_suffix.match(name)
    if m is None:
        return name, None
    return m.group("base"), int(m.group("step"))


def round_key(x: float, decimals: int) -> float:
    """Round for grouping; -0.0 becomes 0.0."""
    return round(x, decimals) + 0.0


def aspect(width: int, height: int) -> tuple[float, str]:
    """Width / height, with the nearest common ratio label within 3% relative error."""
    ratio = width / height
    best = min(_ASPECTS, key=lambda wh: abs(ratio - wh[0] / wh[1]) / (wh[0] / wh[1]))
    error = abs(ratio - best[0] / best[1]) / (best[0] / best[1])
    label = f"{best[0]}:{best[1]}" if error <= _ASPECT_TOLERANCE else "other"
    return round(ratio, 3), label


def megapixels(width: int, height: int) -> float:
    return round(width * height / 1_000_000, 3)


def size_facts(width: int | None, height: int | None) -> dict[str, Any]:
    """megapixels, aspect and aspect_label of an image; None for each without both sides."""
    if not (width and height):
        return {"megapixels": None, "aspect": None, "aspect_label": None}
    ratio, label = aspect(width, height)
    return {"megapixels": megapixels(width, height), "aspect": ratio, "aspect_label": label}


def prompt_ws(text: str) -> str:
    """Identity key for distinct prompts: strip, CRLF to LF, collapse spaces and tabs."""
    return _SPACES.sub(" ", text.strip().replace("\r\n", "\n"))
