"""Derived keys stored per file."""

import json
from typing import Any

import xxhash

from comfylens.extract.normalize import round_key
from comfylens.extract.types import LoraUse, SamplerStage

NO_LORAS = "(none)"
# Joins LoRA stacks and the stage families of a multi-model pipeline.
CHAIN_SEPARATOR = " + "
# Field order of config_key.
CONFIG_KEY_FIELDS = (
    "model_family",
    "base_model",
    "lora_stack_key",
    "sampler_name",
    "scheduler",
    "steps",
    "cfg",
    "denoise",
    "guidance",
    "shift",
)


def _num(x: float | None, decimals: int) -> float | None:
    return None if x is None else round_key(x, decimals)


def lora_stack_key(loras: list[LoraUse], decimals: int) -> str:
    """Reachable, enabled LoRAs in position order as `name@strength`."""
    stack = sorted(
        (u for u in loras if u.reachable and u.enabled and u.position is not None),
        key=lambda u: u.position or 0,
    )
    parts = [f"{u.name}@{_fmt(_num(u.strength_model, decimals))}" for u in stack]
    return CHAIN_SEPARATOR.join(parts) or NO_LORAS


def _fmt(x: float | None) -> str:
    return "?" if x is None else repr(x)


def config_key(
    family: str,
    base_model: str | None,
    stack_key: str,
    primary: SamplerStage | None,
    guidance: float | None,
    shift: float | None,
    decimals: int,
) -> str:
    """Canonical JSON array that drives the top-configurations table."""
    p = primary
    fields: list[Any] = [
        family,
        base_model,
        stack_key,
        p and p.sampler_name,
        p and p.scheduler,
        p and p.steps,
        _num(p and p.cfg, decimals),
        _num(p and p.denoise, decimals),
        _num(guidance, decimals),
        _num(shift, decimals),
    ]
    return json.dumps(fields, ensure_ascii=False, separators=(",", ":"))


def decode_config_key(key: str) -> dict[str, Any]:
    return dict(zip(CONFIG_KEY_FIELDS, json.loads(key), strict=True))


def generation_key(api_prompt: dict[str, Any]) -> str:
    """Shared by all images of one batch; the timestamp burst check relies on that."""
    canonical = json.dumps(api_prompt, sort_keys=True, separators=(",", ":"))
    return xxhash.xxh3_64_hexdigest(canonical.encode())
