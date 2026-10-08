from dataclasses import asdict
from typing import Any, Literal

import polars as pl

from comfylens.analytics.numeric import HistogramSpec, numeric_stats

# LoRAs are grouped by file name, or by base name across versions.
LoraKey = Literal["name", "base_name"]

EXAMPLES = 6


def lora_table(
    uses: pl.DataFrame,
    group_size: int,
    key: LoraKey,
    round_decimals: int,
    histogram: HistogramSpec,
) -> list[dict[str, Any]]:
    """Per LoRA: how many files use it, and strength statistics over those files only.

    Counting non-users as strength zero would mix up how often with how strong.
    """
    ranked = (
        uses.group_by(key)
        .agg(pl.col("file_id").n_unique().alias("images"))
        .sort("images", key, descending=[True, False])
    )
    rows = []
    for name, images in ranked.iter_rows():
        mine = uses.filter(pl.col(key) == name)
        clip = mine["strength_clip"]
        rows.append(
            {
                "name": name,
                "images": images,
                "share": images / group_size,
                "strength_model": asdict(
                    numeric_stats(mine["strength_model"], round_decimals, histogram)
                ),
                "strength_clip": asdict(numeric_stats(clip, round_decimals, histogram))
                if clip.null_count() < clip.len()
                else None,
                "positions": _int_counts(mine["position"]),
                "steps": _int_counts(mine["step"]) if key == "base_name" else None,
            }
        )
    return rows


def _int_counts(values: pl.Series) -> list[dict[str, Any]]:
    counts = values.alias("value").value_counts().sort("count", "value", descending=[True, False])
    return [{"value": v, "count": c} for v, c in counts.iter_rows()]


def recent_examples(column: str) -> pl.Expr:
    """`column`, most recent first, ties by file id: one rule for every example list."""
    return pl.col(column).sort_by(["generated_at", "id"], descending=[True, True], nulls_last=True)


def top_values(rows: pl.DataFrame, column: str, top_n: int) -> pl.DataFrame:
    """Value counts of `column` with up to 6 example ids and hashes each, most recent first."""
    return (
        rows.filter(pl.col(column).is_not_null())
        .group_by(column)
        .agg(
            pl.len().alias("count"),
            recent_examples("id").head(EXAMPLES).alias("examples"),
            recent_examples("content_hash").head(EXAMPLES).alias("example_hashes"),
        )
        .sort("count", column, descending=[True, False])
        .head(top_n)
    )
