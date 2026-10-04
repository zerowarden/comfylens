from dataclasses import dataclass, field

import polars as pl

MAX_TIED_MODES = 3


@dataclass(frozen=True, slots=True)
class HistogramSpec:
    discrete_max_distinct: int  # this many distinct values or fewer: one bar per value
    bins: int  # otherwise equal-width bins over [min, max]


@dataclass(slots=True)
class NumericStats:
    n: int
    n_missing: int
    # Most frequent value(s) after rounding: up to 3 ascending when tied, [] when no value
    # repeats (with mode_note) or n == 0.
    mode: list[float] = field(default_factory=list)
    mode_tied: bool = False
    mode_note: str | None = None
    mode_share: float | None = None
    median: float | None = None  # interpolated, on unrounded values
    mean: float | None = None
    std: float | None = None  # sample standard deviation, n >= 2
    min: float | None = None
    p25: float | None = None
    p75: float | None = None
    max: float | None = None
    histogram: dict[str, object] | None = None  # {"kind", "bars": [{x0, x1, count}]}


def numeric_stats(
    values: pl.Series, round_decimals: int, histogram: HistogramSpec | None = None
) -> NumericStats:
    s = values.cast(pl.Float64).fill_nan(None)
    n_missing = s.null_count()
    s = s.drop_nulls()
    n = s.len()
    if n == 0:
        return NumericStats(0, n_missing)

    # Polars groups -0.0 with 0.0 but may report -0.0; `+ 0.0` below fixes that.
    rounded = s.round(round_decimals).alias("value")
    counts = rounded.value_counts(sort=True)
    top = int(counts["count"][0])
    out = NumericStats(n, n_missing)
    if top == 1 and n > 1:
        out.mode_note = "no repeated value"
    else:
        tied = sorted(v + 0.0 for v in counts.filter(pl.col("count") == top)["value"])
        out.mode, out.mode_tied, out.mode_share = tied[:MAX_TIED_MODES], len(tied) > 1, top / n

    out.median = _float(s.median())
    out.mean = _float(s.mean())
    out.std = _float(s.std(ddof=1)) if n >= 2 else None
    out.min, out.max = _float(s.min()), _float(s.max())
    out.p25 = _float(s.quantile(0.25, interpolation="linear"))
    out.p75 = _float(s.quantile(0.75, interpolation="linear"))
    if histogram is not None:
        out.histogram = _histogram(counts, out.min or 0.0, out.max or 0.0, histogram)
    return out


def _histogram(
    counts: pl.DataFrame, low: float, high: float, spec: HistogramSpec
) -> dict[str, object]:
    """`counts` are value counts of the rounded values."""
    if counts.height <= spec.discrete_max_distinct:
        bars = [
            {"x0": v + 0.0, "x1": v + 0.0, "count": c}
            for v, c in counts.sort("value").select("value", "count").iter_rows()
        ]
        return {"kind": "discrete", "bars": bars}
    width = (high - low) / spec.bins
    index = ((pl.col("value") - low) / width).floor().cast(pl.Int64).clip(0, spec.bins - 1)
    per_bin = dict(
        counts.group_by(index.alias("bin"))
        .agg(pl.col("count").sum())
        .select("bin", "count")
        .iter_rows()
    )
    bars = [
        {"x0": low + i * width, "x1": low + (i + 1) * width, "count": per_bin.get(i, 0)}
        for i in range(spec.bins)
    ]
    return {"kind": "bins", "bars": bars}


def _float(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]
