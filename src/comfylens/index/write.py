"""Catalog writes. Called from the indexer thread, inside transactions; file_ops reuses
`delete_files`."""

import json
import sqlite3
from collections.abc import Iterable, Sequence
from typing import Any

from comfylens.extract.types import Extraction
from comfylens.index.worker import Extracted, ParsedFile
from comfylens.warn import EXTRACTION_CODES, Warn

# Tables holding extraction output; re-extraction replaces their rows.
_EXTRACTION_TABLES = (
    "generations",
    "sampler_stages",
    "loras",
    "input_images",
    "nodes",
    "node_inputs",
)
_EXTRACTION_CODES = tuple(sorted(EXTRACTION_CODES))


def upsert_file(conn: sqlite3.Connection, p: ParsedFile, indexed_at: int) -> int:
    """Insert or update the files row by rel_path; returns its id."""
    row = conn.execute(
        "INSERT INTO files (rel_path, size, mtime_ns, content_hash, format, width, height,"
        " status, error, indexed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(rel_path) DO UPDATE SET size = excluded.size,"
        " mtime_ns = excluded.mtime_ns, content_hash = excluded.content_hash,"
        " format = excluded.format, width = excluded.width, height = excluded.height,"
        " status = excluded.status, error = excluded.error, indexed_at = excluded.indexed_at,"
        " timestamp_suspect = 0"  # the burst check re-flags it, with its warning
        " RETURNING id",
        (
            p.job.rel_path,
            p.job.size,
            p.job.mtime_ns,
            p.content_hash,
            p.format,
            p.width,
            p.height,
            p.extracted.status,
            p.extracted.error,
            indexed_at,
        ),
    ).fetchone()
    return row[0]


def write_parsed(conn: sqlite3.Connection, file_id: int, p: ParsedFile) -> None:
    """Replace every child row of a fully processed file."""
    for table in ("raw_metadata", "warnings", *_EXTRACTION_TABLES):
        conn.execute(f"DELETE FROM {table} WHERE file_id = ?", (file_id,))
    if p.texts:
        others = {k: v for k, v in p.texts.items() if k not in (p.prompt_key, p.workflow_key)}
        conn.execute(
            "INSERT INTO raw_metadata (file_id, sources, prompt_json, workflow_json, other_json)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                file_id,
                json.dumps(p.sources, ensure_ascii=False),
                p.texts.get(p.prompt_key) if p.prompt_key else None,
                p.texts.get(p.workflow_key) if p.workflow_key else None,
                json.dumps(others, ensure_ascii=False) if others else None,
            ),
        )
    _insert_warnings(conn, file_id, p.read_warnings)
    _insert_extracted(conn, file_id, p.extracted)


def write_reextracted(conn: sqlite3.Connection, file_id: int, e: Extracted) -> None:
    """Replace extraction output only; reading, thumbnail and timestamp warnings stay."""
    conn.execute(
        "UPDATE files SET status = ?, error = ? WHERE id = ?", (e.status, e.error, file_id)
    )
    for table in _EXTRACTION_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE file_id = ?", (file_id,))
    placeholders = ",".join("?" * len(_EXTRACTION_CODES))
    conn.execute(
        f"DELETE FROM warnings WHERE file_id = ? AND code IN ({placeholders})",
        (file_id, *_EXTRACTION_CODES),
    )
    _insert_extracted(conn, file_id, e)


def delete_files(conn: sqlite3.Connection, ids: Sequence[int]) -> None:
    """Child rows go with them (ON DELETE CASCADE)."""
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        conn.execute(f"DELETE FROM files WHERE id IN ({','.join('?' * len(chunk))})", chunk)


def _insert_warnings(conn: sqlite3.Connection, file_id: int, warnings: Iterable[Warn]) -> None:
    conn.executemany(
        "INSERT INTO warnings (file_id, code, node_id, message) VALUES (?, ?, ?, ?)",
        [(file_id, w.code.value, w.node_id, w.message) for w in warnings],
    )


def _seed(value: int | None) -> str | None:
    # Seeds reach 2**64 - 1, beyond SQLite's signed 64-bit INTEGER.
    return None if value is None else str(value)


def _insert_extracted(conn: sqlite3.Connection, file_id: int, e: Extracted) -> None:
    _insert_warnings(conn, file_id, e.warnings)
    conn.executemany(
        "INSERT INTO nodes (file_id, node_id, class_type, reachable) VALUES (?, ?, ?, ?)",
        [(file_id, node_id, class_type, reachable) for node_id, class_type, reachable in e.nodes],
    )
    x = e.extraction
    if x is None:
        return
    _insert_generation(conn, file_id, x)
    conn.executemany(
        "INSERT INTO sampler_stages (file_id, stage_index, node_id, class_type, seed, steps, cfg,"
        " sampler_name, scheduler, denoise, start_step, end_step, model_family, base_model,"
        " text_encoder, clip_type, lora_stack_key, positive_prompt, negative_prompt, guidance,"
        " shift, latent_source)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                file_id,
                s.index,
                s.node_id,
                s.class_type,
                _seed(s.seed),
                s.steps,
                s.cfg,
                s.sampler_name,
                s.scheduler,
                s.denoise,
                s.start_step,
                s.end_step,
                s.model_family,
                s.base_model,
                s.text_encoder,
                s.clip_type,
                s.lora_stack_key,
                s.positive_prompt,
                s.negative_prompt,
                s.guidance,
                s.shift,
                s.latent_source,
            )
            for s in x.stages
        ],
    )
    conn.executemany(
        "INSERT INTO loras (file_id, stage_index, node_id, entry, position, class_type, name_raw,"
        " name, base_name, step, strength_model, strength_clip, enabled, reachable)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                file_id,
                u.stage_index,
                u.node_id,
                u.entry,
                u.position,
                u.class_type,
                u.name_raw,
                u.name,
                u.base_name,
                u.step,
                u.strength_model,
                u.strength_clip,
                u.enabled,
                u.reachable,
            )
            for u in x.loras
        ],
    )
    conn.executemany(
        "INSERT INTO input_images (file_id, node_id, filename, sha256) VALUES (?, ?, ?, ?)",
        [(file_id, i.node_id, i.filename, i.sha256) for i in x.input_images],
    )
    conn.executemany(
        "INSERT INTO node_inputs (file_id, node_id, class_type, input_name, kind, value_num,"
        " value_text, reachable) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (file_id, g.node_id, g.class_type, g.input_name, g.kind, *_value(g.value), g.reachable)
            for g in x.generic_inputs
        ],
    )


def _insert_generation(conn: sqlite3.Connection, file_id: int, x: Extraction) -> None:
    p = x.primary
    conn.execute(
        "INSERT INTO generations (file_id, model_family, base_model, text_encoder, clip_type,"
        " vae, seed, steps, cfg, sampler_name, scheduler, denoise, guidance, shift, stage_count,"
        " latent_source, batch_size, positive_prompt, negative_prompt, stage_prompts,"
        " lora_stack_key, config_key, generation_key)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            file_id,
            x.model_family,
            x.base_model,
            x.text_encoder,
            x.clip_type,
            x.vae,
            _seed(p.seed) if p else None,
            p.steps if p else None,
            p.cfg if p else None,
            p.sampler_name if p else None,
            p.scheduler if p else None,
            p.denoise if p else None,
            x.guidance,
            x.shift,
            len(x.stages),
            x.latent_source,
            x.batch_size,
            x.positive_prompt,
            x.negative_prompt,
            x.stage_prompts,
            x.lora_stack_key,
            x.config_key,
            x.generation_key,
        ),
    )


def _value(value: Any) -> tuple[float | None, str | None]:
    """(value_num, value_text) for a generic input: bools and numbers as REAL, else text."""
    if isinstance(value, bool | int | float):
        try:
            return float(value), None
        except OverflowError:  # an integer beyond float range
            return None, str(value)
    return None, value
