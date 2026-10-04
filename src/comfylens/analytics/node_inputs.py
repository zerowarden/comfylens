"""Statistics over every literal node input, including parameters no extractor covers."""

from dataclasses import asdict
from typing import Any

import polars as pl

from comfylens.analytics.categorical import value_counts
from comfylens.analytics.numeric import HistogramSpec, numeric_stats
from comfylens.analytics.scope import Resolved
from comfylens.analytics.snapshot import Snapshot

LONG_TEXT = 200  # longer strings report only their number of distinct values


def input_keys(snap: Snapshot, resolved: Resolved) -> list[dict[str, Any]]:
    rows = snap.node_inputs.filter(pl.col("file_id").is_in(resolved.rows["id"].implode()))
    keys = (
        rows.group_by("class_type", "input_name", "kind")
        .agg(pl.col("file_id").n_unique().alias("files"))
        .sort("files", "class_type", "input_name", descending=[True, False, False])
    )
    return [
        {"class_type": str(c), "input_name": str(i), "kind": str(k), "files": f}
        for c, i, k, f in keys.iter_rows()
    ]


def input_stats(
    snap: Snapshot,
    resolved: Resolved,
    class_type: str,
    input_name: str,
    *,
    round_decimals: int,
    top_n: int,
    histogram: HistogramSpec,
) -> list[dict[str, Any]]:
    """One block per group. Several nodes of the class in one file each count once."""
    key_rows = snap.node_inputs.filter(
        (pl.col("class_type") == class_type) & (pl.col("input_name") == input_name)
    )
    out = []
    for group, rows in resolved.groups():
        mine = key_rows.filter(pl.col("file_id").is_in(rows["id"].implode()))
        if mine.height == 0:
            continue
        # A key can hold several kinds across files (e.g. a number or null); use the commonest.
        kind = str(mine["kind"].value_counts(sort=True)["kind"][0])
        mine = mine.filter(pl.col("kind") == kind)
        block: dict[str, Any] = {"family": group, "files": mine["file_id"].n_unique(), "kind": kind}
        if kind == "num":
            block["numeric"] = asdict(numeric_stats(mine["value_num"], round_decimals, histogram))
        elif kind == "bool":
            labels = mine["value_num"].map_elements(lambda v: "true" if v else "false", pl.String)
            block["categorical"] = value_counts(labels, top_n)
        elif (mine["value_text"].str.len_chars().max() or 0) > LONG_TEXT:  # type: ignore[operator]
            block["n_unique"] = mine["value_text"].n_unique()
        else:
            block["categorical"] = value_counts(mine["value_text"], top_n)
        out.append(block)
    return out
