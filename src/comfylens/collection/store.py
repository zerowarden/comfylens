"""The collection store: one SQLite file and the reference images beside it.

Unlike the catalog this store cannot be rebuilt, so it is never deleted: each schema change is a
numbered migration applied in place, and a store written by a newer comfylens is left untouched.
Every call opens a short-lived connection; several servers (one per library) may share the store.

The methods live in mixins by concern: originals.py (image bytes), prompts.py (CRUD and links),
queries.py (read models), archive_rows.py (archive marshalling). This module keeps the public
name, construction and the re-exported vocabulary.
"""

import threading
from pathlib import Path

from comfylens.collection.archive_rows import ArchiveRowsMixin
from comfylens.collection.originals import OriginalsMixin
from comfylens.collection.prompts import PromptsMixin
from comfylens.collection.queries import QueriesMixin
from comfylens.collection.store_base import (
    GC_GRACE_SECONDS,
    HASH,
    MIGRATIONS,
    CollectionUnavailable,
    InvalidInput,
    PromptData,
    UnknownOriginal,
    normalize_tags,
)

__all__ = [
    "GC_GRACE_SECONDS",
    "HASH",
    "MIGRATIONS",
    "CollectionStore",
    "CollectionUnavailable",
    "InvalidInput",
    "PromptData",
    "UnknownOriginal",
    "normalize_tags",
]


class CollectionStore(OriginalsMixin, QueriesMixin, ArchiveRowsMixin, PromptsMixin):
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / "collection.sqlite"
        self.originals_dir = directory / "originals"
        self._lock = threading.Lock()
        self._hashes: tuple[int, frozenset[str]] | None = None
        directory.mkdir(parents=True, exist_ok=True)
        self._migrate()
        self.collect_garbage()
