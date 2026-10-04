"""Images per day, week or month, stacked by family."""

from datetime import date, timedelta
from typing import Any, Literal

import polars as pl

from comfylens.analytics.snapshot import NO_METADATA

Bucket = Literal["day", "week", "month"]


def _bucket_start(bucket: Bucket) -> pl.Expr:
    d = pl.col("date")
    if bucket == "week":
        return d - pl.duration(days=d.dt.weekday() - 1)  # Monday
    if bucket == "month":
        return d.dt.truncate("1mo")
    return d


def _all_buckets(first: date, last: date, bucket: Bucket) -> list[date]:
    out, current = [], first
    while current <= last:
        out.append(current)
        if bucket == "day":
            current += timedelta(days=1)
        elif bucket == "week":
            current += timedelta(days=7)
        else:
            current = date(current.year + current.month // 12, current.month % 12 + 1, 1)
    return out


def timeline(base: pl.DataFrame, selected: pl.DataFrame | None, bucket: Bucket) -> dict[str, Any]:
    """`base` is the filtered set with its date filter removed, so the brush can widen again.

    `selected` holds the selected files when a selection exists.
    """
    dated = base.filter(pl.col("date").is_not_null()).with_columns(
        _bucket_start(bucket).alias("bucket"),
        pl.col("model_family").fill_null(NO_METADATA).alias("family"),
    )
    if dated.height == 0:
        return {
            "bucket": bucket,
            "buckets": [],
            "series": {},
            "suspect": [],
            "selected": [] if selected is not None else None,
            "date_min": None,
            "date_max": None,
        }
    buckets = _all_buckets(dated["bucket"].min(), dated["bucket"].max(), bucket)  # type: ignore[arg-type]
    index = {b: i for i, b in enumerate(buckets)}

    def aligned(frame: pl.DataFrame) -> list[int]:
        counts = [0] * len(buckets)
        for b, n in frame.group_by("bucket").len().iter_rows():
            if b in index:
                counts[index[b]] = n
        return counts

    families = dated.group_by("family").len().sort("len", "family", descending=[True, False])
    series = {f: aligned(dated.filter(pl.col("family") == f)) for f in families["family"]}
    chosen = None
    if selected is not None:
        chosen = aligned(
            selected.filter(pl.col("date").is_not_null()).with_columns(
                _bucket_start(bucket).alias("bucket")
            )
        )
    return {
        "bucket": bucket,
        "buckets": buckets,
        "series": series,
        "suspect": aligned(dated.filter(pl.col("timestamp_suspect"))),
        "selected": chosen,
        "date_min": dated["date"].min(),
        "date_max": dated["date"].max(),
    }
