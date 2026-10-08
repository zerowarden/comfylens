"""The saved-prompt collection as the filters see it.

A store that is unavailable or busy matches nothing rather than failing the library's requests.
"""

import sqlite3

import polars as pl

from comfylens.analytics import Snapshot, hash_matches, keyed_files, library_counts
from comfylens.api.errors import ApiError
from comfylens.api.server_base import CACHE_SIZE, _ServerBase
from comfylens.extract import prompt_key


class CollectionLookupMixin(_ServerBase):
    def saved_hashes(self) -> frozenset[str]:
        if self.collection is None:
            return frozenset()
        try:
            return self.collection.saved_hashes()
        except sqlite3.Error:
            return frozenset()

    def saved_prompt_ids(self, prompt_id: int) -> set[int]:
        """Files linked to the saved prompt, or whose positive prompt is the same text."""
        if self.collection is None:
            return set()
        try:
            links = self.collection.links(prompt_id)
        except sqlite3.Error:
            return set()
        if links is None:
            return set()
        snap = self.store.current
        key = (snap.built_at, links.revision, prompt_id)
        if key in self._saved:
            return self._saved[key]
        ids = set(hash_matches(snap, links.hashes)["id"].to_list())
        if links.key is not None:
            ids |= self._same_prompt(snap, links.key)
        if len(self._saved) >= CACHE_SIZE:
            self._saved.clear()
        self._saved[key] = ids
        return ids

    def _same_prompt(self, snap: Snapshot, key: int) -> set[int]:
        keyed = keyed_files(snap)
        if keyed is not None:
            return set(keyed.filter(pl.col("positive") == key)["file_id"].to_list())
        # Prompt frames are still being built: hash the catalog's prompts instead.
        try:
            conn = self.connect()
        except ApiError:
            return set()
        try:
            rows = conn.execute(
                "SELECT file_id, positive_prompt FROM generations WHERE positive_prompt != ''"
            ).fetchall()
        finally:
            conn.close()
        present = set(snap.images["id"].to_list())
        return {fid for fid, text in rows if fid in present and prompt_key(text) == key}

    def library_counts(self) -> dict[int, int] | None:
        """Per saved prompt, how many served files belong to it; None while prompts warm up."""
        if self.collection is None:
            return None
        return library_counts(self.store.current, self.collection.all_links())
