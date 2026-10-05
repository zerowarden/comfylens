"""`comfylens report` presentation: the Rich tables over report_data.build_report."""

from datetime import datetime
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Column, Table


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
