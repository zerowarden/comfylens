"""Selection and filters -> the files a request covers."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, Literal, Protocol

import polars as pl
from pydantic import BaseModel, Field

from comfylens.analytics.collection import has_hash
from comfylens.analytics.snapshot import NO_METADATA, Snapshot
from comfylens.config import AnalysisConfig
from comfylens.metadata import Status


class Lookup(Protocol):
    """What filters need beyond the snapshot: prompt search and the saved-prompt collection."""

    def search(self, text: str) -> set[int]:
        """Ids of files whose positive or negative prompt contains `text`."""
        ...

    def saved_hashes(self) -> frozenset[str]:
        """Content hashes linked to any saved prompt."""
        ...

    def saved_prompt_ids(self, prompt_id: int) -> set[int]:
        """Ids of files linked to the saved prompt or sharing its positive prompt."""
        ...

    def sentence_ids(self, hashes: set[int]) -> set[int]:
        """Ids of files whose positive or negative prompt holds one of these sentences."""
        ...


class _NoLookup:
    def search(self, text: str) -> set[int]:
        return set()

    def saved_hashes(self) -> frozenset[str]:
        return frozenset()

    def saved_prompt_ids(self, prompt_id: int) -> set[int]:
        return set()

    def sentence_ids(self, hashes: set[int]) -> set[int]:
        return set()


NO_LOOKUP: Lookup = _NoLookup()  # matches nothing: for callers without a server

NumericFilterField = Literal["steps", "cfg", "denoise", "guidance", "shift"]
# A segmented sentence's xxh3_64 hash as 16 lowercase hex digits.
SentenceKey = Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")]


class LoraFilter(BaseModel):
    names: list[str] = []
    mode: Literal["any", "all"] = "any"


class Filters(BaseModel):
    tags: list[str] = []  # files holding any of them
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
    saved: bool | None = None  # content hash linked to any saved prompt (or to none)
    saved_prompt: int | None = None  # one saved prompt's files: linked, or the same prompt
    sentences: list[SentenceKey] = []  # similar-sentence cluster: the member sentence hashes


class Scope(BaseModel):
    selection: list[int] = []  # non-empty: the scope as-is, filters ignored
    filters: Filters = Filters()


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
        """Per family, largest first; families are never mixed."""
        sizes = self.rows.group_by("group").len().sort("len", "group", descending=[True, False])
        return [(g, self.rows.filter(pl.col("group") == g)) for g in sizes["group"]]


def is_filtered(f: Filters) -> bool:
    # Blank search text, and a LoRA mode without LoRAs, filter nothing.
    loras = f.loras if f.loras.names else LoraFilter()
    return f.model_copy(update={"text": f.text.strip(), "loras": loras}) != Filters()


def filter_files(
    snap: Snapshot, f: Filters, lookup: Lookup, *, ignore_dates: bool = False
) -> pl.DataFrame:
    """Files matching every filter; empty filters mean the whole library."""
    if ignore_dates:
        f = f.model_copy(update={"date_from": None, "date_to": None})
    conditions = [
        *(
            _in_list(column, values)
            for name, column in _LIST_FILTERS.items()
            if (values := getattr(f, name))
        ),
        *(pl.col(field).is_between(low, high) for field, (low, high) in f.numeric.items()),
        *(c for rule in _RULES if (c := rule(f, snap, lookup)) is not None),
    ]
    return snap.images.filter(*conditions) if conditions else snap.images


def _in_list(column: str, values: list[str]) -> pl.Expr:
    condition = pl.col(column).is_in(values)
    # "(no metadata)" is the family of files without a generations row.
    no_family = column == "model_family" and NO_METADATA in values
    return condition | pl.col(column).is_null() if no_family else condition


def _ids(ids: Iterable[int]) -> pl.Expr:
    return pl.col("id").is_in(pl.Series(sorted(ids), dtype=pl.Int64).implode())


# One condition per optional filter, or None while the filter is unset.
type _Rule = Callable[[Filters, Snapshot, Lookup], pl.Expr | None]


def _tags(f: Filters, snap: Snapshot, lookup: Lookup) -> pl.Expr | None:
    return pl.col("tags").list.eval(pl.element().is_in(f.tags)).list.any() if f.tags else None


def _date_from(f: Filters, snap: Snapshot, lookup: Lookup) -> pl.Expr | None:
    return None if f.date_from is None else pl.col("date") >= f.date_from


def _date_to(f: Filters, snap: Snapshot, lookup: Lookup) -> pl.Expr | None:
    return None if f.date_to is None else pl.col("date") <= f.date_to


def _loras(f: Filters, snap: Snapshot, lookup: Lookup) -> pl.Expr | None:
    names, mode = f.loras.names, f.loras.mode
    return pl.col("id").is_in(_lora_ids(snap, names, mode).implode()) if names else None


def _text(f: Filters, snap: Snapshot, lookup: Lookup) -> pl.Expr | None:
    text = f.text.strip()
    return _ids(lookup.search(text)) if text else None


def _saved(f: Filters, snap: Snapshot, lookup: Lookup) -> pl.Expr | None:
    if f.saved is None:
        return None
    saved = has_hash(lookup.saved_hashes())
    return saved if f.saved else ~saved


def _saved_prompt(f: Filters, snap: Snapshot, lookup: Lookup) -> pl.Expr | None:
    return None if f.saved_prompt is None else _ids(lookup.saved_prompt_ids(f.saved_prompt))


def _sentences(f: Filters, snap: Snapshot, lookup: Lookup) -> pl.Expr | None:
    hashes = {int(s, 16) for s in f.sentences}
    return _ids(lookup.sentence_ids(hashes)) if hashes else None


_RULES: tuple[_Rule, ...] = (
    _tags,
    _date_from,
    _date_to,
    _loras,
    _text,
    _saved,
    _saved_prompt,
    _sentences,
)


def _lora_ids(snap: Snapshot, names: list[str], mode: str) -> pl.Series:
    uses = snap.loras.filter(pl.col("name").is_in(names))
    if mode == "all":
        wanted = len(set(names))
        uses = uses.group_by("file_id").agg(pl.col("name").n_unique().alias("n"))
        uses = uses.filter(pl.col("n") == wanted)
    return uses["file_id"].unique()


def resolve(snap: Snapshot, scope: Scope, analysis: AnalysisConfig, lookup: Lookup) -> Resolved:
    if scope.selection:
        files = snap.images.filter(pl.col("id").is_in(scope.selection))
        kind = "selection"
    else:
        files = filter_files(snap, scope.filters, lookup)
        kind = "filtered" if is_filtered(scope.filters) else "all"

    rows = files.filter(pl.col("has_generation"))
    analyzed = rows
    if analysis.dedupe_identical_files:
        # The lowest file id per content hash; unreadable files ("" hash) are never merged.
        first = pl.col("id") == pl.col("id").min().over("content_hash")
        analyzed = rows.filter(first | (pl.col("content_hash") == ""))
    analyzed = analyzed.with_columns(pl.col("model_family").alias("group"))
    info = {
        "scope_kind": kind,
        "scope_size": files.height,
        "excluded_no_metadata": files.height - rows.height,
        "duplicates_removed": rows.height - analyzed.height,
        "analyzed": analyzed.height,
    }
    return Resolved(info, files, analyzed)
