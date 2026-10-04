"""Incremental indexing.

Unchanged files are skipped by path, size and mtime; new and changed files are read once in a
process pool; every database write happens in the indexer thread.
"""

import json
import sqlite3
import time
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from time import perf_counter
from typing import Literal

from comfylens import version
from comfylens.config import Config, resolve_workers
from comfylens.db.connection import has_fts, open_catalog, set_meta, transaction
from comfylens.index.lock import IndexLock
from comfylens.index.scanner import scan
from comfylens.index.timestamps import Cluster, burst_clusters, generated_at
from comfylens.index.worker import (
    Job,
    ParsedFile,
    Reextracted,
    Settings,
    ThumbJob,
    ThumbOutcome,
    init_pool,
    pool_process_file,
    pool_reextract,
    pool_restore_thumbnail,
    process_file,
    reextract,
    restore_thumbnail,
)
from comfylens.index.write import delete_files, upsert_file, write_parsed, write_reextracted
from comfylens.paths import catalog_path, lock_path, thumb_path, thumbs_dir
from comfylens.warn import Code

State = Literal["idle", "scanning", "processing", "finalizing"]


class UnsafeLocation(RuntimeError):
    """App state would be written inside the library directory."""


@dataclass(frozen=True, slots=True)
class IndexStatus:
    state: State = "idle"
    total: int = 0
    done: int = 0
    errors: int = 0
    started_at: float | None = None


@dataclass(slots=True)
class IndexResult:
    scanned: int = 0
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    deleted: int = 0
    reextracted: int = 0
    errors: int = 0  # files processed or re-extracted in this run that ended with status error
    skipped_names: int = 0  # names that are not valid UTF-8
    thumbnails_written: int = 0  # including missing thumbnails of unchanged files
    thumbnails_failed: int = 0  # missing thumbnails of unchanged files that could not be written
    seconds: float = 0.0
    seconds_metadata: float = 0.0  # summed over workers
    seconds_thumbnail: float = 0.0
    seconds_reextract: float = 0.0
    workers: int = 1
    clusters: list[Cluster] = field(default_factory=list)


def _suspect_message(cluster: Cluster) -> str:
    return (
        f"mtime is in a burst of {cluster.distinct_generations} distinct generations within"
        f" {(cluster.end_ns - cluster.start_ns) / 1e9:.1f} s; likely a bulk copy"
    )


class Indexer:
    def __init__(
        self,
        root: Path,
        config: Config,
        *,
        workers: int | None = None,
        on_status: Callable[[IndexStatus], None] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.config = config
        self.workers = resolve_workers(config.index.workers if workers is None else workers)
        self.status = IndexStatus()
        self._on_status = on_status

    def _set(self, **changes: object) -> None:
        self.status = replace(self.status, **changes)  # type: ignore[arg-type]
        if self._on_status is not None:
            self._on_status(self.status)

    def run(self, *, full: bool = False, reextract_all: bool = False) -> IndexResult:
        """Index the library. `full` re-reads every file; `reextract_all` re-extracts every
        unchanged file from raw JSON. Raises IndexLocked when another process is indexing."""
        catalog_file, thumbs = catalog_path(self.root), thumbs_dir()
        for location in (catalog_file.parent, thumbs):
            if location.resolve().is_relative_to(self.root):
                raise UnsafeLocation(f"{location} is inside the library {self.root}")
        with IndexLock(lock_path(self.root)):
            catalog = open_catalog(catalog_file, self.root, self.config.config_hash)
            try:
                return self._run(
                    catalog.conn, thumbs, full=full, reextract_all=reextract_all or catalog.stale
                )
            finally:
                catalog.conn.close()
                self._set(state="idle")

    def _run(
        self, conn: sqlite3.Connection, thumbs: Path, *, full: bool, reextract_all: bool
    ) -> IndexResult:
        result = IndexResult(workers=self.workers)
        start = perf_counter()
        self._set(state="scanning", total=0, done=0, errors=0, started_at=time.time())

        cfg = self.config.index
        scanned = scan(self.root, cfg.extensions, cfg.exclude_globs, cfg.follow_symlinks)
        result.scanned, result.skipped_names = len(scanned.files), scanned.skipped_names
        existing = {
            rel: (file_id, size, mtime)
            for file_id, rel, size, mtime in conn.execute(
                "SELECT id, rel_path, size, mtime_ns FROM files"
            )
        }
        on_disk = {f.rel_path for f in scanned.files}
        deleted = [file_id for rel, (file_id, _, _) in existing.items() if rel not in on_disk]
        jobs: list[Job] = []
        unchanged: list[int] = []
        for f in scanned.files:
            old = existing.get(f.rel_path)
            if old is None:
                result.new += 1
            elif full or (old[1], old[2]) != (f.size, f.mtime_ns):
                result.changed += 1
            else:
                unchanged.append(old[0])
                continue
            jobs.append(Job(f.rel_path, f.size, f.mtime_ns))
        result.unchanged = len(unchanged)

        redo: list[int] = []
        if reextract_all and unchanged:
            with_prompt = {
                r[0]
                for r in conn.execute(
                    "SELECT file_id FROM raw_metadata WHERE prompt_json IS NOT NULL"
                )
            }
            redo = [i for i in unchanged if i in with_prompt]

        restore = self._missing_thumbnails(conn, thumbs, unchanged)

        if deleted:
            with transaction(conn):
                delete_files(conn, deleted)
            result.deleted = len(deleted)

        work = len(jobs) + len(redo) + len(restore)
        self._set(state="processing", total=work)
        settings = Settings(self.root, thumbs, self.config)
        if self.workers > 1 and work > 1:
            pool = ProcessPoolExecutor(self.workers, initializer=init_pool, initargs=(settings,))
            try:
                ahead = self.workers * 4  # chunks in flight; bounds memory for large libraries
                self._write_parsed(
                    conn, pool.map(pool_process_file, jobs, chunksize=16, buffersize=ahead), result
                )
                prompts = self._prompts(redo)
                self._write_reextracted(
                    conn, pool.map(pool_reextract, prompts, chunksize=16, buffersize=ahead), result
                )
                self._count_restored(
                    pool.map(pool_restore_thumbnail, restore, chunksize=16, buffersize=ahead),
                    result,
                )
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
        else:
            self._write_parsed(conn, (process_file(j, settings) for j in jobs), result)
            self._write_reextracted(
                conn, (reextract(i, text, settings) for i, text in self._prompts(redo)), result
            )
            self._count_restored((restore_thumbnail(j, settings) for j in restore), result)

        self._set(state="finalizing")
        changed = bool(jobs or redo or deleted)
        with transaction(conn):
            result.clusters = self._timestamps(conn)
            if changed and has_fts(conn):
                conn.execute("INSERT INTO prompts_fts(prompts_fts) VALUES('rebuild')")
            result.seconds = perf_counter() - start
            set_meta(conn, "extractor_version", str(version.EXTRACTOR_VERSION))
            set_meta(conn, "config_hash", self.config.config_hash)
            set_meta(conn, "last_index_at", str(int(time.time())))
            if jobs or redo:  # timing of the last run that did work, for the report
                stats = {k: v for k, v in asdict(result).items() if k != "clusters"}
                set_meta(conn, "last_index_stats", json.dumps(stats))
            set_meta(conn, "timestamp_clusters", json.dumps([c.to_json() for c in result.clusters]))
        return result

    def _batches[T](self, items: Iterable[T]) -> Iterator[list[T]]:
        batch: list[T] = []
        for item in items:
            batch.append(item)
            if len(batch) >= self.config.index.batch_size:
                yield batch
                batch = []
        if batch:
            yield batch

    def _write_parsed(
        self, conn: sqlite3.Connection, parsed: Iterable[ParsedFile], result: IndexResult
    ) -> None:
        for batch in self._batches(parsed):
            now = int(time.time())
            with transaction(conn):
                for p in batch:
                    write_parsed(conn, upsert_file(conn, p, now), p)
            for p in batch:
                result.errors += p.extracted.status == "error"
                result.seconds_metadata += p.seconds_metadata
                result.seconds_thumbnail += p.seconds_thumbnail
                result.thumbnails_written += p.thumbnail_written
            self._set(done=self.status.done + len(batch), errors=result.errors)

    def _write_reextracted(
        self, conn: sqlite3.Connection, items: Iterable[Reextracted], result: IndexResult
    ) -> None:
        for batch in self._batches(items):
            with transaction(conn):
                for r in batch:
                    write_reextracted(conn, r.file_id, r.extracted)
            for r in batch:
                result.errors += r.extracted.status == "error"
                result.seconds_reextract += r.seconds
            result.reextracted += len(batch)
            self._set(done=self.status.done + len(batch), errors=result.errors)

    def _count_restored(self, outcomes: Iterable[ThumbOutcome], result: IndexResult) -> None:
        for batch in self._batches(outcomes):
            result.thumbnails_written += batch.count("written")
            result.thumbnails_failed += batch.count("failed")
            self._set(done=self.status.done + len(batch))

    def _missing_thumbnails(
        self, conn: sqlite3.Connection, thumbs: Path, unchanged: list[int]
    ) -> list[ThumbJob]:
        """One job per content hash of the unchanged files whose thumbnail is not in the cache,
        e.g. after the cache was cleared. Files that could not be read, or whose thumbnail
        already failed when they were read, are left out: retrying them would fail again."""
        ids = set(unchanged)
        missing: dict[str, ThumbJob] = {}
        for file_id, rel_path, content_hash in conn.execute(
            "SELECT id, rel_path, content_hash FROM files f WHERE content_hash != ''"
            " AND NOT EXISTS (SELECT 1 FROM warnings w WHERE w.file_id = f.id AND w.code = ?)",
            (Code.THUMBNAIL_FAILED.value,),
        ):
            if (
                file_id in ids
                and content_hash not in missing
                and not thumb_path(thumbs, content_hash).is_file()
            ):
                missing[content_hash] = ThumbJob(rel_path, content_hash)
        return list(missing.values())

    def _prompts(self, ids: list[int]) -> Iterator[tuple[int, str]]:
        """Stored API prompts, read lazily on a separate connection while the writer works."""
        if not ids:
            return
        reader = sqlite3.connect(catalog_path(self.root), autocommit=True)
        try:
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                yield from reader.execute(
                    "SELECT file_id, prompt_json FROM raw_metadata"
                    f" WHERE file_id IN ({','.join('?' * len(chunk))})",
                    chunk,
                ).fetchall()
        finally:
            reader.close()

    def _timestamps(self, conn: sqlite3.Connection) -> list[Cluster]:
        """generated_at for every file, then the burst check."""
        ts = self.config.timestamps
        updates = []
        for file_id, rel_path, mtime_ns, current in conn.execute(
            "SELECT id, rel_path, mtime_ns, generated_at FROM files"
        ).fetchall():
            value = generated_at(rel_path, mtime_ns, ts)
            if value != current:
                updates.append((value, file_id))
        conn.executemany("UPDATE files SET generated_at = ? WHERE id = ?", updates)

        rows = conn.execute(
            "SELECT f.id, f.mtime_ns, g.generation_key FROM files f"
            " JOIN generations g ON g.file_id = f.id WHERE g.generation_key IS NOT NULL"
        ).fetchall()
        clusters = burst_clusters(rows, ts.burst_window_seconds, ts.burst_min_distinct)
        flagged = {r[0] for r in conn.execute("SELECT id FROM files WHERE timestamp_suspect = 1")}
        suspect = {i: c for c in clusters for i in c.file_ids}

        cleared = [(i,) for i in flagged - suspect.keys()]
        conn.executemany("UPDATE files SET timestamp_suspect = 0 WHERE id = ?", cleared)
        conn.executemany(
            "DELETE FROM warnings WHERE file_id = ? AND code = 'TIMESTAMP_SUSPECT'", cleared
        )
        # Rewrite every suspect file's warning, not only the newly flagged ones: a cluster can
        # grow after a file was flagged, and its message must keep counting its members.
        conn.executemany(
            "DELETE FROM warnings WHERE file_id = ? AND code = 'TIMESTAMP_SUSPECT'",
            [(i,) for i in suspect],
        )
        added = [(i,) for i in suspect if i not in flagged]
        conn.executemany("UPDATE files SET timestamp_suspect = 1 WHERE id = ?", added)
        conn.executemany(
            "INSERT INTO warnings (file_id, code, node_id, message) VALUES (?, ?, NULL, ?)",
            [(i, Code.TIMESTAMP_SUSPECT.value, _suspect_message(c)) for i, c in suspect.items()],
        )
        return clusters
