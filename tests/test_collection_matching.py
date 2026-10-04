import polars as pl

from comfylens.analytics.collection import (
    hash_matches,
    keyed_files,
    library_counts,
    library_ids,
)
from comfylens.analytics.prompts import PromptFrames, empty_prompt_frames
from comfylens.analytics.snapshot import Snapshot, apply_removal, empty_snapshot
from comfylens.collection.store import Links

FOX, OWL = 11, 22  # prompt keys


def snapshot(files: list[tuple[int, str, int | None]]) -> Snapshot:
    """(id, content_hash, positive prompt key) per file."""
    snap = empty_snapshot()
    snap.images = pl.DataFrame(
        {"id": [f[0] for f in files], "content_hash": [f[1] for f in files]},
        schema={"id": pl.Int64, "content_hash": pl.String},
    )
    empty = empty_prompt_frames()
    snap.prompts = PromptFrames(
        pl.DataFrame(
            {
                "file_id": [f[0] for f in files],
                "positive": [f[2] for f in files],
                "negative": [None] * len(files),
            },
            schema={"file_id": pl.Int64, "positive": pl.UInt64, "negative": pl.UInt64},
        ),
        empty.texts,
        empty.sentences,
        empty.units,
    )
    return snap


def test_counts_union_hashes_and_prompt_keys():
    snap = snapshot([(1, "a", FOX), (2, "b", FOX), (3, "a", OWL), (4, "", None), (5, "c", None)])
    links = {
        100: Links(1, frozenset({"a"}), FOX),  # 1, 3 by hash; 1, 2 by key
        200: Links(1, frozenset({"c", "zz"}), None),
        300: Links(1, frozenset(), 2**64 - 1),  # a key no file has, beyond Int64
    }
    assert library_counts(snap, links) == {100: 3, 200: 1, 300: 0}
    assert library_ids(snap, {"a", "c", "zz"}) == {"a": [1, 3], "c": [5]}
    assert sorted(hash_matches(snap, {"a"})["id"].to_list()) == [1, 3]


def test_removed_files_never_match():
    snap = snapshot([(1, "a", FOX), (2, "b", FOX)])
    apply_removal(snap, [2])
    keyed = keyed_files(snap)
    assert keyed is not None and keyed["file_id"].to_list() == [1]
    assert library_counts(snap, {7: Links(1, frozenset({"b"}), FOX)}) == {7: 1}


def test_counts_wait_for_prompt_frames():
    snap = snapshot([(1, "a", FOX)])
    snap.prompts = None
    assert keyed_files(snap) is None
    assert library_counts(snap, {7: Links(1, frozenset({"a"}), None)}) is None
