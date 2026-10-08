"""Saved-prompt CRUD: validation, tags, references and attempt links."""

import json
import sqlite3
import uuid
from typing import Any

from comfylens.collection.models import MAX_TITLE
from comfylens.collection.store_base import (
    InvalidInput,
    PromptData,
    UnknownOriginal,
    _check_hashes,
    _now,
    _StoreBase,
    key_hex,
    normalize_tags,
)
from comfylens.db import transaction
from comfylens.extract import prompt_key


class PromptsMixin(_StoreBase):
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
        PromptsMixin._add_attempts(conn, prompt_id, attempts, now)

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

    def rehash_attempts(self, renamed: dict[str, str], keep: set[str]) -> None:
        """Follow library files whose content hash changed: each attempt link to an old hash
        gains its new one, and loses the old one unless a file in `keep` still has it."""
        if not renamed:
            return
        with self._connect() as conn, transaction(conn):
            conn.executemany(
                "INSERT OR IGNORE INTO prompt_images (prompt_id, content_hash, role, position,"
                " added_at) SELECT prompt_id, ?, role, position, added_at FROM prompt_images"
                " WHERE content_hash = ? AND role = 'attempt'",
                [(new, old) for old, new in renamed.items()],
            )
            conn.executemany(
                "DELETE FROM prompt_images WHERE content_hash = ? AND role = 'attempt'",
                [(old,) for old in renamed if old not in keep],
            )
            self._bump(conn)

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
