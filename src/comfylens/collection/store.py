"""The collection store: one SQLite file and the reference images beside it.

Unlike the catalog this store cannot be rebuilt, so it is never deleted: each schema change is a
numbered migration applied in place, and a store written by a newer comfylens is left untouched.
Every call opens a short-lived connection; several servers (one per library) may share the store.
"""

import json
import os
import re
import sqlite3
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import xxhash

from comfylens.analytics.prompts import prompt_key
from comfylens.db.connection import connect, transaction

Role = Literal["reference", "attempt"]
OriginalFormat = Literal["png", "jpeg", "webp"]

# A content hash: xxh3-128 as 32 lowercase hex digits. Thumbnails and originals are named by it.
HASH_RE = r"[0-9a-f]{32}"
HASH = re.compile(HASH_RE)
EXTENSIONS: dict[str, str] = {"png": "png", "jpeg": "jpg", "webp": "webp"}
MAX_TITLE = 200
MAX_TAG = 40
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


@dataclass(frozen=True, slots=True)
class Links:
    """What ties a saved prompt to library files, as of one store revision."""

    revision: int
    hashes: frozenset[str]  # references and attempts
    key: int | None  # prompt_key of the positive prompt


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


class CollectionStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / "collection.sqlite"
        self.originals_dir = directory / "originals"
        self._lock = threading.Lock()
        self._hashes: tuple[int, frozenset[str]] | None = None
        directory.mkdir(parents=True, exist_ok=True)
        self._migrate()
        self.collect_garbage()

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

    def _file(self, content_hash: str, fmt: str) -> Path:
        return self.originals_dir / content_hash[:2] / f"{content_hash}.{EXTENSIONS[fmt]}"

    def put_original(
        self,
        data: bytes,
        fmt: OriginalFormat,
        width: int,
        height: int,
        api_prompt: str | None,
        workflow: str | None,
    ) -> str:
        """Store an image's exact bytes; returns its content hash. Storing it again is a no-op."""
        content_hash = xxhash.xxh3_128_hexdigest(data)
        self.write_file(content_hash, fmt, data)
        with self._connect() as conn, transaction(conn):
            # A re-upload restarts the grace period of an original no prompt uses yet.
            conn.execute(
                "INSERT INTO originals (content_hash, format, width, height, size, api_prompt,"
                " workflow, added_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(content_hash)"
                " DO UPDATE SET added_at = excluded.added_at",
                (content_hash, fmt, width, height, len(data), api_prompt, workflow, _now()),
            )
        return content_hash

    def write_file(self, content_hash: str, fmt: str, data: bytes) -> None:
        """Put an original's bytes in place, atomically; nothing to do when already there."""
        target = self._file(content_hash, fmt)
        if target.is_file():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def original(self, content_hash: str) -> dict[str, Any] | None:
        """format, width, height, size and the file path; None when unknown or missing."""
        if not HASH.fullmatch(content_hash):
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT format, width, height, size FROM originals WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
        if row is None:
            return None
        path = self._file(content_hash, row[0])
        if not path.is_file():
            return None
        return {"format": row[0], "width": row[1], "height": row[2], "size": row[3], "path": path}

    def original_metadata(self, content_hash: str) -> tuple[str | None, str | None] | None:
        """The API prompt and workflow JSON texts of an original; None when unknown."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT api_prompt, workflow FROM originals WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
        return (row[0], row[1]) if row else None

    def collect_garbage(self, now: float | None = None) -> int:
        """Delete originals no prompt refers to once their grace period is over."""
        cutoff = int((time.time() if now is None else now) - GC_GRACE_SECONDS)
        with self._connect() as conn, transaction(conn):
            gone = conn.execute(
                "DELETE FROM originals WHERE added_at < ? AND content_hash NOT IN"
                " (SELECT content_hash FROM prompt_images WHERE role = 'reference')"
                " RETURNING content_hash, format",
                (cutoff,),
            ).fetchall()
        for content_hash, fmt in gone:
            self._file(content_hash, fmt).unlink(missing_ok=True)
        return len(gone)

    def _validated(self, data: PromptData) -> tuple[PromptData, list[str], list[str]]:
        title = data.title.strip()
        if not title or len(title) > MAX_TITLE:
            raise InvalidInput(f"title: 1 to {MAX_TITLE} characters")
        tags = normalize_tags(data.tags)
        references = _check_hashes(data.references)
        attempts = [h for h in _check_hashes(data.attempts) if h not in references]
        clean = PromptData(
            title=title,
            positive=data.positive,
            negative=data.negative,
            notes=data.notes,
            source_url=(data.source_url or "").strip() or None,
            model_family=(data.model_family or "").strip() or None,
            tags=tags,
            settings=data.settings,
        )
        return clean, references, attempts

    @staticmethod
    def _check_references(conn: sqlite3.Connection, references: list[str]) -> None:
        for h in references:
            if conn.execute("SELECT 1 FROM originals WHERE content_hash = ?", (h,)).fetchone():
                continue
            raise UnknownOriginal(h)

    @staticmethod
    def _write_children(
        conn: sqlite3.Connection,
        prompt_id: int,
        tags: list[str],
        references: list[str],
        attempts: list[str],
    ) -> None:
        now = _now()
        conn.execute("DELETE FROM prompt_tags WHERE prompt_id = ?", (prompt_id,))
        conn.executemany(
            "INSERT INTO prompt_tags (prompt_id, tag) VALUES (?, ?)",
            [(prompt_id, t) for t in tags],
        )
        # A hash that becomes a reference stops being an attempt.
        conn.execute(
            "DELETE FROM prompt_images WHERE prompt_id = ? AND role = 'reference'", (prompt_id,)
        )
        conn.executemany(
            "DELETE FROM prompt_images WHERE prompt_id = ? AND content_hash = ?",
            [(prompt_id, h) for h in references],
        )
        conn.executemany(
            "INSERT INTO prompt_images (prompt_id, content_hash, role, position, added_at)"
            " VALUES (?, ?, 'reference', ?, ?)",
            [(prompt_id, h, i, now) for i, h in enumerate(references)],
        )
        CollectionStore._add_attempts(conn, prompt_id, attempts, now)

    @staticmethod
    def _add_attempts(conn: sqlite3.Connection, prompt_id: int, hashes: list[str], now: int) -> int:
        start = conn.execute(
            "SELECT COALESCE(MAX(position) + 1, 0) FROM prompt_images"
            " WHERE prompt_id = ? AND role = 'attempt'",
            (prompt_id,),
        ).fetchone()[0]
        added = 0
        for h in hashes:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO prompt_images (prompt_id, content_hash, role, position,"
                " added_at) VALUES (?, ?, 'attempt', ?, ?)",
                (prompt_id, h, start + added, now),
            )
            added += cursor.rowcount
        return added

    def create(self, data: PromptData) -> int:
        """Raises InvalidInput or UnknownOriginal."""
        clean, references, attempts = self._validated(data)
        now = _now()
        with self._connect() as conn, transaction(conn):
            self._check_references(conn, references)
            prompt_id = conn.execute(
                "INSERT INTO prompts (uid, title, positive, negative, positive_key, notes,"
                " source_url, model_family, settings, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                (uuid.uuid4().hex, *self._columns(clean), now, now),
            ).fetchone()[0]
            self._write_children(conn, prompt_id, clean.tags, references, attempts)
            self._bump(conn)
        return prompt_id

    def update(self, prompt_id: int, data: PromptData) -> bool:
        """Replace the fields, tags and references; attempts are only added. False if unknown."""
        clean, references, attempts = self._validated(data)
        with self._connect() as conn, transaction(conn):
            self._check_references(conn, references)
            cursor = conn.execute(
                "UPDATE prompts SET title = ?, positive = ?, negative = ?, positive_key = ?,"
                " notes = ?, source_url = ?, model_family = ?, settings = ?, updated_at = ?"
                " WHERE id = ?",
                (*self._columns(clean), _now(), prompt_id),
            )
            if cursor.rowcount == 0:
                return False
            self._write_children(conn, prompt_id, clean.tags, references, attempts)
            self._bump(conn)
        return True

    @staticmethod
    def _columns(d: PromptData) -> tuple[Any, ...]:
        return (
            d.title,
            d.positive,
            d.negative,
            key_hex(prompt_key(d.positive)),
            d.notes,
            d.source_url,
            d.model_family,
            json.dumps(d.settings),
        )

    def delete(self, prompt_id: int) -> bool:
        with self._connect() as conn, transaction(conn):
            cursor = conn.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
            if cursor.rowcount:
                self._bump(conn)
        return cursor.rowcount > 0

    def link_attempts(self, prompt_id: int, hashes: list[str]) -> int | None:
        """Link library images by content hash; returns how many were new, None if unknown."""
        hashes = _check_hashes(hashes)
        with self._connect() as conn, transaction(conn):
            if not conn.execute("SELECT 1 FROM prompts WHERE id = ?", (prompt_id,)).fetchone():
                return None
            added = self._add_attempts(conn, prompt_id, hashes, _now())
            if added:
                conn.execute("UPDATE prompts SET updated_at = ? WHERE id = ?", (_now(), prompt_id))
                self._bump(conn)
        return added

    def unlink_attempts(self, prompt_id: int, hashes: list[str]) -> bool:
        """Remove attempt links (references stay); False if the prompt is unknown."""
        hashes = _check_hashes(hashes)
        with self._connect() as conn, transaction(conn):
            if not conn.execute("SELECT 1 FROM prompts WHERE id = ?", (prompt_id,)).fetchone():
                return False
            removed = sum(
                conn.execute(
                    "DELETE FROM prompt_images WHERE prompt_id = ? AND content_hash = ?"
                    " AND role = 'attempt'",
                    (prompt_id, h),
                ).rowcount
                for h in hashes
            )
            if removed:
                self._bump(conn)
        return True

    def get(self, prompt_id: int) -> dict[str, Any] | None:
        """Every field, tags, and images in order (references first) with original details."""
        with self._connect() as conn:
            cursor = conn.execute("SELECT * FROM prompts WHERE id = ?", (prompt_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            prompt = dict(zip([d[0] for d in cursor.description], row, strict=True))
            prompt["tags"] = [
                r[0]
                for r in conn.execute(
                    "SELECT tag FROM prompt_tags WHERE prompt_id = ? ORDER BY tag", (prompt_id,)
                )
            ]
            prompt["images"] = [
                {
                    "content_hash": h,
                    "role": role,
                    "format": fmt,
                    "width": w,
                    "height": ht,
                    "has_workflow": bool(has_workflow),
                }
                for h, role, fmt, w, ht, has_workflow in conn.execute(
                    "SELECT i.content_hash, i.role, o.format, o.width, o.height,"
                    " o.api_prompt IS NOT NULL OR o.workflow IS NOT NULL"
                    " FROM prompt_images i LEFT JOIN originals o USING (content_hash)"
                    " WHERE i.prompt_id = ? ORDER BY i.role = 'attempt', i.position",
                    (prompt_id,),
                )
            ]
        prompt["settings"] = json.loads(prompt["settings"])
        return prompt

    def summaries(
        self, q: str = "", tag: str | None = None, family: str | None = None
    ) -> list[dict[str, Any]]:
        """Summaries, most recently changed first. `q` matches text fields and tags."""
        where: list[str] = []
        params: list[Any] = []
        if q.strip():
            escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            fields = ("title", "positive", "negative", "notes")
            like = " OR ".join(f"p.{f} LIKE ? ESCAPE '\\'" for f in fields)
            where.append(
                f"({like} OR EXISTS (SELECT 1 FROM prompt_tags t WHERE t.prompt_id = p.id"
                " AND t.tag LIKE ? ESCAPE '\\'))"
            )
            params += [pattern] * (len(fields) + 1)
        if tag:
            where.append(
                "EXISTS (SELECT 1 FROM prompt_tags t WHERE t.prompt_id = p.id AND t.tag = ?)"
            )
            params.append(tag)
        if family:
            where.append("p.model_family = ?")
            params.append(family)
        sql = (
            "SELECT p.id, p.title, p.positive, p.model_family, p.updated_at,"
            " (SELECT json_group_array(tag) FROM (SELECT tag FROM prompt_tags"
            "   WHERE prompt_id = p.id ORDER BY tag)) AS tags,"
            " (SELECT content_hash FROM prompt_images WHERE prompt_id = p.id"
            "   ORDER BY role = 'attempt', position LIMIT 1) AS cover_hash,"
            " (SELECT COUNT(*) FROM prompt_images WHERE prompt_id = p.id"
            "   AND role = 'reference') AS reference_count,"
            " (SELECT COUNT(*) FROM prompt_images WHERE prompt_id = p.id"
            "   AND role = 'attempt') AS attempt_count"
            " FROM prompts p"
            + (f" WHERE {' AND '.join(where)}" if where else "")
            + " ORDER BY p.updated_at DESC, p.id DESC"
        )
        with self._connect() as conn:
            cursor = conn.execute(sql, params)
            names = [d[0] for d in cursor.description]
            rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        for row in rows:
            row["tags"] = json.loads(row["tags"])
        return rows

    def facets(self) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
        """(tag, prompts) and (model family, prompts), most used first."""
        with self._connect() as conn:
            tags = conn.execute(
                "SELECT tag, COUNT(*) AS n FROM prompt_tags GROUP BY tag ORDER BY n DESC, tag"
            ).fetchall()
            families = conn.execute(
                "SELECT model_family, COUNT(*) AS n FROM prompts WHERE model_family IS NOT NULL"
                " GROUP BY model_family ORDER BY n DESC, model_family"
            ).fetchall()
        return tags, families

    def saved_hashes(self) -> frozenset[str]:
        """Every content hash linked to a prompt, as reference or attempt."""
        with self._connect() as conn:
            revision = self._revision(conn)
            with self._lock:
                if self._hashes is not None and self._hashes[0] == revision:
                    return self._hashes[1]
            hashes = frozenset(
                r[0] for r in conn.execute("SELECT DISTINCT content_hash FROM prompt_images")
            )
        with self._lock:
            self._hashes = (revision, hashes)
        return hashes

    def links(self, prompt_id: int) -> Links | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT positive_key FROM prompts WHERE id = ?", (prompt_id,)
            ).fetchone()
            if row is None:
                return None
            hashes = frozenset(
                r[0]
                for r in conn.execute(
                    "SELECT content_hash FROM prompt_images WHERE prompt_id = ?", (prompt_id,)
                )
            )
            return Links(self._revision(conn), hashes, _key_int(row[0]))

    def all_links(self) -> dict[int, Links]:
        with self._connect() as conn:
            revision = self._revision(conn)
            hashes: dict[int, set[str]] = {}
            for prompt_id, h in conn.execute("SELECT prompt_id, content_hash FROM prompt_images"):
                hashes.setdefault(prompt_id, set()).add(h)
            return {
                prompt_id: Links(revision, frozenset(hashes.get(prompt_id, ())), _key_int(key))
                for prompt_id, key in conn.execute("SELECT id, positive_key FROM prompts")
            }

    def prompts_for_hash(self, content_hash: str) -> list[tuple[int, str, Role]]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT p.id, p.title, i.role FROM prompt_images i JOIN prompts p"
                " ON p.id = i.prompt_id WHERE i.content_hash = ?"
                " ORDER BY p.updated_at DESC, p.id DESC",
                (content_hash,),
            ).fetchall()

    def prompts_for_key(self, key: int) -> list[tuple[int, str]]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT id, title FROM prompts WHERE positive_key = ?"
                " ORDER BY updated_at DESC, id DESC",
                (key_hex(key),),
            ).fetchall()

    def export_rows(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Every prompt (fields, tags, images) and every original a prompt refers to, read in
        one transaction."""
        with self._connect() as conn:
            conn.execute("BEGIN")
            try:
                cursor = conn.execute(
                    "SELECT uid, title, positive, negative, notes, source_url, model_family,"
                    " settings, created_at, updated_at, id FROM prompts ORDER BY id"
                )
                names = [d[0] for d in cursor.description]
                prompts = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
                tags: dict[int, list[str]] = {}
                for prompt_id, tag in conn.execute(
                    "SELECT prompt_id, tag FROM prompt_tags ORDER BY tag"
                ):
                    tags.setdefault(prompt_id, []).append(tag)
                images: dict[int, list[dict[str, Any]]] = {}
                for prompt_id, h, role, position in conn.execute(
                    "SELECT prompt_id, content_hash, role, position FROM prompt_images"
                    " ORDER BY prompt_id, role, position"
                ):
                    images.setdefault(prompt_id, []).append(
                        {"content_hash": h, "role": role, "position": position}
                    )
                cursor = conn.execute(
                    "SELECT content_hash, format, width, height, size, api_prompt, workflow"
                    " FROM originals WHERE content_hash IN"
                    " (SELECT content_hash FROM prompt_images WHERE role = 'reference')"
                    " ORDER BY content_hash"
                )
                names = [d[0] for d in cursor.description]
                originals = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
            finally:
                conn.execute("ROLLBACK")
        for prompt in prompts:
            prompt_id = prompt.pop("id")
            prompt["settings"] = json.loads(prompt["settings"])
            prompt["tags"] = tags.get(prompt_id, [])
            prompt["images"] = images.get(prompt_id, [])
        return prompts, originals

    def import_rows(
        self, prompts: list[dict[str, Any]], originals: list[dict[str, Any]]
    ) -> tuple[int, int]:
        """Add prompts whose uid is new, in one transaction; returns (added, skipped).

        The originals' files must already be in place (`write_file`). A reference to an original
        that is not in the collection is dropped; attempts are kept as they are.
        """
        now = _now()
        added = skipped = 0
        with self._connect() as conn, transaction(conn):
            conn.executemany(
                "INSERT OR IGNORE INTO originals (content_hash, format, width, height, size,"
                " api_prompt, workflow, added_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        o["content_hash"],
                        o["format"],
                        o["width"],
                        o["height"],
                        o["size"],
                        o["api_prompt"],
                        o["workflow"],
                        now,
                    )
                    for o in originals
                ],
            )
            known = {r[0] for r in conn.execute("SELECT content_hash FROM originals")}
            for p in prompts:
                if conn.execute("SELECT 1 FROM prompts WHERE uid = ?", (p["uid"],)).fetchone():
                    skipped += 1
                    continue
                data = PromptData(
                    title=p["title"],
                    positive=p["positive"],
                    negative=p["negative"],
                    notes=p["notes"],
                    source_url=p["source_url"],
                    model_family=p["model_family"],
                    tags=p["tags"],
                    settings=p["settings"],
                )
                clean, _, _ = self._validated(data)
                prompt_id = conn.execute(
                    "INSERT INTO prompts (uid, title, positive, negative, positive_key, notes,"
                    " source_url, model_family, settings, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (p["uid"], *self._columns(clean), p["created_at"], p["updated_at"]),
                ).fetchone()[0]
                images = sorted(p["images"], key=lambda i: (i["role"], i["position"]))
                references = [
                    i["content_hash"]
                    for i in images
                    if i["role"] == "reference" and i["content_hash"] in known
                ]
                attempts = [i["content_hash"] for i in images if i["role"] == "attempt"]
                self._write_children(
                    conn,
                    prompt_id,
                    clean.tags,
                    _check_hashes(references),
                    [h for h in _check_hashes(attempts) if h not in references],
                )
                added += 1
            if added:
                self._bump(conn)
        return added, skipped


def _now() -> int:
    return int(time.time())
