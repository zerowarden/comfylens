"""The in-memory snapshot every statistic reads.

Built at startup and after every index run, then swapped in by one reference assignment:
queries during a rebuild use the previous snapshot. Prompt frames follow in a background
thread; until they are ready `prompts` is None. A rename, retag or trash from the UI patches the
current snapshot's frames in place, each by one reference assignment, instead of rebuilding.
"""

import sqlite3
import threading
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import polars as pl

from comfylens.analytics.prompts import PromptFrames, build_prompt_frames, empty_prompt_frames
from comfylens.config import Config, resolve_workers
from comfylens.db import (
    FILES_SCHEMA,
    GENERATIONS_SCHEMA,
    LORAS_SCHEMA,
    TAGS_SCHEMA,
    CatalogMissing,
    connect_readonly,
    files_frame,
    generations_frame,
    has_fts,
    loras_frame,
    tags_frame,
)
from comfylens.extract import aspect, megapixels

NO_METADATA = "(no metadata)"  # the family of files without a generations row


@dataclass(slots=True)
class Snapshot:
    # One row per file: file columns, every scalar generations column (null without one), its
    # sorted tags, and derived columns megapixels, aspect, aspect_label, resolution and date.
    images: pl.DataFrame
    loras: pl.DataFrame  # reachable, enabled LoRA uses
    fts: bool
    built_at: float
    prompts: PromptFrames | None = None
    facets_cache: dict[str, object] = field(default_factory=dict)


def empty_snapshot() -> Snapshot:
    images = _derive(
        pl.DataFrame(schema=FILES_SCHEMA),
        pl.DataFrame(schema=GENERATIONS_SCHEMA),
        pl.DataFrame(schema=TAGS_SCHEMA),
    )
    return Snapshot(
        images=images,
        loras=pl.DataFrame(schema=LORAS_SCHEMA),
        fts=False,
        built_at=time.time(),
        prompts=empty_prompt_frames(),
    )


def build_snapshot(catalog: Path) -> Snapshot:
    """Everything except prompt frames. Raises CatalogMissing without a usable catalog."""
    conn = connect_readonly(catalog)
    try:
        return snapshot_from_conn(conn)
    finally:
        conn.close()


def snapshot_from_conn(conn: sqlite3.Connection) -> Snapshot:
    """Everything except prompt frames, from one read transaction's consistent catalog view."""
    conn.execute("BEGIN")
    try:
        files = files_frame(conn)
        gens = generations_frame(conn)
        images = _derive(files, gens, tags_frame(conn))
        return Snapshot(
            images=images,
            loras=loras_frame(conn),
            fts=has_fts(conn),
            built_at=time.time(),
        )
    finally:
        conn.execute("ROLLBACK")  # read-only: autocommit connections ignore conn.rollback()


def _derive(files: pl.DataFrame, gens: pl.DataFrame, tags: pl.DataFrame) -> pl.DataFrame:
    joined = files.join(gens, left_on="id", right_on="file_id", how="left").join(
        tags, left_on="id", right_on="file_id", how="left"
    )
    sizes = joined.select("width", "height").unique().drop_nulls()
    labels = pl.DataFrame(
        [(w, h, *aspect(w, h), megapixels(w, h)) for w, h in sizes.iter_rows() if h],
        schema={
            "width": pl.Int64,
            "height": pl.Int64,
            "aspect": pl.Float64,
            "aspect_label": pl.String,
            "megapixels": pl.Float64,
        },
        orient="row",
    )
    # Day buckets use the system's local time zone, DST included.
    stamps = joined["generated_at"].drop_nulls().unique()
    dates = pl.DataFrame(
        {
            "generated_at": stamps,
            "date": [datetime.fromtimestamp(t).date() for t in stamps.to_list()],
        },
        schema={"generated_at": pl.Int64, "date": pl.Date},
    )
    return (
        joined.with_columns(
            pl.col("model_family").is_not_null().alias("has_generation"),
            pl.col("seed").cast(pl.UInt64, strict=False),
            pl.format("{}x{}", "width", "height").alias("resolution"),
            pl.col("tags").fill_null([]),
        )
        .join(labels, on=["width", "height"], how="left")
        .join(dates, on="generated_at", how="left")
        .sort("id")
    )


def prompt_rows(catalog: Path) -> list[tuple[int, str | None, str | None]]:
    conn = connect_readonly(catalog)
    try:
        return conn.execute(
            "SELECT file_id, positive_prompt, negative_prompt FROM generations"
        ).fetchall()
    finally:
        conn.close()


# An edit already committed to the catalog, applied to a snapshot in place. Applying it twice
# gives the same result as once.
Patch = Callable[[Snapshot], None]


class SnapshotStore:
    """Holds the current snapshot; rebuilds swap it in atomically, edits patch it in place.

    Neither waits for the other. A rebuild may read the catalog before or after an edit commits,
    so every patch made while it runs is applied again to its result just before the swap.
    """

    def __init__(self, catalog: Path, config: Config) -> None:
        self.catalog = catalog
        self.config = config
        self._current = empty_snapshot()
        self._building = threading.Lock()  # one rebuild at a time
        self._swap = threading.Lock()  # a patch or a swap: both take microseconds to milliseconds
        self._replay: list[Patch] | None = None  # patches made while a rebuild runs

    @property
    def current(self) -> Snapshot:
        return self._current

    def rebuild(self, *, prompts_in_background: bool = True) -> Snapshot:
        with self._building:
            with self._swap:
                self._replay = []
            try:
                try:
                    snap = build_snapshot(self.catalog)
                except CatalogMissing:
                    snap = empty_snapshot()
            except BaseException:
                with self._swap:
                    self._replay = None
                raise
            with self._swap:
                for patch in self._replay:
                    patch(snap)
                self._replay = None
                self._current = snap
        if snap.prompts is None:
            if prompts_in_background:
                threading.Thread(
                    target=self._build_prompts, args=(snap,), name="prompt-frames", daemon=True
                ).start()
            else:
                self._build_prompts(snap)
        return snap

    def patch(self, patch: Patch) -> None:
        """Apply an edit committed to the catalog to the served snapshot, and to the one a
        running rebuild is about to swap in."""
        with self._swap:
            patch(self._current)
            if self._replay is not None:
                self._replay.append(patch)

    def _build_prompts(self, snap: Snapshot) -> None:
        try:
            rows = prompt_rows(self.catalog)
        except CatalogMissing:
            rows = []
        frames = build_prompt_frames(
            rows, self.config.prompts, resolve_workers(self.config.index.workers)
        )
        # A reference assignment; readers see None or complete frames. The new built_at tells the
        # UI that prompt-frame-dependent answers (e.g. a similar-sentence filter) are now valid.
        snap.prompts = frames
        snap.built_at = time.time()


def apply_rename(snap: Snapshot, file_id: int, rel_path: str, generated_at: int) -> None:
    """Patch a renamed file into `snap`, through SnapshotStore.patch."""
    hit = pl.col("id") == file_id
    values = {
        "rel_path": rel_path,
        "generated_at": generated_at,
        "date": datetime.fromtimestamp(generated_at).date(),  # local time, as in _derive
    }
    snap.images = snap.images.with_columns(
        pl.when(hit).then(pl.lit(value)).otherwise(pl.col(name)).alias(name)
        for name, value in values.items()
    )
    snap.facets_cache = {}  # after the frames: see facets()
    snap.built_at = time.time()


def apply_tags(snap: Snapshot, tags: dict[int, list[str]]) -> None:
    """Patch retagged files into `snap`, through SnapshotStore.patch."""
    changed = pl.DataFrame(
        {"id": list(tags), "tags": list(tags.values())},
        schema={"id": pl.Int64, "tags": pl.List(pl.String)},
    )
    snap.images = snap.images.update(changed, on="id")
    snap.facets_cache = {}  # after the frames: see facets()
    snap.built_at = time.time()


def apply_removal(snap: Snapshot, ids: Collection[int]) -> None:
    """Drop removed files from `snap`, through SnapshotStore.patch.

    Prompt frames keep their rows: every prompt statistic joins them to the files in scope.
    """
    gone = pl.Series(list(ids), dtype=pl.Int64).implode()
    snap.images = snap.images.filter(~pl.col("id").is_in(gone))
    snap.loras = snap.loras.filter(~pl.col("file_id").is_in(gone))
    snap.facets_cache = {}  # after the frames: see facets()
    snap.built_at = time.time()
