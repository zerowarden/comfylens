"""Reference-image storage: exact original bytes on disk, metadata rows, garbage collection."""

import time
from pathlib import Path
from typing import Any

from comfylens.collection.models import EXTENSIONS, OriginalFormat
from comfylens.collection.store_base import GC_GRACE_SECONDS, HASH, _now, _StoreBase
from comfylens.db import transaction
from comfylens.fileio import write_atomic
from comfylens.metadata import hash_content


class OriginalsMixin(_StoreBase):
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
        content_hash = hash_content(data)
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
        write_atomic(target, lambda f: f.write(data))

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
