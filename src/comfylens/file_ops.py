"""Renaming and trashing library files on the user's request.

This module and its callers in the server are the only code that changes the library; the
indexer and the watcher only read it. Each operation updates the file on disk and its catalog
row together, so the next index run finds nothing to do for it.
"""

import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from send2trash import send2trash

from comfylens.config import Config
from comfylens.db.connection import transaction
from comfylens.index.timestamps import generated_at
from comfylens.index.write import delete_files

MAX_NAME_BYTES = 255  # NAME_MAX on Linux and macOS


class InvalidName(ValueError):
    """The new name is not a usable file name for this library."""


class NameTaken(FileExistsError):
    """Another file already has the new name."""


class FileMissing(FileNotFoundError):
    """The catalog lists the file, but it is not on disk (the catalog is behind)."""


class UnknownFile(LookupError):
    """No catalog row has this id."""


@dataclass(frozen=True, slots=True)
class Renamed:
    rel_path: str
    generated_at: int
    replaced: int | None  # id of a stale row that held the new path, now deleted


@dataclass(slots=True)
class Trashed:
    removed: list[int] = field(default_factory=list)  # gone from disk and catalog
    failed: list[tuple[int, str]] = field(default_factory=list)  # (id, reason)


def new_rel_path(rel_path: str, name: str, config: Config) -> str:
    """The path `rel_path` would have under the new base name, in the same directory.

    The extension must stay the same (case aside): it decides whether the file is indexed and
    how it is read. Raises InvalidName.
    """
    if not name.strip():
        raise InvalidName("the name is empty")
    if name != name.strip():
        raise InvalidName("the name starts or ends with whitespace")
    if "/" in name or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise InvalidName("the name contains a slash or a control character")
    try:
        encoded = name.encode("utf-8")
    except UnicodeEncodeError:
        raise InvalidName("the name is not valid UTF-8") from None
    if len(encoded) > MAX_NAME_BYTES:
        raise InvalidName(f"the name is longer than {MAX_NAME_BYTES} bytes")
    old = PurePosixPath(rel_path)
    suffix = old.suffix.lower()
    if not name.lower().endswith(suffix) or len(name) == len(suffix):
        raise InvalidName(f"the name must keep the {old.suffix} extension")
    new = (old.parent / name).as_posix()
    if any(PurePosixPath(new).full_match(g) for g in config.index.exclude_globs):
        raise InvalidName("the new path is excluded from indexing")
    return new


def library_path(root: Path, rel_path: str) -> str:
    """The absolute path of a catalog path; FileMissing if it would leave the library."""
    path = os.path.normpath(os.path.join(root, rel_path))
    if os.path.commonpath([path, root]) != str(root):
        raise FileMissing(rel_path)
    return path


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def rename_file(
    root: Path, conn: sqlite3.Connection, config: Config, file_id: int, name: str
) -> Renamed:
    """Give a file a new base name on disk and in the catalog.

    Never replaces another file. If the catalog write fails, the file gets its old name back.
    Raises UnknownFile, InvalidName, FileMissing, NameTaken or OSError.
    """
    row = conn.execute("SELECT rel_path, mtime_ns FROM files WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        raise UnknownFile(file_id)
    old_rel, mtime_ns = row
    new_rel = new_rel_path(old_rel, name, config)
    stamp = generated_at(new_rel, mtime_ns, config.timestamps)
    if new_rel == old_rel:
        return Renamed(old_rel, stamp, None)
    src, dst = library_path(root, old_rel), library_path(root, new_rel)
    if not os.path.isfile(src):
        raise FileMissing(old_rel)
    # A name differing only in case is the same file on a case-insensitive file system.
    if os.path.lexists(dst) and not _same_file(src, dst):
        raise NameTaken(PurePosixPath(new_rel).name)
    os.rename(src, dst)  # same directory: atomic, and the mtime is kept
    try:
        with transaction(conn):
            # A row can still hold the new path when its file was removed outside the app and
            # no index run has noticed yet.
            stale = conn.execute(
                "DELETE FROM files WHERE rel_path = ? AND id != ? RETURNING id", (new_rel, file_id)
            ).fetchone()
            conn.execute(
                "UPDATE files SET rel_path = ?, generated_at = ? WHERE id = ?",
                (new_rel, stamp, file_id),
            )
    except BaseException:
        os.rename(dst, src)
        raise
    return Renamed(new_rel, stamp, stale[0] if stale else None)


def trash_files(root: Path, conn: sqlite3.Connection, ids: list[int]) -> Trashed:
    """Move files to the system trash and drop their catalog rows.

    A file already gone from disk only loses its row. Failures are reported per file; the
    other files are still trashed.
    """
    result = Trashed()
    rows: dict[int, str] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        rows.update(
            conn.execute(
                f"SELECT id, rel_path FROM files WHERE id IN ({','.join('?' * len(chunk))})",
                chunk,
            ).fetchall()
        )
    for file_id in dict.fromkeys(ids):
        rel_path = rows.get(file_id)
        if rel_path is None:
            result.failed.append((file_id, "no image with this id"))
            continue
        try:
            path = library_path(root, rel_path)
            if os.path.lexists(path):
                send2trash(path)
        except FileMissing:
            result.failed.append((file_id, f"{rel_path}: the path leaves the library"))
            continue
        except OSError as e:
            result.failed.append((file_id, f"{rel_path}: {e.strerror or e}"))
            continue
        result.removed.append(file_id)
    if result.removed:
        # The prompt search index keeps the rows until the next index run rebuilds it; search
        # results are intersected with the snapshot, so they never show.
        with transaction(conn):
            delete_files(conn, result.removed)
    return result
