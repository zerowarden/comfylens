"""Catalog reads into Polars frames, for the report and the analytics snapshot."""

import sqlite3
from typing import Any

import polars as pl

FILES_SCHEMA: dict[str, Any] = {
    "id": pl.Int64,
    "rel_path": pl.String,
    "content_hash": pl.String,
    "format": pl.String,
    "status": pl.String,
    "width": pl.Int64,
    "height": pl.Int64,
    "mtime_ns": pl.Int64,
    "generated_at": pl.Int64,
    "timestamp_suspect": pl.Boolean,
}

GENERATIONS_SCHEMA: dict[str, Any] = {
    "file_id": pl.Int64,
    "model_family": pl.String,
    "base_model": pl.String,
    "text_encoder": pl.String,
    "clip_type": pl.String,
    "vae": pl.String,
    "seed": pl.String,  # TEXT in SQLite: up to 2**64 - 1
    "steps": pl.Int64,
    "cfg": pl.Float64,
    "sampler_name": pl.String,
    "scheduler": pl.String,
    "denoise": pl.Float64,
    "guidance": pl.Float64,
    "shift": pl.Float64,
    "stage_count": pl.Int64,
    "latent_source": pl.String,
    "batch_size": pl.Int64,
    "lora_stack_key": pl.String,
    "config_key": pl.String,
    "generation_key": pl.String,
}

TAGS_SCHEMA: dict[str, Any] = {"file_id": pl.Int64, "tags": pl.List(pl.String)}

LORAS_SCHEMA: dict[str, Any] = {
    "file_id": pl.Int64,
    "name": pl.String,
    "base_name": pl.String,
    "step": pl.Int64,
    "position": pl.Int64,
    "strength_model": pl.Float64,
    "strength_clip": pl.Float64,
}


def _frame(
    conn: sqlite3.Connection, table: str, schema: dict[str, Any], where: str = ""
) -> pl.DataFrame:
    rows = conn.execute(f"SELECT {', '.join(schema)} FROM {table} {where}").fetchall()
    return pl.DataFrame(rows, schema=schema, orient="row")


def files_frame(conn: sqlite3.Connection) -> pl.DataFrame:
    return _frame(conn, "files", FILES_SCHEMA)


def generations_frame(conn: sqlite3.Connection) -> pl.DataFrame:
    """Every scalar generations column; prompts are loaded separately."""
    return _frame(conn, "generations", GENERATIONS_SCHEMA)


def tags_frame(conn: sqlite3.Connection) -> pl.DataFrame:
    """Each tagged file's tags, sorted."""
    tags = _frame(conn, "tags", {"file_id": pl.Int64, "tag": pl.String}, "ORDER BY file_id, tag")
    return tags.group_by("file_id", maintain_order=True).agg(pl.col("tag").alias("tags"))


def loras_frame(conn: sqlite3.Connection) -> pl.DataFrame:
    """Reachable, enabled LoRA uses: the only ones that count in statistics.

    A LoRA shared by several stages counts once, as its earliest stage's row.
    """
    return _frame(
        conn,
        "loras",
        LORAS_SCHEMA,
        "WHERE reachable = 1 AND enabled = 1 AND stage_index = (SELECT MIN(s.stage_index)"
        " FROM loras s WHERE s.file_id = loras.file_id AND s.node_id = loras.node_id"
        " AND s.entry = loras.entry)",
    )
