"""Filter options with counts over the whole library (GET /api/facets)."""

from typing import Any

import polars as pl

from comfylens.analytics.snapshot import NO_METADATA, Snapshot

RANGE_FIELDS = ("steps", "cfg", "denoise", "guidance", "shift")


def _counts(values: pl.Series) -> list[dict[str, Any]]:
    counts = values.drop_nulls().alias("value").value_counts()
    counts = counts.sort("count", "value", descending=[True, False])
    return [{"value": str(v), "count": c} for v, c in counts.iter_rows()]


def facets(snap: Snapshot) -> dict[str, Any]:
    # Read the cache before the frames: an edit patches the frames, then replaces the cache, so
    # a result computed from frames older than this cache can only land in a discarded one.
    cache = snap.facets_cache
    cached = cache.get("facets")
    if cached is not None:
        return cached  # type: ignore[return-value]
    images = snap.images
    gens = images.filter(pl.col("has_generation"))
    lora_files = snap.loras.group_by("name").agg(pl.col("file_id").n_unique().alias("count"))
    result = {
        "families": _counts(images["model_family"].fill_null(NO_METADATA)),
        "base_models": _counts(gens["base_model"]),
        "samplers": _counts(gens["sampler_name"]),
        "schedulers": _counts(gens["scheduler"]),
        "loras": [
            {"value": n, "count": c}
            for n, c in lora_files.sort("count", "name", descending=[True, False]).iter_rows()
        ],
        "statuses": _counts(images["status"]),
        "date_range": {"min": images["date"].min(), "max": images["date"].max()},
        "numeric_ranges": {
            name: {"min": gens[name].min(), "max": gens[name].max()} for name in RANGE_FIELDS
        },
    }
    cache["facets"] = result
    return result
