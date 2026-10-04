"""Models shared by the API and the collection archive."""

from pydantic import BaseModel


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
