"""Distinctive terms: what sets a selection apart from the rest of the filtered set.

Terms are ranked by the z-scored log-odds ratio with an informative Dirichlet prior (Monroe,
Colaresi & Quinn 2008, Political Analysis 16(4)). The prior is the group's whole-library term
counts scaled to alpha0 pseudo-counts; unlike raw frequency ratios, it does not over-rank
rare terms.
"""

from typing import Any, Literal

import polars as pl

from comfylens.analytics.prompts import PromptFrames, Side, document_weight, with_keys

TOP_DISTINCTIVE = 25
KINDS = {"phrases": "phrase", "unigrams": "1g", "bigrams": "2g", "trigrams": "3g"}
_EPSILON = 1e-9


def distinctive_terms(
    frames: PromptFrames,
    selection: pl.DataFrame,
    rest: pl.DataFrame,
    library: pl.DataFrame,
    side: Side,
    by: Literal["image", "unique_prompt"],
    alpha0: float,
) -> dict[str, dict[str, Any]]:
    """Lists per group. Each frame has columns id and group; `library` gives the prior.

    All groups and sides are counted in one pass over the unit frame.
    """
    roles = pl.concat(
        [
            frame.select("id", "group").with_columns(pl.lit(role).alias("role"))
            for role, frame in (("s", selection), ("r", rest), ("p", library))
        ]
    )
    keyed = with_keys(frames, roles, side)
    per_key = keyed.group_by("group", "role", "key").len("count")
    weighted = per_key.with_columns(document_weight(by).alias("w"))
    totals = {
        (g, r): int(w)
        for g, r, w in weighted.group_by("group", "role").agg(pl.col("w").sum()).iter_rows()
    }
    counts = (
        frames.units.join(weighted.select("group", "role", "key", "w"), on="key")
        .unique(["group", "role", "key", "kind", "term"])
        .group_by("group", "role", "kind", "term")
        .agg(pl.col("w").sum().alias("y"))
    )
    out = {}
    for group in selection["group"].unique().to_list():
        mine = counts.filter(pl.col("group") == group)
        counted = {
            role: mine.filter(pl.col("role") == role).select(
                "kind", "term", pl.col("y").alias(f"y_{role}")
            )
            for role in ("s", "r", "p")
        }
        sizes = {role: totals.get((group, role), 0) for role in ("s", "r", "p")}
        block: dict[str, Any] = {"selection_images": sizes["s"], "rest_images": sizes["r"]}
        for label, kind in KINDS.items():
            block[label] = _rank(counted, sizes, kind, alpha0)
        out[group] = block
    return out


def _rank(
    counted: dict[str, pl.DataFrame], totals: dict[str, int], kind: str, alpha0: float
) -> dict[str, list[dict[str, Any]]]:
    s, r, p = (counted[n].filter(pl.col("kind") == kind).drop("kind") for n in ("s", "r", "p"))
    n_s, n_r, n_p = (float(f[f"y_{n}"].sum()) for f, n in ((s, "s"), (r, "r"), (p, "p")))
    if n_p == 0:
        return {"selection": [], "rest": []}
    ys, yr = pl.col("y_s"), pl.col("y_r")
    # alpha_w: the term's share of the library, scaled to alpha0 pseudo-counts.
    alpha = (pl.col("y_p") / n_p * alpha0).clip(lower_bound=_EPSILON)
    scored = (
        s.join(r, on="term", how="full", coalesce=True)
        .join(p, on="term", how="left")
        .with_columns(pl.col("y_s", "y_r", "y_p").fill_null(0))
        .with_columns(alpha.alias("a"))
        .with_columns(
            (
                ((ys + pl.col("a")) / (n_s + alpha0 - ys - pl.col("a")).clip(_EPSILON)).log()
                - ((yr + pl.col("a")) / (n_r + alpha0 - yr - pl.col("a")).clip(_EPSILON)).log()
            ).alias("delta"),
            (1 / (ys + pl.col("a")) + 1 / (yr + pl.col("a"))).alias("variance"),
        )
        .with_columns((pl.col("delta") / pl.col("variance").sqrt()).alias("z"))
    )

    def rows(frame: pl.DataFrame) -> list[dict[str, Any]]:
        return [
            {
                "term": term,
                "z": z,
                "selection_df": y_s,
                "selection_share": y_s / totals["s"] if totals["s"] else 0.0,
                "rest_df": y_r,
                "rest_share": y_r / totals["r"] if totals["r"] else 0.0,
            }
            for term, z, y_s, y_r in frame.select("term", "z", "y_s", "y_r").iter_rows()
        ]

    more_in_selection = scored.filter((pl.col("z") > 0) & (ys > 0))
    more_in_rest = scored.filter((pl.col("z") < 0) & (yr > 0))
    return {
        "selection": rows(
            more_in_selection.sort("z", "term", descending=[True, False]).head(TOP_DISTINCTIVE)
        ),
        "rest": rows(more_in_rest.sort("z", "term").head(TOP_DISTINCTIVE)),
    }
