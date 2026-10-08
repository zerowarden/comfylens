"""`comfylens report` data: what the index found, and what extraction still misses."""

import json
import sqlite3
from typing import Any

import polars as pl

from comfylens.analytics import (
    NO_LOOKUP,
    Scope,
    Snapshot,
    compute_stats,
    resolve,
    snapshot_from_conn,
)
from comfylens.config import Config
from comfylens.db import is_stale
from comfylens.extract import UNKNOWN, unregistered
from comfylens.warn import INFORMATIONAL_CODES

TOP_LORAS = 10
TOP_CONFIGS = 5
TOP_UNUSED_LORAS = 20
TOP_UNKNOWN_MODELS = 10


def build_report(
    conn: sqlite3.Connection, config: Config, *, family: str | None = None
) -> dict[str, Any]:
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    snap = snapshot_from_conn(conn)
    gens = snap.images.filter("has_generation")
    return {
        "library": {
            "root": meta.get("library_root"),
            "last_index_at": _int(meta.get("last_index_at")),
            "stale": is_stale(conn, config.config_hash),
        },
        "files": _files(snap.images),
        "families": _families(gens),
        "unregistered": _unregistered(conn, config),
        "warnings": _warnings(conn),
        "timestamp_clusters": json.loads(meta.get("timestamp_clusters", "[]")),
        "per_family": _per_family(snap, config, family),
        "timing": _timing(meta.get("last_index_stats")),
    }


def _int(value: str | None) -> int | None:
    return int(value) if value else None


def _files(files: pl.DataFrame) -> dict[str, Any]:
    total = files.height
    ok = int((files["status"] == "ok").sum())
    counts = (
        files.group_by("status", "format").len().sort("len", "status", descending=[True, False])
    )
    return {
        "total": total,
        "ok": ok,
        "parse_success_rate": ok / total if total else None,
        "by_status_format": [
            {"status": s, "format": f, "files": n} for s, f, n in counts.iter_rows()
        ],
    }


def _families(gens: pl.DataFrame) -> dict[str, Any]:
    counts = (
        gens.group_by("model_family").len().sort("len", "model_family", descending=[True, False])
    )
    unknown = (
        gens.filter(pl.col("model_family") == UNKNOWN)
        .group_by("base_model")
        .len()
        .sort("len", "base_model", descending=[True, False])
        .head(TOP_UNKNOWN_MODELS)
    )
    return {
        "counts": [{"family": f, "files": n} for f, n in counts.iter_rows()],
        "unknown_base_models": [{"base_model": m, "files": n} for m, n in unknown.iter_rows()],
    }


def _unregistered(conn: sqlite3.Connection, config: Config) -> list[dict[str, Any]]:
    """Reachable class_types with no handler, by the number of files they appear in."""
    counts = dict(
        conn.execute(
            "SELECT class_type, COUNT(DISTINCT file_id) FROM nodes WHERE reachable = 1"
            " GROUP BY class_type"
        ).fetchall()
    )
    missing = unregistered(counts, config.graph.output_classes)
    ranked = sorted(missing, key=lambda c: (-counts[c], c))
    return [{"class_type": c, "files": counts[c]} for c in ranked]


def _warnings(conn: sqlite3.Connection) -> dict[str, Any]:
    codes = conn.execute(
        "SELECT code, COUNT(*), COUNT(DISTINCT file_id) FROM warnings GROUP BY code"
        " ORDER BY 2 DESC, 1"
    ).fetchall()
    unused = conn.execute(
        "SELECT name, COUNT(DISTINCT file_id) FROM loras WHERE reachable = 0"
        " GROUP BY name ORDER BY 2 DESC, 1 LIMIT ?",
        (TOP_UNUSED_LORAS,),
    ).fetchall()
    return {
        "codes": [
            {"code": c, "count": n, "files": f, "informational": c in INFORMATIONAL_CODES}
            for c, n, f in codes
        ],
        "unused_loras": [{"name": name, "files": n} for name, n in unused],
    }


def _per_family(snap: Snapshot, config: Config, only: str | None) -> list[dict[str, Any]]:
    """Numeric table, top LoRAs and top configurations per family, never across families.

    Uses the same snapshot and statistics as the UI, so the two cannot disagree.
    """
    analysis = config.analysis
    resolved = resolve(snap, Scope(), analysis, NO_LOOKUP)
    blocks = compute_stats(snap, resolved, ["numeric", "loras", "configs"], "name", analysis)
    out = []
    for block in blocks:
        if only is not None and block["family"] != only:
            continue
        block["loras"] = block["loras"][:TOP_LORAS]
        block["configs"] = block["configs"][:TOP_CONFIGS]
        out.append(block)
    return out


def _timing(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    s = json.loads(raw)
    processed = s["new"] + s["changed"]

    def rate(count: int, seconds: float) -> float | None:
        return count / seconds if seconds > 0 and count else None

    return {
        "workers": s["workers"],
        "processed": processed,
        "reextracted": s["reextracted"],
        "seconds": s["seconds"],
        # Per-stage rates are per worker: seconds are summed across the pool.
        "metadata_files_per_s_per_worker": rate(processed, s["seconds_metadata"]),
        "thumbnail_files_per_s_per_worker": rate(processed, s["seconds_thumbnail"]),
        "reextract_files_per_s_per_worker": rate(s["reextracted"], s["seconds_reextract"]),
        "total_files_per_s": rate(processed + s["reextracted"], s["seconds"]),
    }
