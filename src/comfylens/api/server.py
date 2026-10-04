"""Server state shared by every route: the library, its snapshot and the background indexer."""

import sqlite3
import threading
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse

from comfylens.analytics.snapshot import SnapshotStore
from comfylens.config import Config
from comfylens.db.connection import CatalogMissing, connect_readonly
from comfylens.index.indexer import Indexer
from comfylens.index.watch import DEBOUNCE_MS, LibraryWatcher
from comfylens.paths import catalog_path

_SEARCH_CACHE = 64


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
