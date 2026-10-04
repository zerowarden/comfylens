"""Data passed from the format readers to blob classification."""

from dataclasses import dataclass, field
from typing import Any, Literal

from comfylens.warn import Warn

Format = Literal["png", "jpeg"]
Status = Literal["ok", "partial", "no_metadata", "error"]
# How a text value was classified: see blobs.classify.
Kind = Literal["api_prompt", "workflow", "a1111", "json", "text", "oversized"]

# Metadata is untrusted: larger payloads are never inflated or parsed.
MAX_TEXT_BYTES = 50 * 1024 * 1024


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
    hits: list[TextHit] = field(default_factory=list)
    warnings: list[Warn] = field(default_factory=list)


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

    @property
    def status(self) -> Status:
        if self.api_prompt is not None:
            return "ok"
        if self.workflow is not None or "a1111" in self.kinds.values():
            return "partial"
        return "no_metadata"
