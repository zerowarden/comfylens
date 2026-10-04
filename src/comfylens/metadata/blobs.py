"""Classify text payloads as API prompt, UI workflow, A1111 parameters or other."""

import json
import re
from dataclasses import dataclass
from typing import Any

from comfylens.metadata.types import MAX_TEXT_BYTES, Kind
from comfylens.warn import Code, Warn

# What a key name claims its value is. Keys from other probes ("UserComment", ...) claim nothing.
_KEY_CLAIMS: dict[str, Kind] = {
    "prompt": "api_prompt",
    "workflow": "workflow",
    "parameters": "a1111",
}
_A1111 = re.compile(r"(?:^|\n)Steps: \d+, Sampler: ")
API_NODE_SHARE = 0.8


@dataclass(slots=True)
class Classified:
    kinds: dict[str, Kind]
    api_prompt_key: str | None
    api_prompt: dict[str, Any] | None
    workflow_key: str | None
    workflow: dict[str, Any] | None
    warnings: list[Warn]


def base_key(key: str) -> str:
    """Strip the `#2` suffix that keeps repeated keys from different probes apart."""
    return key.partition("#")[0]


def is_api_node(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("class_type"), str)
        and isinstance(value.get("inputs"), dict)
    )


def shape_of(obj: Any) -> Kind:
    if isinstance(obj, dict) and obj:
        nodes = sum(1 for v in obj.values() if is_api_node(v))
        if nodes >= 1 and nodes >= API_NODE_SHARE * len(obj):
            return "api_prompt"
        if isinstance(obj.get("nodes"), list) and isinstance(obj.get("links"), list):
            return "workflow"
    return "json"


def classify(texts: dict[str, str]) -> Classified:
    kinds: dict[str, Kind] = {}
    parsed: dict[str, dict[str, Any]] = {}
    warnings: list[Warn] = []

    for key, text in texts.items():
        claim = _KEY_CLAIMS.get(base_key(key))
        if text.lstrip().startswith("{"):
            if len(text) > MAX_TEXT_BYTES:
                kinds[key] = "oversized"
                continue
            try:
                # stdlib json accepts the NaN and Infinity that ComfyUI can emit.
                obj = json.loads(text)
            except ValueError, RecursionError:
                obj = None
            kind: Kind = "text" if obj is None else shape_of(obj)
            if kind in ("api_prompt", "workflow") and isinstance(obj, dict):
                parsed[key] = obj
        elif claim == "a1111" or _A1111.search(text):
            kind = "a1111"
        else:
            kind = "text"
        kinds[key] = kind
        if claim is not None and claim != kind:
            # Trust the shape over the name.
            warnings.append(
                Warn(Code.METADATA_KEY_MISMATCH, None, f"key {key!r} holds {kind}, not {claim}")
            )

    if "a1111" in kinds.values():
        warnings.append(
            Warn(Code.UNSUPPORTED_FORMAT, None, "A1111 parameters text is stored but not parsed")
        )
    api_key = _pick(kinds, "api_prompt")
    workflow_key = _pick(kinds, "workflow")
    return Classified(
        kinds,
        api_key,
        parsed[api_key] if api_key else None,
        workflow_key,
        parsed[workflow_key] if workflow_key else None,
        warnings,
    )


def _pick(kinds: dict[str, Kind], kind: Kind) -> str | None:
    """The first key holding `kind`, preferring one whose name agrees with its shape."""
    keys = [k for k, v in kinds.items() if v == kind]
    agreeing = [k for k in keys if _KEY_CLAIMS.get(base_key(k)) == kind]
    return (agreeing or keys or [None])[0]
