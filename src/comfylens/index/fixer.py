"""The library Fix: rewrites image metadata in place, file by file.

One fix so far: LoRAs that cannot affect the image leave the API prompt and the workflow
(extract.cleanup). PNG only: JPEG keeps its metadata in EXIF, which is not rewritten. Only the
changed text chunks differ afterwards; pixels, other metadata and the modification time stay.

The catalog is left as it was: the caller re-reads the fixed files with an index run.
"""

import json
import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from comfylens.config import Config
from comfylens.extract import (
    Analysis,
    Cleanup,
    analyze,
    clean_prompt,
    clean_workflow,
    mirrored,
    plan_cleanup,
)
from comfylens.index.file_ops import FileMissing, Unrewritable, failure, rewrite
from comfylens.metadata import CannotRewrite, RawMetadata, hash_content, replace_png_texts
from comfylens.warn import Code

# Files a fix may change: PNGs with a LoRA on no sampler's chain, or one switched off.
_CANDIDATES = (
    "SELECT id FROM files f WHERE format = 'png' AND ("
    " EXISTS (SELECT 1 FROM warnings w WHERE w.file_id = f.id AND w.code = ?)"
    " OR EXISTS (SELECT 1 FROM loras l WHERE l.file_id = f.id AND l.enabled = 0))"
    " ORDER BY id"
)


@dataclass(slots=True)
class Fixed:
    changed: dict[str, tuple[str, str]] = field(default_factory=dict)  # path -> old, new hash
    failed: list[str] = field(default_factory=list)  # "path: reason"
    # Old hashes that files left as they were still have, e.g. a failed identical copy.
    kept_hashes: set[str] = field(default_factory=set)


def fix_file(data: bytes, config: Config) -> bytes | None:
    """`data` with its metadata fixed; None when there is nothing to fix."""
    found = _cleanup(analyze(data, config))
    if found is None:
        return None
    raw, prompt_key, prompt, cleanup = found
    # As ComfyUI writes them: json.dumps with its default separators, ASCII only.
    texts = {raw.texts[prompt_key]: json.dumps(clean_prompt(prompt, cleanup))}
    if raw.workflow is not None and raw.workflow_key is not None:
        texts[raw.texts[raw.workflow_key]] = json.dumps(clean_workflow(raw.workflow, cleanup))
    return replace_png_texts(data, texts)


def _cleanup(a: Analysis) -> tuple[RawMetadata, str, dict[str, Any], Cleanup] | None:
    """The file's metadata, its API prompt's key and value, and what to clean; None when there
    is no graph or nothing to clean."""
    raw = a.raw
    if raw is None or raw.api_prompt is None or raw.api_prompt_key is None:
        return None
    if a.graph is None or a.reach is None:
        return None
    cleanup = plan_cleanup(a.graph, a.reach)
    if raw.workflow is not None:  # what the workflow cannot mirror stays in both
        cleanup = mirrored(raw.workflow, cleanup)
    return (raw, raw.api_prompt_key, raw.api_prompt, cleanup) if cleanup else None


def fix_library(
    root: Path,
    conn: sqlite3.Connection,
    config: Config,
    *,
    guard: AbstractContextManager[object],
    progress: Callable[[int, int], None],
) -> Fixed:
    """Fix every candidate file. Each file is read and written under `guard`, which keeps the
    UI's own edits (rename, tags, trash) from interleaving with it."""
    ids = [row[0] for row in conn.execute(_CANDIDATES, (Code.UNUSED_LORA.value,))]
    result = Fixed()
    for done, file_id in enumerate(ids):
        progress(done, len(ids))
        with guard:
            _fix_row(root, conn, config, file_id, result)
    progress(len(ids), len(ids))
    olds = {old for old, _ in result.changed.values()}
    result.kept_hashes = {
        h
        for rel_path, h in conn.execute("SELECT rel_path, content_hash FROM files")
        if h in olds and rel_path not in result.changed
    }
    return result


def _fix_row(
    root: Path, conn: sqlite3.Connection, config: Config, file_id: int, result: Fixed
) -> None:
    # Read now, not when the run started: an edit may have renamed or retagged the file since.
    row = conn.execute(
        "SELECT rel_path, size, mtime_ns, content_hash FROM files WHERE id = ?", (file_id,)
    ).fetchone()
    if row is None:  # trashed meanwhile
        return
    rel_path, size, mtime_ns, old_hash = row
    try:
        data = rewrite(root, rel_path, size, mtime_ns, lambda data: fix_file(data, config))
    except (CannotRewrite, Unrewritable, FileMissing, OSError) as e:
        result.failed.append(failure(rel_path, e))
        return
    if data is not None:
        result.changed[rel_path] = (old_hash, hash_content(data))
