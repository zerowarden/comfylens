"""Selection and filters -> the files a request covers."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

import polars as pl
from pydantic import BaseModel

from comfylens.analytics.snapshot import NO_METADATA, Snapshot
from comfylens.config import AnalysisConfig
from comfylens.metadata.types import Status

# Prompt search: text -> ids of files whose positive or negative prompt matches.
TextSearch = Callable[[str], set[int]]

NumericFilterField = Literal["steps", "cfg", "denoise", "guidance", "shift"]


class LoraFilter(BaseModel):
    names: list[str] = []
    mode: Literal["any", "all"] = "any"


class Filters(BaseModel):
    families: list[str] = []  # "(no metadata)" matches files without a generations row
    base_models: list[str] = []
    samplers: list[str] = []
    schedulers: list[str] = []
    loras: LoraFilter = LoraFilter()
    date_from: date | None = None  # inclusive, local dates of generated_at
    date_to: date | None = None
    statuses: list[Status] = []
    text: str = ""  # prompt search, both sides
    numeric: dict[NumericFilterField, tuple[float, float]] = {}  # inclusive ranges
    has_warnings: bool | None = None


class Scope(BaseModel):
    selection: list[int] = []  # non-empty: the scope as-is, filters ignored
    filters: Filters = Filters()
    pool: bool = False  # one group "all" instead of one per family


POOLED = "all"
_LIST_FILTERS = {
    "families": "model_family",
    "base_models": "base_model",
    "samplers": "sampler_name",
    "schedulers": "scheduler",
    "statuses": "status",
}


@dataclass(slots=True)
class Resolved:
    info: dict[str, Any]  # ScopeInfo
    files: pl.DataFrame  # every file in scope
    rows: pl.DataFrame  # analyzed: with a generations row, deduplicated, plus a "group" column

    def groups(self) -> list[tuple[str, pl.DataFrame]]:
        """Per family (or one pooled group), largest first; families are never mixed."""
        sizes = self.rows.group_by("group").len().sort("len", "group", descending=[True, False])
        return [(g, self.rows.filter(pl.col("group") == g)) for g in sizes["group"]]


def is_filtered(f: Filters) -> bool:
    dates = f.date_from is not None or f.date_to is not None
    lists = any(getattr(f, name) for name in _LIST_FILTERS)
    return bool(
        lists or dates or f.loras.names or f.text.strip() or f.numeric or f.has_warnings is not None
    )


def filter_files(
    snap: Snapshot, f: Filters, search: TextSearch, *, ignore_dates: bool = False
) -> pl.DataFrame:
    """Files matching every filter; empty filters mean the whole library."""
    conditions: list[pl.Expr] = []
    for name, column in _LIST_FILTERS.items():
        values: list[str] = getattr(f, name)
        if not values:
            continue
        condition = pl.col(column).is_in(values)
        if name == "families" and NO_METADATA in values:
            condition = condition | pl.col("model_family").is_null()
        conditions.append(condition)
    if not ignore_dates:
        if f.date_from is not None:
            conditions.append(pl.col("date") >= f.date_from)
        if f.date_to is not None:
            conditions.append(pl.col("date") <= f.date_to)
    for field, (low, high) in f.numeric.items():
        conditions.append(pl.col(field).is_between(low, high))
    if f.has_warnings is not None:
        conditions.append(pl.col("has_warnings") == f.has_warnings)
    if f.loras.names:
        conditions.append(
            pl.col("id").is_in(_lora_ids(snap, f.loras.names, f.loras.mode).implode())
        )
    if f.text.strip():
        conditions.append(pl.col("id").is_in(sorted(search(f.text.strip()))))
    return snap.images.filter(*conditions) if conditions else snap.images


def _lora_ids(snap: Snapshot, names: list[str], mode: str) -> pl.Series:
    uses = snap.loras.filter(pl.col("name").is_in(names))
    if mode == "all":
        wanted = len(set(names))
        uses = uses.group_by("file_id").agg(pl.col("name").n_unique().alias("n"))
        uses = uses.filter(pl.col("n") == wanted)
    return uses["file_id"].unique()


def resolve(snap: Snapshot, scope: Scope, analysis: AnalysisConfig, search: TextSearch) -> Resolved:
    if scope.selection:
        files = snap.images.filter(pl.col("id").is_in(scope.selection))
        kind = "selection"
    else:
        files = filter_files(snap, scope.filters, search)
        kind = "filtered" if is_filtered(scope.filters) else "all"

    rows = files.filter(pl.col("has_generation"))
    analyzed = rows
    if analysis.dedupe_identical_files:
        # The lowest file id per content hash; unreadable files ("" hash) are never merged.
        first = pl.col("id") == pl.col("id").min().over("content_hash")
        analyzed = rows.filter(first | (pl.col("content_hash") == ""))
    group = pl.lit(POOLED) if scope.pool else pl.col("model_family")
    analyzed = analyzed.with_columns(group.alias("group"))
    info = {
        "scope_kind": kind,
        "scope_size": files.height,
        "excluded_no_metadata": files.height - rows.height,
        "duplicates_removed": rows.height - analyzed.height,
        "analyzed": analyzed.height,
    }
    return Resolved(info, files, analyzed)
