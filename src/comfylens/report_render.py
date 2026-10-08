"""`comfylens report` presentation: the Rich tables over report_data.build_report."""

from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from typing import Any

from rich.console import Console, RenderableType
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


def _table(*headers: str, rows: Iterable[Sequence[object]], title: str | None = None) -> Table:
    """A table of `rows`, every cell escaped."""
    columns = [Column(h, overflow="fold") for h in headers]
    table = Table(*columns, title=title, title_justify="left", title_style="bold")
    for row in rows:
        table.add_row(*(escape(str(cell)) for cell in row))
    return table


def _config_text(fields: dict[str, Any]) -> str:
    parts = [
        fields["base_model"] or "?",
        fields["lora_stack_key"],
        f"{fields['sampler_name'] or '?'}/{fields['scheduler'] or '?'}",
        f"{_n(fields['steps'])} steps",
        f"cfg {_n(fields['cfg'])}",
        f"denoise {_n(fields['denoise'])}",
        *(
            f"{name} {_n(fields[name])}"
            for name in ("guidance", "shift")
            if fields[name] is not None
        ),
    ]
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
    for title, section in _SECTIONS:
        console.rule(title)
        for renderable in section(r):
            console.print(renderable)


type _Section = list[RenderableType]


def _files(r: dict[str, Any]) -> _Section:
    f = r["files"]
    rows = ((row["status"], row["format"], row["files"]) for row in f["by_status_format"])
    return [
        _table("status", "format", "files", rows=rows),
        f"Parse success: {f['ok']} of {f['total']} ({_pct(f['parse_success_rate'])})",
    ]


def _families(r: dict[str, Any]) -> _Section:
    counts, unknown = r["families"]["counts"], r["families"]["unknown_base_models"]
    title = "Base models of family unknown"
    return [
        _table("family", "files", rows=((row["family"], row["files"]) for row in counts)),
        *(
            [
                _table(
                    "base_model",
                    "files",
                    rows=((u["base_model"], u["files"]) for u in unknown),
                    title=title,
                )
            ]
            if unknown
            else []
        ),
    ]


def _unregistered(r: dict[str, Any]) -> _Section:
    rows = [(row["class_type"], row["files"]) for row in r["unregistered"]]
    return [_table("class_type", "files", rows=rows) if rows else "None."]


def _warnings(r: dict[str, Any]) -> _Section:
    codes, unused = r["warnings"]["codes"], r["warnings"]["unused_loras"]
    rows = [
        (c["code"], c["count"], c["files"], "informational" if c["informational"] else "")
        for c in codes
    ]
    title = "Most frequent unused LoRAs"
    return [
        _table("code", "count", "files", "", rows=rows) if rows else "None.",
        *(
            [_table("LoRA", "files", rows=((u["name"], u["files"]) for u in unused), title=title)]
            if unused
            else []
        ),
    ]


def _timestamp_clusters(r: dict[str, Any]) -> _Section:
    rows = [
        (_time(c["start"]), _time(c["end"]), c["files"], c["distinct_generations"])
        for c in r["timestamp_clusters"]
    ]
    return [_table("start", "end", "files", "distinct generations", rows=rows) if rows else "None."]


def _per_family(r: dict[str, Any]) -> _Section:
    return [renderable for fam in r["per_family"] for renderable in _family(fam)]


def _family(fam: dict[str, Any]) -> _Section:
    numeric = [
        (name, *_summary(stats), stats["n"]) for name, stats in fam["numeric"].items() if stats["n"]
    ]
    loras = [
        (row["name"], row["images"], _pct(row["share"]), *_summary(row["strength_model"]))
        for row in fam["loras"]
    ]
    configs = [
        (rank, row["count"], _pct(row["share"]), _config_text(row["fields"]))
        for rank, row in enumerate(fam["configs"], 1)
    ]
    return [
        f"[bold]{escape(fam['family'])}[/] ({fam['images']} unique images)",
        _table("field", "mode (share)", "median", "mean", "min–max", "n", rows=numeric),
        *(
            [
                _table(
                    "LoRA",
                    "images",
                    "share",
                    "strength mode",
                    "median",
                    "mean",
                    "range",
                    rows=loras,
                )
            ]
            if loras
            else []
        ),
        _table("#", "count", "share", "configuration", rows=configs),
    ]


def _summary(stats: dict[str, Any]) -> tuple[str, str, str, str]:
    """Mode (share), median, mean and range of numeric statistics."""
    return _mode(stats), _n(stats["median"]), _n(stats["mean"]), _range(stats)


def _timing(r: dict[str, Any]) -> _Section:
    t = r["timing"]
    if t is None:
        return ["No index run recorded."]
    return [
        f"{t['processed']} files read, {t['reextracted']} re-extracted in {t['seconds']:.1f} s"
        f" with {t['workers']} workers: {_n(t['total_files_per_s'])} files/s in total",
        f"Per worker: metadata {_n(t['metadata_files_per_s_per_worker'])} files/s,"
        f" thumbnails {_n(t['thumbnail_files_per_s_per_worker'])} files/s,"
        f" re-extraction {_n(t['reextract_files_per_s_per_worker'])} files/s",
    ]


_SECTIONS: tuple[tuple[str, Callable[[dict[str, Any]], _Section]], ...] = (
    ("1. Files", _files),
    ("2. Families", _families),
    ("3. Reachable classes with no handler", _unregistered),
    ("4. Warnings", _warnings),
    ("5. Suspect timestamp clusters", _timestamp_clusters),
    ("6. Per family", _per_family),
    ("7. Timing (last index run that read files)", _timing),
)
