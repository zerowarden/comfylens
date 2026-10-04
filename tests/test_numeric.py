import math

import polars as pl

from comfylens.analytics.categorical import seed_stats, value_counts
from comfylens.analytics.numeric import HistogramSpec, numeric_stats


def stats(values, decimals=4):
    return numeric_stats(pl.Series(values, dtype=pl.Float64), decimals)


def test_basic_statistics():
    s = stats([20, 20, 30, 30, 30, None, float("nan")])
    assert (s.n, s.n_missing) == (5, 2)
    assert (s.mode, s.mode_tied, s.mode_share) == ([30.0], False, 0.6)
    assert (s.median, s.mean, s.min, s.max) == (30.0, 26.0, 20.0, 30.0)
    assert (s.p25, s.p75) == (20.0, 30.0)
    assert math.isclose(s.std or 0, 5.477225575051661)


def test_mode_ties_report_up_to_three_ascending():
    s = stats([4, 3, 2, 1, 4, 3, 2, 1])
    assert (s.mode, s.mode_tied, s.mode_share) == ([1.0, 2.0, 3.0], True, 0.25)


def test_no_repeated_value():
    s = stats([1.0, 2.0, 3.5])
    assert (s.mode, s.mode_note, s.mode_share) == ([], "no repeated value", None)
    assert s.median == 2.0


def test_mode_rounds_but_median_does_not():
    s = stats([1.13000001, 1.13, 1.2], decimals=2)
    assert s.mode == [1.13]
    assert s.median == 1.13000001  # unrounded


def test_single_and_empty():
    one = stats([7])
    assert (one.mode, one.mode_share, one.std, one.p25) == ([7.0], 1.0, None, 7.0)
    empty = stats([None, None])
    assert (empty.n, empty.n_missing, empty.mode, empty.median) == (0, 2, [], None)


def test_negative_zero_mode():
    assert stats([-0.00001, 0.0], decimals=2).mode == [0.0]


def test_discrete_histogram_has_one_bar_per_value():
    s = numeric_stats(pl.Series([20.0, 20.0, 30.0, 25.00001]), 4, HistogramSpec(25, 20))
    assert s.histogram == {
        "kind": "discrete",
        "bars": [
            {"x0": 20.0, "x1": 20.0, "count": 2},
            {"x0": 25.0, "x1": 25.0, "count": 1},
            {"x0": 30.0, "x1": 30.0, "count": 1},
        ],
    }


def test_binned_histogram_covers_min_to_max():
    s = numeric_stats(pl.Series([float(v) for v in range(100)]), 4, HistogramSpec(25, 4))
    assert s.histogram is not None and s.histogram["kind"] == "bins"
    bars = s.histogram["bars"]
    assert [b["count"] for b in bars] == [25, 25, 25, 25]  # type: ignore[index]
    assert (bars[0]["x0"], bars[-1]["x1"]) == (0.0, 99.0)  # type: ignore[index]


def test_categorical_other_and_missing():
    counts = value_counts(pl.Series(["a", "a", "b", "c", None]), top_n=2)
    assert counts == {
        "n": 4,
        "values": [
            {"value": "a", "count": 2, "share": 0.4},
            {"value": "b", "count": 1, "share": 0.2},
        ],
        "other": 1,
        "missing": 1,
    }


def test_seeds_count_repeats_only():
    stats = seed_stats(pl.Series([5, 5, 7, 2**64 - 1, 2**64 - 1, 2**64 - 1], dtype=pl.UInt64))
    assert stats == {
        "n": 6,
        "n_unique": 3,
        "repeated": [{"seed": "18446744073709551615", "count": 3}, {"seed": "5", "count": 2}],
    }
