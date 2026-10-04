"""`comfylens report`: what the index found, and what extraction still misses."""

import json
import sqlite3
from datetime import datetime
from typing import Any

import polars as pl
from rich.console import Console
from rich.markup import escape
from rich.table import Column, Table

from comfylens import version
from comfylens.analytics.scope import NO_LOOKUP, Scope, resolve
from comfylens.analytics.snapshot import Snapshot, snapshot_from_conn
from comfylens.analytics.stats import compute_stats
from comfylens.config import Config
from comfylens.extract.family import UNKNOWN
from comfylens.extract.registry import unregistered
from comfylens.warn import INFORMATIONAL_CODES

TOP_LORAS = 10
TOP_CONFIGS = 5
TOP_UNUSED_LORAS = 20
TOP_UNKNOWN_MODELS = 10


def build_report(
    conn: sqlite3.Connection, config: Config, *, family: str | None = None
) -> dict[str, Any]:
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    snap = snapshot_from_conn(conn, with_node_inputs=False)
    gens = snap.images.filter("has_generation")
    return {
        "library": {
            "root": meta.get("library_root"),
            "last_index_at": _int(meta.get("last_index_at")),
            "stale": meta.get("extractor_version") != str(version.EXTRACTOR_VERSION)
            or meta.get("config_hash") != config.config_hash,
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


# Rendering.


def _n(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{round(x, 4):.6g}"


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:.1%}"


def _time(ts: float | None) -> str:
    return "—" if ts is None else datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _mode(stats: dict[str, Any]) -> str:
    if not stats["mode"]:
        return f"— ({stats['mode_note']})" if stats["mode_note"] else "—"
    values = ", ".join(_n(v) for v in stats["mode"])
    return f"{values} ({_pct(stats['mode_share'])}){' tied' if stats['mode_tied'] else ''}"


def _range(stats: dict[str, Any]) -> str:
    return "—" if stats["min"] is None else f"{_n(stats['min'])}–{_n(stats['max'])}"


def _table(*headers: str, title: str | None = None) -> Table:
    columns = [Column(h, overflow="fold") for h in headers]
    return Table(*columns, title=title, title_justify="left", title_style="bold")


def _config_text(fields: dict[str, Any]) -> str:
    parts = [
        fields["base_model"] or "?",
        fields["lora_stack_key"],
        f"{fields['sampler_name'] or '?'}/{fields['scheduler'] or '?'}",
        f"{_n(fields['steps'])} steps",
        f"cfg {_n(fields['cfg'])}",
        f"denoise {_n(fields['denoise'])}",
    ]
    for name in ("guidance", "shift"):
        if fields[name] is not None:
            parts.append(f"{name} {_n(fields[name])}")
    return " | ".join(parts)


def render_report(console: Console, r: dict[str, Any]) -> None:
    lib = r["library"]
    console.print(
        f"[bold]{escape(str(lib['root']))}[/]  last indexed {_time(lib['last_index_at'])}"
    )
    if lib["stale"]:
        console.print(
            "[yellow]The index predates the current extractor or config; re-run index.[/]"
        )

    f = r["files"]
    console.rule("1. Files")
    table = _table("status", "format", "files")
    for row in f["by_status_format"]:
        table.add_row(row["status"], row["format"], str(row["files"]))
    console.print(table)
    console.print(f"Parse success: {f['ok']} of {f['total']} ({_pct(f['parse_success_rate'])})")

    console.rule("2. Families")
    table = _table("family", "files")
    for row in r["families"]["counts"]:
        table.add_row(escape(row["family"]), str(row["files"]))
    console.print(table)
    if r["families"]["unknown_base_models"]:
        table = _table("base_model", "files", title="Base models of family unknown")
        for row in r["families"]["unknown_base_models"]:
            table.add_row(escape(str(row["base_model"])), str(row["files"]))
        console.print(table)

    console.rule("3. Reachable classes with no handler")
    if r["unregistered"]:
        table = _table("class_type", "files")
        for row in r["unregistered"]:
            table.add_row(escape(row["class_type"]), str(row["files"]))
        console.print(table)
    else:
        console.print("None.")

    console.rule("4. Warnings")
    table = _table("code", "count", "files", "")
    for row in r["warnings"]["codes"]:
        note = "informational: no badge" if row["informational"] else ""
        table.add_row(row["code"], str(row["count"]), str(row["files"]), note)
    console.print(table if r["warnings"]["codes"] else "None.")
    if r["warnings"]["unused_loras"]:
        table = _table("LoRA", "files", title="Most frequent unused LoRAs")
        for row in r["warnings"]["unused_loras"]:
            table.add_row(escape(row["name"]), str(row["files"]))
        console.print(table)

    console.rule("5. Suspect timestamp clusters")
    if r["timestamp_clusters"]:
        table = _table("start", "end", "files", "distinct generations")
        for c in r["timestamp_clusters"]:
            table.add_row(
                _time(c["start"]), _time(c["end"]), str(c["files"]), str(c["distinct_generations"])
            )
        console.print(table)
    else:
        console.print("None.")

    console.rule("6. Per family")
    for fam in r["per_family"]:
        console.print(f"[bold]{escape(fam['family'])}[/] ({fam['images']} unique images)")
        table = _table("field", "mode (share)", "median", "mean", "min–max", "n")
        for name, stats in fam["numeric"].items():
            if stats["n"]:
                table.add_row(
                    name,
                    _mode(stats),
                    _n(stats["median"]),
                    _n(stats["mean"]),
                    _range(stats),
                    str(stats["n"]),
                )
        console.print(table)
        if fam["loras"]:
            table = _table("LoRA", "images", "share", "strength mode", "median", "mean", "range")
            for row in fam["loras"]:
                st = row["strength_model"]
                table.add_row(
                    escape(row["name"]),
                    str(row["images"]),
                    _pct(row["share"]),
                    _mode(st),
                    _n(st["median"]),
                    _n(st["mean"]),
                    _range(st),
                )
            console.print(table)
        table = _table("#", "count", "share", "configuration")
        for rank, row in enumerate(fam["configs"], 1):
            table.add_row(
                str(rank),
                str(row["count"]),
                _pct(row["share"]),
                escape(_config_text(row["fields"])),
            )
        console.print(table)

    console.rule("7. Timing (last index run that read files)")
    t = r["timing"]
    if t is None:
        console.print("No index run recorded.")
        return
    console.print(
        f"{t['processed']} files read, {t['reextracted']} re-extracted in {t['seconds']:.1f} s"
        f" with {t['workers']} workers: {_n(t['total_files_per_s'])} files/s in total"
    )
    console.print(
        f"Per worker: metadata {_n(t['metadata_files_per_s_per_worker'])} files/s,"
        f" thumbnails {_n(t['thumbnail_files_per_s_per_worker'])} files/s,"
        f" re-extraction {_n(t['reextract_files_per_s_per_worker'])} files/s"
    )
