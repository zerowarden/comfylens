"""Catalog prompt search and prompt-frame lookups: FTS5 phrase first, LIKE fallback."""

import sqlite3

import polars as pl

from comfylens.api.server_base import CACHE_SIZE, _ServerBase
from comfylens.db import like_pattern


class SearchMixin(_ServerBase):
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
                pattern = like_pattern(text)
                rows = conn.execute(
                    "SELECT file_id FROM generations WHERE positive_prompt LIKE ? ESCAPE '\\'"
                    " OR negative_prompt LIKE ? ESCAPE '\\' OR stage_prompts LIKE ? ESCAPE '\\'",
                    (pattern, pattern, pattern),
                ).fetchall()
                ids = {r[0] for r in rows}
        finally:
            conn.close()
        if len(self._search) >= CACHE_SIZE:
            self._search.clear()
        self._search[key] = ids
        return ids

    def sentence_ids(self, hashes: set[int]) -> set[int]:
        """File ids whose prompt holds one of these sentence hashes, either side.

        Prompt frames keep the rows of trashed files; the caller intersects with the snapshot.
        """
        frames = self.store.current.prompts
        if frames is None or not hashes:
            return set()
        keys = frames.sentences.filter(pl.col("sentence").is_in(sorted(hashes)))["key"].unique()
        if keys.len() == 0:
            return set()
        present = frames.file_keys.filter(
            pl.col("positive").is_in(keys.implode()) | pl.col("negative").is_in(keys.implode())
        )
        return set(present["file_id"].to_list())
