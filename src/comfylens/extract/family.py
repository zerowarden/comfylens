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
        # Every key set on a condition must match; an unset key gives None here.
        loader = loader_name or ""
        checks = [
            None
            if (u := c.unet_regex) is None
            else loader_kind == "unet" and bool(u.search(loader)),
            None
            if (k := c.ckpt_regex) is None
            else loader_kind == "ckpt" and bool(k.search(loader)),
            None if c.clip_type is None else clip_type == c.clip_type,
            None if (r := c.class_regex) is None else any(r.search(t) for t in class_types),
        ]
        keys = [check for check in checks if check is not None]
        return bool(keys) and all(keys)

    return next((rule.name for rule in rules if any(map(matches, rule.any))), UNKNOWN)
