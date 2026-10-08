"""Classify text payloads as API prompt, UI workflow, A1111 parameters or other."""

import json
import re
from dataclasses import dataclass
from typing import Any

from comfylens.metadata.types import MAX_TEXT_BYTES, Kind, is_api_node
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


def shape_of(obj: Any) -> Kind:
    if isinstance(obj, dict) and obj:
        nodes = sum(1 for v in obj.values() if is_api_node(v))
        if nodes >= 1 and nodes >= API_NODE_SHARE * len(obj):
            return "api_prompt"
        if isinstance(obj.get("nodes"), list) and isinstance(obj.get("links"), list):
            return "workflow"
    return "json"


def classify(texts: dict[str, str]) -> Classified:
    read = {key: _read(key, text) for key, text in texts.items()}
    kinds: dict[str, Kind] = {key: kind for key, (kind, _) in read.items()}
    # Trust the shape over the name.
    warnings = [
        Warn(Code.METADATA_KEY_MISMATCH, None, f"key {key!r} holds {kind}, not {claim}")
        for key, kind in kinds.items()
        if (claim := _KEY_CLAIMS.get(base_key(key))) not in (None, kind) and kind != "oversized"
    ]
    if "a1111" in kinds.values():
        warnings.append(
            Warn(Code.UNSUPPORTED_FORMAT, None, "A1111 parameters text is stored but not parsed")
        )
    api_key = _pick(kinds, "api_prompt")
    workflow_key = _pick(kinds, "workflow")
    return Classified(
        kinds,
        api_key,
        read[api_key][1] if api_key else None,
        workflow_key,
        read[workflow_key][1] if workflow_key else None,
        warnings,
    )


def _read(key: str, text: str) -> tuple[Kind, dict[str, Any] | None]:
    """A text's kind, and its JSON object when that is an API prompt or a workflow."""
    if not text.lstrip().startswith("{"):
        a1111 = _KEY_CLAIMS.get(base_key(key)) == "a1111" or _A1111.search(text)
        return ("a1111" if a1111 else "text"), None
    if len(text) > MAX_TEXT_BYTES:
        return "oversized", None
    obj = _json(text)
    kind: Kind = "text" if obj is None else shape_of(obj)
    return kind, obj if kind in ("api_prompt", "workflow") else None


def _json(text: str) -> Any:
    try:
        # stdlib json accepts the NaN and Infinity that ComfyUI can emit.
        return json.loads(text)
    except ValueError, RecursionError:
        return None


def _pick(kinds: dict[str, Kind], kind: Kind) -> str | None:
    """The first key holding `kind`, preferring one whose name agrees with its shape."""
    keys = [k for k, v in kinds.items() if v == kind]
    agreeing = [k for k in keys if _KEY_CLAIMS.get(base_key(k)) == kind]
    return (agreeing or keys or [None])[0]
