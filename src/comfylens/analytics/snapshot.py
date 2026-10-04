"""The in-memory snapshot every statistic reads.

Built at startup and after every index run, then swapped in by one reference assignment:
queries during a rebuild use the previous snapshot. Prompt frames follow in a background
thread; until they are ready `prompts` is None. A rename or trash from the UI patches the
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
from comfylens.db.connection import CatalogMissing, connect_readonly, has_fts
from comfylens.db.read import (
    FILES_SCHEMA,
    GENERATIONS_SCHEMA,
    LORAS_SCHEMA,
    files_frame,
    generations_frame,
    loras_frame,
)
from comfylens.extract.normalize import aspect
from comfylens.warn import INFORMATIONAL_CODES

NO_METADATA = "(no metadata)"  # the family of files without a generations row

NODE_INPUTS_SCHEMA = {
    "file_id": pl.Int64,
    "class_type": pl.Categorical,
    "input_name": pl.Categorical,
    "kind": pl.Categorical,
    "value_num": pl.Float64,
    "value_text": pl.String,
}


@dataclass(slots=True)
class Snapshot:
    # One row per file: file columns, every scalar generations column (null without one),
    # and derived columns megapixels, aspect, aspect_label, resolution, date, has_warnings
    # (a warning other than the informational ones).
    images: pl.DataFrame
    loras: pl.DataFrame  # reachable, enabled LoRA uses
    node_inputs: pl.DataFrame  # reachable nodes only
    fts: bool
    built_at: float
    prompts: PromptFrames | None = None
    facets_cache: dict[str, object] = field(default_factory=dict)


def empty_snapshot() -> Snapshot:
    images = _derive(
        pl.DataFrame(schema=FILES_SCHEMA).join(
            pl.DataFrame(schema=GENERATIONS_SCHEMA), left_on="id", right_on="file_id", how="left"
        ),
        set(),
    )
    return Snapshot(
        images=images,
        loras=pl.DataFrame(schema=LORAS_SCHEMA),
        node_inputs=pl.DataFrame(schema=NODE_INPUTS_SCHEMA),
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


def snapshot_from_conn(conn: sqlite3.Connection, *, with_node_inputs: bool = True) -> Snapshot:
    """Everything except prompt frames, from one read transaction's consistent catalog view.

    `with_node_inputs=False` skips the generic-input table, which only the advanced panel
    reads; the report uses this to stay cheap.
    """
    conn.execute("BEGIN")
    try:
        files = files_frame(conn)
        gens = generations_frame(conn)
        informational = sorted(INFORMATIONAL_CODES)
        warned = {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT file_id FROM warnings"
                f" WHERE code NOT IN ({','.join('?' * len(informational))})",
                informational,
            )
        }
        images = _derive(files.join(gens, left_on="id", right_on="file_id", how="left"), warned)
        return Snapshot(
            images=images,
            loras=loras_frame(conn),
            node_inputs=_node_inputs(conn)
            if with_node_inputs
            else pl.DataFrame(schema=NODE_INPUTS_SCHEMA),
            fts=has_fts(conn),
            built_at=time.time(),
        )
    finally:
        conn.execute("ROLLBACK")  # read-only: autocommit connections ignore conn.rollback()


def _derive(joined: pl.DataFrame, warned: set[int]) -> pl.DataFrame:
    sizes = joined.select("width", "height").unique().drop_nulls()
    labels = pl.DataFrame(
        [(w, h, *aspect(w, h)) for w, h in sizes.iter_rows() if h],
        schema={
            "width": pl.Int64,
            "height": pl.Int64,
            "aspect": pl.Float64,
            "aspect_label": pl.String,
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
            (pl.col("width") * pl.col("height") / 1_000_000).round(3).alias("megapixels"),
            pl.format("{}x{}", "width", "height").alias("resolution"),
            pl.col("id").is_in(list(warned)).alias("has_warnings"),
        )
        .join(labels, on=["width", "height"], how="left")
        .join(dates, on="generated_at", how="left")
        .sort("id")
    )


def _node_inputs(conn: sqlite3.Connection) -> pl.DataFrame:
    cursor = conn.execute(
        "SELECT file_id, class_type, input_name, kind, value_num, value_text"
        " FROM node_inputs WHERE reachable = 1"
    )
    frames = []
    while batch := cursor.fetchmany(200_000):
        frames.append(pl.DataFrame(batch, schema=NODE_INPUTS_SCHEMA, orient="row"))
    return pl.concat(frames) if frames else pl.DataFrame(schema=NODE_INPUTS_SCHEMA)


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
        snap.prompts = frames  # a reference assignment; readers see None or complete frames


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


def apply_removal(snap: Snapshot, ids: Collection[int]) -> None:
    """Drop removed files from `snap`, through SnapshotStore.patch.

    Prompt frames keep their rows: every prompt statistic joins them to the files in scope.
    """
    gone = pl.Series(list(ids), dtype=pl.Int64).implode()
    snap.images = snap.images.filter(~pl.col("id").is_in(gone))
    snap.loras = snap.loras.filter(~pl.col("file_id").is_in(gone))
    snap.node_inputs = snap.node_inputs.filter(~pl.col("file_id").is_in(gone))
    snap.facets_cache = {}  # after the frames: see facets()
    snap.built_at = time.time()
