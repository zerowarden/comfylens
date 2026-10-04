"""Model family from the first matching [[families]] rule."""

from collections.abc import Collection, Sequence

from comfylens.config import FamilyCondition, FamilyRule

UNKNOWN = "unknown"


def match_family(
    rules: Sequence[FamilyRule],
    *,
    loader_kind: str | None,  # "unet" or "ckpt"
    loader_name: str | None,  # file name as in the graph
    clip_type: str | None,
    class_types: Collection[str],  # every reachable class_type
) -> str:
    def matches(c: FamilyCondition) -> bool:
        # Every key set on a condition must match.
        checks = []
        if c.unet_regex is not None:
            checks.append(loader_kind == "unet" and bool(c.unet_regex.search(loader_name or "")))
        if c.ckpt_regex is not None:
            checks.append(loader_kind == "ckpt" and bool(c.ckpt_regex.search(loader_name or "")))
        if c.clip_type is not None:
            checks.append(clip_type == c.clip_type)
        if c.class_regex is not None:
            regex = c.class_regex
            checks.append(any(regex.search(t) for t in class_types))
        return bool(checks) and all(checks)

    return next((rule.name for rule in rules if any(map(matches, rule.any))), UNKNOWN)
