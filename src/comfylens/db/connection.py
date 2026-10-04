"""One writer connection, owned by the indexer thread; every reader opens its own connection.

Renames and trashes from the UI write through short-lived connections of their own, one small
transaction each; SQLite serializes them with the indexer's.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from comfylens import version


class CatalogMissing(FileNotFoundError):
    """No usable catalog exists for this library."""


def connect(path: Path, *, timeout: float = 5.0) -> sqlite3.Connection:
    """A writer connection in autocommit mode; use `transaction` for writes. `timeout` is how
    long a write waits for another connection's transaction."""
    conn = sqlite3.connect(path, autocommit=True, check_same_thread=False, timeout=timeout)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise CatalogMissing(str(path))
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, autocommit=True)
    if get_meta(conn, "schema_version") != str(version.SCHEMA_VERSION):
        conn.close()
        raise CatalogMissing(f"{path} was built by another schema version")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    except sqlite3.DatabaseError:
        return None
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def has_fts(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'prompts_fts'").fetchone()
    return row is not None


def _fts5_available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp.fts5_probe USING fts5(x)")
    except sqlite3.OperationalError:
        return False
    conn.execute("DROP TABLE temp.fts5_probe")
    return True


@dataclass(slots=True)
class Catalog:
    conn: sqlite3.Connection
    path: Path
    created: bool  # built from scratch by this open
    stale: bool  # extractor version or config hash differ: re-extract from raw JSON


def open_catalog(path: Path, root: Path, config_hash: str) -> Catalog:
    """Open the writer connection, rebuilding the catalog when its schema version differs.

    Thumbnails survive a rebuild because they are keyed by content hash.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        conn: sqlite3.Connection | None = None
        try:
            conn = connect(path)
            schema = get_meta(conn, "schema_version")
        except sqlite3.DatabaseError:
            schema = None  # not a readable database: rebuild below
        if conn is not None and schema == str(version.SCHEMA_VERSION):
            stale = (
                get_meta(conn, "extractor_version") != str(version.EXTRACTOR_VERSION)
                or get_meta(conn, "config_hash") != config_hash
            )
            return Catalog(conn, path, created=False, stale=stale)
        if conn is not None:
            conn.close()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)

    conn = connect(path)
    with transaction(conn):
        conn.executescript(
            resources.files("comfylens.db").joinpath("schema.sql").read_text("utf-8")
        )
        if _fts5_available(conn):
            conn.execute(
                "CREATE VIRTUAL TABLE prompts_fts USING fts5("
                "positive_prompt, negative_prompt, stage_prompts,"
                " content='generations', content_rowid='file_id')"
            )
        set_meta(conn, "schema_version", str(version.SCHEMA_VERSION))
        set_meta(conn, "extractor_version", str(version.EXTRACTOR_VERSION))
        set_meta(conn, "config_hash", config_hash)
        set_meta(conn, "library_root", str(root))
    return Catalog(conn, path, created=True, stale=False)
