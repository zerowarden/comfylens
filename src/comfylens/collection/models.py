"""Models and constants shared by the API, the collection archive, the store and analytics."""

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

Role = Literal["reference", "attempt"]
OriginalFormat = Literal["png", "jpeg", "webp"]

# A content hash: xxh3-128 as 32 lowercase hex digits. Thumbnails and originals are named by it.
HASH_RE = r"[0-9a-f]{32}"
HASH_PATTERN = f"^{HASH_RE}$"
Hash = Annotated[str, Field(pattern=HASH_PATTERN)]
EXTENSIONS: dict[str, str] = {"png": "png", "jpeg": "jpg", "webp": "webp"}
MAX_TITLE = 200
MAX_TAG = 40


class SavedLora(BaseModel):
    name: str
    strength_model: float | None = None
    strength_clip: float | None = None


class PromptSettings(BaseModel):
    """Generation settings as far as they are known; every field may be missing."""

    base_model: str | None = None
    seed: str | None = None  # up to 2**64 - 1
    steps: int | None = None
    cfg: float | None = None
    sampler_name: str | None = None
    scheduler: str | None = None
    denoise: float | None = None
    guidance: float | None = None
    shift: float | None = None
    loras: list[SavedLora] = []


# The scalar keys of a settings mapping, in presentation order; `loras` is the list beside them.
PROMPT_SETTING_KEYS: tuple[str, ...] = tuple(PromptSettings.model_fields)  # type: ignore[attr-defined]
SAVED_LORA_KEYS: tuple[str, ...] = tuple(SavedLora.model_fields)  # type: ignore[attr-defined]


def saved_lora(
    name: str, strength_model: float | None, strength_clip: float | None
) -> dict[str, Any]:
    """A SavedLora as the plain dict drafts and archives carry."""
    return {"name": name, "strength_model": strength_model, "strength_clip": strength_clip}


@dataclass(frozen=True, slots=True)
class Links:
    """What ties a saved prompt to library files, as of one store revision."""

    revision: int
    hashes: frozenset[str]  # references and attempts
    key: int | None  # prompt_key of the positive prompt
