"""Connection plumbing and cache state shared by the Server's mixins."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from comfylens.analytics.snapshot import SnapshotStore
from comfylens.api.errors import no_catalog
from comfylens.collection.store import CollectionStore
from comfylens.db.connection import CatalogMissing, connect_readonly

# How many memoized search and collection-lookup results to keep, keyed by snapshot revision.
CACHE_SIZE = 64


class _ServerBase:
    """The state every Server mixin may touch; filled in by Server.__init__."""

    catalog: Path
    store: SnapshotStore
    collection: CollectionStore | None
    _search: dict[tuple[float, str], set[int]]
    _saved: dict[tuple[float, int, int], set[int]]

    def connect(self) -> sqlite3.Connection:
        try:
            return connect_readonly(self.catalog)
        except CatalogMissing as e:
            raise no_catalog() from e

    @contextmanager
    def reading(self) -> Iterator[sqlite3.Connection]:
        """A read-only catalog connection for the block, closed after it."""
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()
