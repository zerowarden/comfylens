"""Row marshalling for collection archives: every prompt and original as plain dicts.

The zip format itself lives in archive.py; this mixin owns the database side, so a change to
the archive's shape stays next to the prompt validation it relies on.
"""

import json
from typing import Any

from comfylens.collection.prompts import PromptsMixin
from comfylens.collection.store_base import PromptData, _check_hashes, _now
from comfylens.db import rows, transaction


class ArchiveRowsMixin(PromptsMixin):
    def export_rows(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Every prompt (fields, tags, images) and every original a prompt refers to, read in
        one transaction."""
        with self._connect() as conn:
            conn.execute("BEGIN")
            try:
                prompts = rows(
                    conn,
                    "SELECT uid, title, positive, negative, notes, source_url, model_family,"
                    " settings, created_at, updated_at, id FROM prompts ORDER BY id",
                )
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
                originals = rows(
                    conn,
                    "SELECT content_hash, format, width, height, size, api_prompt, workflow"
                    " FROM originals WHERE content_hash IN"
                    " (SELECT content_hash FROM prompt_images WHERE role = 'reference')"
                    " ORDER BY content_hash",
                )
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
