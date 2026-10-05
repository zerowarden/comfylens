"""Catalog writes. Called from the indexer thread, inside transactions; file_ops reuses
`delete_files`.

Each INSERT derives its column list from the named tuple below, so reordering a value tuple
and its columns at the same time is impossible. test_schema_sync checks those tuples against
the dataclasses and db/schema.sql.
"""

import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import fields
from typing import Any

from comfylens.db.connection import chunks, placeholders
from comfylens.extract.types import Extraction, LoraUse, SamplerStage
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

FILES_COLUMNS = (
    "rel_path",
    "size",
    "mtime_ns",
    "content_hash",
    "format",
    "width",
    "height",
    "status",
    "error",
    "indexed_at",
)
GENERATIONS_COLUMNS = (
    "model_family",
    "base_model",
    "text_encoder",
    "clip_type",
    "vae",
    "seed",
    "steps",
    "cfg",
    "sampler_name",
    "scheduler",
    "denoise",
    "guidance",
    "shift",
    "stage_count",
    "latent_source",
    "batch_size",
    "positive_prompt",
    "negative_prompt",
    "stage_prompts",
    "lora_stack_key",
    "config_key",
    "generation_key",
)
SAMPLER_STAGE_COLUMNS = (
    "stage_index",
    "node_id",
    "class_type",
    "seed",
    "steps",
    "cfg",
    "sampler_name",
    "scheduler",
    "denoise",
    "start_step",
    "end_step",
    "model_family",
    "base_model",
    "text_encoder",
    "clip_type",
    "lora_stack_key",
    "positive_prompt",
    "negative_prompt",
    "guidance",
    "shift",
    "latent_source",
)
LORA_COLUMNS = (
    "stage_index",
    "node_id",
    "entry",
    "position",
    "class_type",
    "name_raw",
    "name",
    "base_name",
    "step",
    "strength_model",
    "strength_clip",
    "enabled",
    "reachable",
)
# SamplerStage names the column `stage_index`; every other field name is a column name.
SAMPLER_STAGE_RENAMES = {"index": "stage_index"}


def _insert_sql(table: str, columns: tuple[str, ...]) -> str:
    names = ", ".join(("file_id", *columns))
    marks = ", ".join("?" * (len(columns) + 1))
    return f"INSERT INTO {table} ({names}) VALUES ({marks})"


def _by_column(
    values: dict[str, Any], renames: dict[str, str], columns: tuple[str, ...]
) -> tuple[Any, ...]:
    for before, after in renames.items():
        values[after] = values.pop(before)
    return tuple(values[column] for column in columns)


def _dataclass_values(instance: Any) -> dict[str, Any]:
    return {f.name: getattr(instance, f.name) for f in fields(instance)}


_FILES_INSERT = (
    "INSERT INTO files ("
    + ", ".join(FILES_COLUMNS)
    + ") VALUES ("
    + ", ".join("?" * len(FILES_COLUMNS))
    + ")"
    + " ON CONFLICT(rel_path) DO UPDATE SET "
    + ", ".join(f"{c} = excluded.{c}" for c in FILES_COLUMNS if c != "rel_path")
    + ", timestamp_suspect = 0"  # the burst check re-flags it, with its warning
    + " RETURNING id"
)
_STAGE_INSERT = _insert_sql("sampler_stages", SAMPLER_STAGE_COLUMNS)
_LORA_INSERT = _insert_sql("loras", LORA_COLUMNS)
_GENERATION_INSERT = _insert_sql("generations", GENERATIONS_COLUMNS)


def upsert_file(conn: sqlite3.Connection, p: ParsedFile, indexed_at: int) -> int:
    """Insert or update the files row by rel_path; returns its id."""
    values: dict[str, Any] = {
        "rel_path": p.job.rel_path,
        "size": p.job.size,
        "mtime_ns": p.job.mtime_ns,
        "content_hash": p.content_hash,
        "format": p.format,
        "width": p.width,
        "height": p.height,
        "status": p.extracted.status,
        "error": p.extracted.error,
        "indexed_at": indexed_at,
    }
    row = conn.execute(_FILES_INSERT, tuple(values[c] for c in FILES_COLUMNS)).fetchone()
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
    for chunk in chunks(ids):
        conn.execute(f"DELETE FROM files WHERE id IN ({placeholders(len(chunk))})", chunk)


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
        _STAGE_INSERT,
        [(file_id, *_stage_values(s)) for s in x.stages],
    )
    conn.executemany(
        _LORA_INSERT,
        [(file_id, *_lora_values(u)) for u in x.loras],
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


def _stage_values(s: SamplerStage) -> tuple[Any, ...]:
    values = _dataclass_values(s)
    values["seed"] = _seed(s.seed)
    return _by_column(values, SAMPLER_STAGE_RENAMES, SAMPLER_STAGE_COLUMNS)


def _lora_values(u: LoraUse) -> tuple[Any, ...]:
    return _by_column(_dataclass_values(u), {}, LORA_COLUMNS)


def _insert_generation(conn: sqlite3.Connection, file_id: int, x: Extraction) -> None:
    p = x.primary
    values: dict[str, Any] = {
        "model_family": x.model_family,
        "base_model": x.base_model,
        "text_encoder": x.text_encoder,
        "clip_type": x.clip_type,
        "vae": x.vae,
        "seed": _seed(p.seed) if p else None,
        "steps": p.steps if p else None,
        "cfg": p.cfg if p else None,
        "sampler_name": p.sampler_name if p else None,
        "scheduler": p.scheduler if p else None,
        "denoise": p.denoise if p else None,
        "guidance": x.guidance,
        "shift": x.shift,
        "stage_count": len(x.stages),
        "latent_source": x.latent_source,
        "batch_size": x.batch_size,
        "positive_prompt": x.positive_prompt,
        "negative_prompt": x.negative_prompt,
        "stage_prompts": x.stage_prompts,
        "lora_stack_key": x.lora_stack_key,
        "config_key": x.config_key,
        "generation_key": x.generation_key,
    }
    conn.execute(_GENERATION_INSERT, (file_id, *(values[c] for c in GENERATIONS_COLUMNS)))


def _value(value: Any) -> tuple[float | None, str | None]:
    """(value_num, value_text) for a generic input: bools and numbers as REAL, else text."""
    if isinstance(value, bool | int | float):
        try:
            return float(value), None
        except OverflowError:  # an integer beyond float range
            return None, str(value)
    return None, value
