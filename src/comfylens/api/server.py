"""Server state shared by every route: the library, its snapshot and the background indexer."""

import json
import sqlite3
import threading
import time
from collections.abc import Callable, Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import Request

from comfylens.analytics import (
    Snapshot,
    SnapshotStore,
    apply_removal,
    apply_rename,
    apply_tags,
)
from comfylens.api.collection_lookup import CollectionLookupMixin
from comfylens.api.errors import ApiError, no_catalog
from comfylens.api.search import SearchMixin
from comfylens.collection import CollectionStore, CollectionUnavailable
from comfylens.config import Config
from comfylens.db import connect
from comfylens.index import DEBOUNCE_MS, Indexer, IndexLock, LibraryWatcher, file_ops, fixer
from comfylens.paths import catalog_path, collection_dir, lock_path

# An edit waits this long for the indexer's current transaction (an FTS rebuild of a large
# library takes seconds) before it gives up as busy.
_EDIT_BUSY_TIMEOUT = 30.0

# Only the Host headers in server.allowed_hosts are served: without the check, a malicious
# page could reach the loopback server through DNS rebinding. "testserver" is Starlette's
# TestClient default; "comfylens.local" is the container's mDNS name.


def stored_json(text: str | None) -> Any:
    """A JSON document from the catalog or collection, or None when there is none."""
    # stdlib json accepts NaN; Pydantic then serializes it as null.
    return json.loads(text) if text else None


MEDIA_TYPES = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
# Thumbnails and collection originals are named by content hash, so they never change.
IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}


@dataclass(frozen=True, slots=True)
class FixSummary:
    """The last Fix run, for the UI's notice once it lands."""

    fixed: int  # files rewritten
    first_failure: str | None  # "path: reason"
    failed: int
    error: str | None  # the run itself failed: nothing more was fixed
    finished_at: float = field(default_factory=time.time)


class Server(SearchMixin, CollectionLookupMixin):
    def __init__(self, root: Path, config: Config) -> None:
        self.root = root.resolve()
        self.config = config
        self.catalog = catalog_path(self.root)
        self.store = SnapshotStore(self.catalog, config)
        self.indexer = Indexer(self.root, config)
        self.last_error: str | None = None
        self.last_fix: FixSummary | None = None
        self.last_finished_at: float | None = None
        self.rebuilding = False  # swapping in the snapshot after a run
        self.watcher: LibraryWatcher | None = None
        self._pending = False  # another run was requested while one was running
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        # Edits run one at a time, so the snapshot sees them in the order the catalog did.
        self._edits = threading.Lock()
        self._search: dict[tuple[float, str], set[int]] = {}
        self._saved: dict[tuple[float, int, int], set[int]] = {}
        # The collection is shared by every library; without it the library still works.
        self.collection: CollectionStore | None = None
        self.collection_error: str | None = None
        try:
            self.collection = CollectionStore(collection_dir())
        except (CollectionUnavailable, sqlite3.Error, OSError) as e:
            self.collection_error = str(e)

    @property
    def indexing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def watching(self) -> bool:
        return self.watcher is not None and self.watcher.running

    def watch(self, debounce_ms: int = DEBOUNCE_MS) -> None:
        """Index automatically when image files in the library change."""
        self.watcher = LibraryWatcher(
            self.root, self.config.index, self.request_index, debounce_ms=debounce_ms
        )
        self.watcher.start()

    def stop_watching(self) -> None:
        if self.watcher is not None:
            self.watcher.stop()

    def request_index(self) -> None:
        """Start a run, or queue one more after the current run so no change is missed."""
        with self._lock:
            if self.indexing:
                self._pending = True
                return
        self.start_index()

    def start_index(self) -> bool:
        """Start an incremental index in a background thread; False if a run is under way."""
        return self._start(self._index)

    def start_fix(self) -> bool:
        """Fix the library's files in a background thread, then index the ones that changed;
        False if a run is under way."""
        return self._start(self._fix)

    def _start(self, target: Callable[[], None]) -> bool:
        with self._lock:
            if self.indexing:
                return False
            self._thread = threading.Thread(target=target, name="indexer", daemon=True)
            self._thread.start()
            return True

    def _fix(self) -> None:
        started = time.time()
        changed: list[str] = []
        try:
            fixed = self._fix_files(started)
            changed = list(fixed.changed)
            if self.collection is not None:  # saved prompts follow their attempts' new hashes
                renamed = dict(fixed.changed.values())
                self.collection.rehash_attempts(renamed, fixed.kept_hashes)
            self.last_fix = FixSummary(
                fixed=len(changed),
                first_failure=next(iter(fixed.failed), None),
                failed=len(fixed.failed),
                error=None,
            )
        except Exception as e:  # IndexLocked, no catalog, a busy collection, or a bug
            self.last_fix = FixSummary(
                fixed=len(changed), first_failure=None, failed=0, error=str(e)
            )
        self._index(reread=changed)

    def _fix_files(self, started: float) -> fixer.Fixed:
        """Rewrite the files under the index lock. The catalog follows in the index run after."""
        self.indexer.set_status(state="fixing", total=0, done=0, errors=0, started_at=started)
        with IndexLock(lock_path(self.root)), self._edit_connection() as conn:
            fixed = fixer.fix_library(
                self.root,
                conn,
                self.config,
                guard=self._edits,
                progress=lambda done, total: self.indexer.set_status(done=done, total=total),
            )
        return fixed

    def _index(self, reread: Collection[str] = ()) -> None:
        while True:
            with self._lock:
                self._pending = False
            try:
                self.indexer.run(reread=reread)
                reread = ()
                self.last_error = None
                self.rebuilding = True
                self.store.rebuild()
            except Exception as e:  # IndexLocked, UnsafeLocation, or a bug: report, keep serving
                self.last_error = str(e)
            finally:
                self.rebuilding = False
                self.last_finished_at = time.time()
            with self._lock:
                if self._pending:
                    continue
                # Under the same lock that request_index checks, so a request can never be
                # queued after this point and then never run.
                self._thread = None
                return

    def rename(self, file_id: int, name: str) -> file_ops.Renamed:
        """Rename a file on disk, in the catalog and in the served snapshot.

        Raises what file_ops.rename_file raises, or sqlite3.OperationalError when busy.
        """
        with self._editing() as conn:
            renamed = file_ops.rename_file(self.root, conn, self.config, file_id, name)

            def patch(snap: Snapshot) -> None:
                if renamed.replaced is not None:
                    apply_removal(snap, [renamed.replaced])
                apply_rename(snap, file_id, renamed.rel_path, renamed.generated_at)

            self.store.patch(patch)
        self._index_again_if_running()
        return renamed

    def tag(self, ids: list[int], add: list[str], remove: list[str]) -> file_ops.Tagged:
        """Retag files on disk, in the catalog and in the served snapshot."""
        with self._editing() as conn:
            tagged = file_ops.tag_files(self.root, conn, ids, add, remove)
            if tagged.tags:
                self.store.patch(partial(apply_tags, tags=tagged.tags))
        if tagged.failed:
            self.request_index()  # a file may have changed or gone since it was indexed
        else:
            self._index_again_if_running()
        return tagged

    def trash(self, ids: list[int]) -> file_ops.Trashed:
        """Move files to the system trash and drop them from the catalog and the snapshot."""
        with self._editing() as conn:
            try:
                trashed = file_ops.trash_files(self.root, conn, ids)
            except sqlite3.Error:
                self.request_index()  # some files may be gone already: let a run catch up
                raise
            if trashed.removed:
                self.store.patch(partial(apply_removal, ids=trashed.removed))
        self._index_again_if_running()
        return trashed

    @contextmanager
    def _edit_connection(self) -> Iterator[sqlite3.Connection]:
        """An open writer connection, closed after the block; requires a catalog."""
        if not self.catalog.is_file():
            raise no_catalog()
        conn = connect(self.catalog, timeout=_EDIT_BUSY_TIMEOUT)
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _editing(self) -> Iterator[sqlite3.Connection]:
        """An edit connection while the edit lock is held, so edits run one at a time and the
        snapshot follows them in the catalog's order."""
        with self._edits, self._edit_connection() as conn:
            yield conn

    def _index_again_if_running(self) -> None:
        """A run in progress may have scanned the library before the edit; queue another so
        nothing it wrote from that older view outlives it."""
        with self._lock:
            if self.indexing:
                self._pending = True

    def file_gone(self) -> ApiError:
        """The error for a catalogued file that is no longer on disk; queues an index run, since
        the catalog is behind the library."""
        self.request_index()
        return ApiError(404, "file_missing", "the file is no longer on disk")


def server_of(request: Request) -> Server:
    return request.app.state.server


def same_origin(request: Request) -> None:
    """Refuse a library-changing request that another site's page sent.

    Browsers already stop such JSON requests behind a CORS preflight this server never
    answers; this check does not depend on that.
    """
    origin = request.headers.get("origin")
    allowed = server_of(request).config.server.allowed_hosts
    if origin is not None and urlsplit(origin).hostname not in allowed:
        raise ApiError(403, "cross_origin", "requests from other sites cannot change the library")
