"""Server state shared by every route: the library, its snapshot and the background indexer."""

import sqlite3
import threading
import time
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

from comfylens import file_ops
from comfylens.analytics.snapshot import Snapshot, SnapshotStore, apply_removal, apply_rename
from comfylens.config import Config
from comfylens.db.connection import CatalogMissing, connect, connect_readonly
from comfylens.index.indexer import Indexer
from comfylens.index.watch import DEBOUNCE_MS, LibraryWatcher
from comfylens.paths import catalog_path

_SEARCH_CACHE = 64
# An edit waits this long for the indexer's current transaction (an FTS rebuild of a large
# library takes seconds) before it gives up as busy.
_EDIT_BUSY_TIMEOUT = 30.0

# Only these Host headers are served: without the check, a malicious page could reach the
# loopback server through DNS rebinding. "testserver" is Starlette's TestClient default.
ALLOWED_HOSTS = ("localhost", "127.0.0.1", "testserver")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def error_response(status: int, code: str, message: str, **extra: object) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}, **extra}, status_code=status)


class Server:
    def __init__(self, root: Path, config: Config) -> None:
        self.root = root.resolve()
        self.config = config
        self.catalog = catalog_path(self.root)
        self.store = SnapshotStore(self.catalog, config)
        self.indexer = Indexer(self.root, config)
        self.last_error: str | None = None
        self.last_finished_at: float | None = None
        self.rebuilding = False  # swapping in the snapshot after a run
        self.watcher: LibraryWatcher | None = None
        self._pending = False  # another run was requested while one was running
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        # Edits run one at a time, so the snapshot sees them in the order the catalog did.
        self._edits = threading.Lock()
        self._search: dict[tuple[float, str], set[int]] = {}

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
        """Start an incremental index in a background thread; False if one is running."""
        with self._lock:
            if self.indexing:
                return False
            self._thread = threading.Thread(target=self._index, name="indexer", daemon=True)
            self._thread.start()
            return True

    def _index(self) -> None:
        while True:
            with self._lock:
                self._pending = False
            try:
                self.indexer.run()
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
        with self._edits:
            conn = self._edit_connection()
            try:
                renamed = file_ops.rename_file(self.root, conn, self.config, file_id, name)
            finally:
                conn.close()

            def patch(snap: Snapshot) -> None:
                if renamed.replaced is not None:
                    apply_removal(snap, [renamed.replaced])
                apply_rename(snap, file_id, renamed.rel_path, renamed.generated_at)

            self.store.patch(patch)
        self._index_again_if_running()
        return renamed

    def trash(self, ids: list[int]) -> file_ops.Trashed:
        """Move files to the system trash and drop them from the catalog and the snapshot."""
        with self._edits:
            conn = self._edit_connection()
            try:
                trashed = file_ops.trash_files(self.root, conn, ids)
            except sqlite3.Error:
                self.request_index()  # some files may be gone already: let a run catch up
                raise
            finally:
                conn.close()
            if trashed.removed:
                self.store.patch(partial(apply_removal, ids=trashed.removed))
        self._index_again_if_running()
        return trashed

    def _edit_connection(self) -> sqlite3.Connection:
        if not self.catalog.is_file():
            raise ApiError(503, "no_catalog", "the library has not been indexed yet")
        return connect(self.catalog, timeout=_EDIT_BUSY_TIMEOUT)

    def _index_again_if_running(self) -> None:
        """A run in progress may have scanned the library before the edit; queue another so
        nothing it wrote from that older view outlives it."""
        with self._lock:
            if self.indexing:
                self._pending = True

    def connect(self) -> sqlite3.Connection:
        try:
            return connect_readonly(self.catalog)
        except CatalogMissing as e:
            raise ApiError(503, "no_catalog", "the library has not been indexed yet") from e

    def search(self, text: str) -> set[int]:
        """Files whose positive or negative prompt contains `text` (FTS5 phrase, else LIKE)."""
        key = (self.store.current.built_at, text)
        if key in self._search:
            return self._search[key]
        conn = self.connect()
        try:
            ids = None
            if self.store.current.fts:
                phrase = '"' + text.replace('"', '""') + '"'
                try:
                    rows = conn.execute(
                        "SELECT rowid FROM prompts_fts WHERE prompts_fts MATCH ?", (phrase,)
                    ).fetchall()
                    ids = {r[0] for r in rows}
                except sqlite3.OperationalError:
                    ids = None  # e.g. only punctuation: fall back to LIKE
            if ids is None:
                escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                pattern = f"%{escaped}%"
                rows = conn.execute(
                    "SELECT file_id FROM generations WHERE positive_prompt LIKE ? ESCAPE '\\'"
                    " OR negative_prompt LIKE ? ESCAPE '\\' OR stage_prompts LIKE ? ESCAPE '\\'",
                    (pattern, pattern, pattern),
                ).fetchall()
                ids = {r[0] for r in rows}
        finally:
            conn.close()
        if len(self._search) >= _SEARCH_CACHE:
            self._search.clear()
        self._search[key] = ids
        return ids


def server_of(request: Request) -> Server:
    return request.app.state.server


def same_origin(request: Request) -> None:
    """Refuse a library-changing request that another site's page sent.

    Browsers already stop such JSON requests behind a CORS preflight this server never
    answers; this check does not depend on that.
    """
    origin = request.headers.get("origin")
    if origin is not None and urlsplit(origin).hostname not in ALLOWED_HOSTS:
        raise ApiError(403, "cross_origin", "requests from other sites cannot change the library")
