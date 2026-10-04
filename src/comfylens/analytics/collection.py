"""Saved prompts against the served library: which files belong to a saved prompt.

A file belongs to a saved prompt when its content hash is linked to it (as reference or attempt)
or when its positive prompt is the same text, whitespace aside (the same prompt key).
"""

from collections.abc import Collection, Mapping

import polars as pl

from comfylens.analytics.snapshot import Snapshot
from comfylens.collection.store import Links


def hash_matches(snap: Snapshot, hashes: Collection[str]) -> pl.DataFrame:
    """id and content_hash of the served files with one of `hashes`."""
    wanted = pl.Series(sorted(hashes), dtype=pl.String).implode()
    return snap.images.filter(pl.col("content_hash").is_in(wanted)).select("id", "content_hash")


def keyed_files(snap: Snapshot) -> pl.DataFrame | None:
    """file_id and positive prompt key of every served file; None until prompt frames exist.

    Prompt frames keep the rows of trashed files, so they are joined to the snapshot's files.
    """
    if snap.prompts is None:
        return None
    present = snap.images.select(pl.col("id").alias("file_id"))
    return (
        snap.prompts.file_keys.select("file_id", "positive")
        .drop_nulls()
        .join(present, on="file_id", how="semi")
    )


def library_counts(snap: Snapshot, links: Mapping[int, Links]) -> dict[int, int] | None:
    """Per saved prompt, how many served files belong to it; None until prompt frames exist."""
    keyed = keyed_files(snap)
    if keyed is None:
        return None
    by_key = pl.DataFrame(
        [(pid, link.key) for pid, link in links.items() if link.key is not None],
        schema={"prompt_id": pl.Int64, "positive": pl.UInt64},
        orient="row",
    ).join(keyed, on="positive")
    by_hash = pl.DataFrame(
        [(pid, h) for pid, link in links.items() for h in link.hashes],
        schema={"prompt_id": pl.Int64, "content_hash": pl.String},
        orient="row",
    ).join(snap.images.select(pl.col("id").alias("file_id"), "content_hash"), on="content_hash")
    pairs = pl.concat([frame.select("prompt_id", "file_id") for frame in (by_key, by_hash)])
    counts = dict.fromkeys(links, 0)
    counts.update(pairs.unique().group_by("prompt_id").len().iter_rows())
    return counts


def library_ids(snap: Snapshot, hashes: Collection[str]) -> dict[str, list[int]]:
    """Served file ids per content hash, ascending."""
    out: dict[str, list[int]] = {}
    for file_id, content_hash in hash_matches(snap, hashes).sort("id").iter_rows():
        out.setdefault(content_hash, []).append(file_id)
    return out
