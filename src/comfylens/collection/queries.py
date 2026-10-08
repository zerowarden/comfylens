import json
from typing import Any

from comfylens.collection.models import Links, Role
from comfylens.collection.store_base import _key_int, _StoreBase, key_hex
from comfylens.db import like_pattern, rows


class QueriesMixin(_StoreBase):
    def get(self, prompt_id: int) -> dict[str, Any] | None:
        """Every field, tags, and images in order (references first) with original details."""
        with self._connect() as conn:
            found = rows(conn, "SELECT * FROM prompts WHERE id = ?", (prompt_id,))
            if not found:
                return None
            prompt = found[0]
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
        text = q.strip()
        fields = ("title", "positive", "negative", "notes")
        like = " OR ".join(f"p.{f} LIKE ? ESCAPE '\\'" for f in fields)
        tagged = "EXISTS (SELECT 1 FROM prompt_tags t WHERE t.prompt_id = p.id AND t.tag {})"
        searched = f"({like} OR {tagged.format("LIKE ? ESCAPE '\\'")})"
        # (clause, its parameters, the filter value that sets it)
        filters = [
            (searched, [like_pattern(text)] * (len(fields) + 1), text),
            (tagged.format("= ?"), [tag], tag),
            ("p.model_family = ?", [family], family),
        ]
        where = [clause for clause, _, value in filters if value]
        params = [param for _, values, value in filters if value for param in values]
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
            found = rows(conn, sql, params)
        for row in found:
            row["tags"] = json.loads(row["tags"])
        return found

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
