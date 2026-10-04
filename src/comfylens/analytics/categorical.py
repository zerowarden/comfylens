from typing import Any

import polars as pl

REPEATED_SEEDS = 10


def value_counts(values: pl.Series, top_n: int) -> dict[str, Any]:
    """The top_n values with count and share of all files, plus other and missing buckets."""
    total = values.len()
    missing = values.null_count()
    counts = (
        values.drop_nulls()
        .cast(pl.String)
        .alias("value")
        .value_counts()
        .sort("count", "value", descending=[True, False])
    )
    top = counts.head(top_n)
    return {
        "n": total - missing,
        "values": [
            {"value": v, "count": c, "share": c / total}
            for v, c in top.select("value", "count").iter_rows()
        ],
        "other": int(counts["count"].sum()) - int(top["count"].sum()),
        "missing": missing,
    }


def seed_stats(seeds: pl.Series) -> dict[str, Any]:
    """Seeds are identifiers: count distinct values and repeats, never average them."""
    s = seeds.drop_nulls()
    counts = s.alias("seed").value_counts().filter(pl.col("count") >= 2)
    repeated = counts.sort("count", "seed", descending=[True, False]).head(REPEATED_SEEDS)
    return {
        "n": s.len(),
        "n_unique": s.n_unique(),
        "repeated": [{"seed": str(v), "count": c} for v, c in repeated.iter_rows()],
    }
