"""Shared plumbing and vocabulary for CollectionStore: connections, migrations, validation.

The store's methods live in mixins by concern (originals, prompts, queries, archive rows); they
all share the connection and migration behavior defined here.
"""

import re
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from comfylens.collection.models import HASH_RE, MAX_TAG
from comfylens.db.connection import connect, transaction

HASH = re.compile(HASH_RE)
# Originals no prompt refers to are kept this long: an open editor's draft must not lose its image.
GC_GRACE_SECONDS = 24 * 3600
_BUSY_TIMEOUT = 30.0


def _migrations() -> list[str]:
    folder = resources.files("comfylens.collection").joinpath("schema")
    names = sorted(p.name for p in folder.iterdir() if p.name.endswith(".sql"))
    return [folder.joinpath(name).read_text("utf-8") for name in names]


MIGRATIONS = _migrations()


class CollectionUnavailable(RuntimeError):
    """The store cannot be used: unreadable, or written by a newer schema."""


class InvalidInput(ValueError):
    """A field is out of bounds; the message names it."""


class UnknownOriginal(LookupError):
    """A reference names an image that is not in the collection."""


@dataclass(slots=True)
class PromptData:
    """The editable fields of a saved prompt."""

    title: str
    positive: str
    negative: str = ""
    notes: str = ""
    source_url: str | None = None
    model_family: str | None = None
    tags: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    references: list[str] = field(default_factory=list)  # content hashes, in order
    attempts: list[str] = field(default_factory=list)  # linked in addition to existing ones


def key_hex(key: int | None) -> str | None:
    return None if key is None else f"{key:016x}"


def _key_int(text: str | None) -> int | None:
    return None if text is None else int(text, 16)


def normalize_tags(tags: list[str]) -> list[str]:
    """Trimmed, lowercased, inner whitespace collapsed; duplicates dropped, order kept."""
    out: list[str] = []
    for raw in tags:
        tag = " ".join(raw.split()).lower()
        if not tag:
            continue
        if len(tag) > MAX_TAG or "," in tag:
            raise InvalidInput(f"tag {raw!r}: at most {MAX_TAG} characters and no commas")
        if tag not in out:
            out.append(tag)
    return out


def _check_hashes(hashes: list[str]) -> list[str]:
    for h in hashes:
        if not HASH.fullmatch(h):
            raise InvalidInput(f"{h!r} is not a content hash")
    return list(dict.fromkeys(hashes))


def _now() -> int:
    return int(time.time())


class _StoreBase:
    """The connection, migration and cache state every mixin shares."""

    directory: Path
    path: Path
    originals_dir: Path
    _lock: threading.Lock
    _hashes: tuple[int, frozenset[str]] | None

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = connect(self.path, timeout=_BUSY_TIMEOUT)
        try:
            yield conn
        finally:
            conn.close()

    def _stored_version(self) -> int:
        """Read without the writer connection, which would switch the file to WAL mode."""
        if not self.path.exists():
            return 0
        try:
            conn = sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)
            try:
                return conn.execute("PRAGMA user_version").fetchone()[0]
            finally:
                conn.close()
        except sqlite3.DatabaseError as e:
            raise CollectionUnavailable(f"{self.path} is not a readable database: {e}") from e

    def _migrate(self) -> None:
        version = self._stored_version()
        if version > len(MIGRATIONS):
            raise CollectionUnavailable(
                f"{self.path} has schema {version}; this comfylens knows up to {len(MIGRATIONS)}"
            )
        if version == len(MIGRATIONS):
            return
        try:
            with self._connect() as conn:
                for number in range(version + 1, len(MIGRATIONS) + 1):
                    with transaction(conn):
                        conn.executescript(MIGRATIONS[number - 1])
                        conn.execute(f"PRAGMA user_version = {number}")
        except sqlite3.DatabaseError as e:
            raise CollectionUnavailable(f"{self.path} could not be migrated: {e}") from e

    @staticmethod
    def _bump(conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('revision', '1') ON CONFLICT(key)"
            " DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)"
        )

    @staticmethod
    def _revision(conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT value FROM meta WHERE key = 'revision'").fetchone()
        return int(row[0]) if row else 0

    def revision(self) -> int:
        with self._connect() as conn:
            return self._revision(conn)
