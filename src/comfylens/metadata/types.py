"""Data passed from the format readers to blob classification."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from comfylens.warn import Warn

Format = Literal["png", "jpeg"]
Status = Literal["ok", "partial", "no_metadata", "error"]
# How a text value was classified: see blobs.classify.
Kind = Literal["api_prompt", "workflow", "a1111", "json", "text", "oversized"]

# Metadata is untrusted: larger payloads are never inflated or parsed.
MAX_TEXT_BYTES = 50 * 1024 * 1024


class Truncated(ValueError):
    """The data ends, or stops making sense, inside a chunk or segment or before the image end."""


def until_truncated[T](items: Iterable[T]) -> tuple[list[T], bool]:
    """The items read before a Truncated, and whether one was raised."""
    read: list[T] = []
    try:
        read.extend(items)  # appends one by one: what came before the error stays
    except Truncated:
        return read, True
    return read, False


def is_api_node(value: Any) -> bool:
    """Whether a JSON object has the shape of a ComfyUI API prompt node."""
    return (
        isinstance(value, dict)
        and isinstance(value.get("class_type"), str)
        and isinstance(value.get("inputs"), dict)
    )


@dataclass(frozen=True, slots=True)
class TextHit:
    key: str  # "prompt", "workflow", "UserComment", "xmp", ...
    text: str
    source: str  # "png:tEXt", "jpeg:exif:UserComment", ...


@dataclass(slots=True)
class Scan:
    """What a format reader found, before any interpretation."""

    format: Format
    width: int
    height: int
    hits: list[TextHit] = field(default_factory=list)  # comfylens's own XMP packet excluded
    warnings: list[Warn] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)  # from comfylens's own XMP packet


@dataclass(slots=True)
class RawMetadata:
    format: Format
    width: int
    height: int
    texts: dict[str, str]  # key -> decoded text
    sources: dict[str, str]  # key -> where it came from
    kinds: dict[str, Kind]  # key -> classification
    api_prompt_key: str | None  # the key whose text is the chosen API prompt
    api_prompt: dict[str, Any] | None
    workflow_key: str | None
    workflow: dict[str, Any] | None
    warnings: list[Warn]
    tags: list[str]

    @property
    def status(self) -> Status:
        if self.api_prompt is not None:
            return "ok"
        if self.workflow is not None or "a1111" in self.kinds.values():
            return "partial"
        return "no_metadata"
