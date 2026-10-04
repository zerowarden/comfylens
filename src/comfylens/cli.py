import contextlib
import ipaddress
import json
import os
import sys
import tempfile
import threading
import time
import webbrowser
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Column, Table

from comfylens.collection.archive import InvalidArchive, export_zip, import_zip
from comfylens.collection.store import CollectionStore, CollectionUnavailable
from comfylens.config import Config, ConfigError, load_config
from comfylens.db.connection import CatalogMissing, connect_readonly
from comfylens.extract.keys import CHAIN_SEPARATOR
from comfylens.extract.normalize import aspect, megapixels
from comfylens.extract.pipeline import Analysis, analyze
from comfylens.extract.registry import unregistered
from comfylens.extract.types import Extraction
from comfylens.index.indexer import Indexer, IndexStatus, UnsafeLocation
from comfylens.index.lock import IndexLocked
from comfylens.paths import catalog_path, collection_dir
from comfylens.report import build_report, render_report
from comfylens.version import EXTRACTOR_VERSION, SCHEMA_VERSION

app = typer.Typer(no_args_is_help=True, add_completion=False)
collection_app = typer.Typer(
    no_args_is_help=True, help="Back up and restore the saved-prompt collection."
)
app.add_typer(collection_app, name="collection")


@app.callback()
def main() -> None:
    """Index ComfyUI output images and report the generation settings they used."""


Library = Annotated[
    Path, typer.Argument(exists=True, file_okay=False, readable=True, help="Library directory.")
]
JsonFlag = Annotated[bool, typer.Option("--json", help="Print JSON instead of tables.")]


def _config() -> Config:
    try:
        return load_config()
    except ConfigError as e:
        typer.echo(f"config error: {e}", err=True)
        raise typer.Exit(2) from e


@app.command("index")
def index_library(
    library: Library,
    workers: Annotated[
        int | None, typer.Option(min=1, help="Worker processes (default: CPU count - 2).")
    ] = None,
    reextract: Annotated[
        bool, typer.Option("--reextract", help="Re-extract every file from stored raw JSON.")
    ] = False,
    full: Annotated[
        bool, typer.Option("--full", help="Ignore size and mtime; re-read every file.")
    ] = False,
) -> None:
    """Incrementally index a library. Never writes inside it."""
    config = _config()
    console = Console()
    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("{task.fields[errors]} errors"),
        TimeRemainingColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Scanning", total=None, errors=0)

        def show(status: IndexStatus) -> None:
            total = status.total if status.state == "processing" else None
            progress.update(
                task,
                description=status.state.capitalize(),
                total=total,
                completed=status.done,
                errors=status.errors,
            )

        indexer = Indexer(library, config, workers=workers, on_status=show)
        try:
            result = indexer.run(full=full, reextract_all=reextract)
        except (IndexLocked, UnsafeLocation) as e:
            progress.stop()
            typer.echo(str(e), err=True)
            raise typer.Exit(1) from e

    processed = result.new + result.changed
    console.print(
        f"Indexed {result.scanned} files in {result.seconds:.1f} s with {result.workers} workers:"
        f" {result.new} new, {result.changed} changed, {result.deleted} deleted,"
        f" {result.unchanged} unchanged, {result.reextracted} re-extracted, {result.errors} errors."
    )
    if (processed or result.reextracted) and result.seconds:
        console.print(f"{(processed + result.reextracted) / result.seconds:.0f} files/s")
    if result.skipped_names:
        console.print(f"[yellow]Skipped {result.skipped_names} files whose names are not UTF-8.[/]")
    if result.thumbnails_failed:
        console.print(
            f"[yellow]Could not restore {result.thumbnails_failed} missing thumbnails;"
            " the next run tries again.[/]"
        )
    if result.clusters:
        files = sum(len(c.file_ids) for c in result.clusters)
        console.print(
            f"[yellow]{files} files in {len(result.clusters)} suspect timestamp clusters;"
            " see comfylens report.[/]"
        )


@app.command("report")
def report_library(
    library: Library,
    as_json: JsonFlag = False,
    family: Annotated[
        str | None, typer.Option(help="Limit the per-family section to one family.")
    ] = None,
) -> None:
    """Summarize an existing index: parse rate, unhandled classes, warnings, statistics."""
    config = _config()
    try:
        conn = connect_readonly(catalog_path(library))
    except CatalogMissing as e:
        typer.echo(f"No usable index for {library}. Run: comfylens index {library}", err=True)
        raise typer.Exit(1) from e
    try:
        doc = build_report(conn, config, family=family)
    finally:
        conn.close()
    if as_json:
        json.dump(doc, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        render_report(Console(), doc)


@app.command("serve")
def serve_library(
    library: Library,
    port: Annotated[int | None, typer.Option(help="Port (default from config: 8765).")] = None,
    host: Annotated[str | None, typer.Option(help="Interface (default 127.0.0.1).")] = None,
    no_index: Annotated[
        bool, typer.Option("--no-index", help="Serve the existing catalog without indexing.")
    ] = False,
    no_open: Annotated[bool, typer.Option("--no-open", help="Do not open a browser.")] = False,
    watch: Annotated[
        bool, typer.Option("--watch", help="Index new and changed files automatically.")
    ] = False,
) -> None:
    """Serve the web UI; an incremental index runs in the background."""
    import uvicorn

    from comfylens.api.app import create_app

    config = _config()
    host = host or config.server.host
    port = port or config.server.port
    if not _is_loopback(host):
        typer.echo(
            f"Warning: serving on {host}, which is not a loopback address. comfylens has no"
            " authentication: anyone who can reach this port can view, rename and trash images.",
            err=True,
        )
    url = f"http://{'localhost' if _is_loopback(host) else host}:{port}/"

    def announce(server: uvicorn.Server) -> None:
        while not server.started and not server.should_exit:
            time.sleep(0.05)
        if not server.started:
            return  # startup failed: the process is exiting
        typer.echo(f"comfylens is serving {library.resolve()} at {url}")
        if watch:
            typer.echo("Watching for new and changed images.")
        if config.server.open_browser and not no_open:
            threading.Timer(0.5, webbrowser.open, [url]).start()

    application = create_app(library, config, index_on_start=not no_index, watch=watch)
    server = uvicorn.Server(uvicorn.Config(application, host=host, port=port, log_level="warning"))
    threading.Thread(target=announce, args=(server,), name="startup-announce", daemon=True).start()
    with contextlib.suppress(KeyboardInterrupt):
        server.run()


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@app.command("inspect")
def inspect_file(
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    as_json: JsonFlag = False,
) -> None:
    """Read one file and show what extraction finds. Touches no catalog."""
    config = _config()
    result = analyze(file.read_bytes(), config)
    if as_json:
        doc = {"path": str(file), **to_dict(result, config.graph.output_classes)}
        json.dump(doc, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        _print(Console(), file, result, config.graph.output_classes)


def to_dict(a: Analysis, output_classes: frozenset[str]) -> dict[str, Any]:
    """The `inspect --json` document; also the golden-test format."""
    doc: dict[str, Any] = {
        "versions": {"extractor": EXTRACTOR_VERSION, "schema": SCHEMA_VERSION},
        "status": a.status,
        "error": a.error,
    }
    if a.raw is not None:
        raw = a.raw
        ratio, label = aspect(raw.width, raw.height)
        doc["file"] = {
            "format": raw.format,
            "width": raw.width,
            "height": raw.height,
            "megapixels": megapixels(raw.width, raw.height),
            "aspect": ratio,
            "aspect_label": label,
        }
        doc["raw_keys"] = [
            {"key": k, "source": raw.sources[k], "kind": raw.kinds[k], "chars": len(v)}
            for k, v in raw.texts.items()
        ]
    if a.graph is not None and a.reach is not None:
        graph, reach = a.graph, a.reach
        ordered = reach.order + [n for n in graph.nodes if n not in reach.reachable]
        doc["outputs"] = reach.outputs
        doc["nodes"] = [
            {
                "id": n,
                "class_type": graph.nodes[n].class_type,
                "title": graph.nodes[n].title,
                "reachable": n in reach.reachable,
            }
            for n in ordered
        ]
        doc["unregistered"] = unregistered(
            {graph.nodes[n].class_type for n in reach.reachable}, output_classes
        )
    if a.extraction is not None:
        extraction = asdict(a.extraction)
        del extraction["warnings"]
        extraction["text_encoder"] = a.extraction.text_encoder
        doc["extraction"] = extraction
    doc["warnings"] = [asdict(w) for w in a.warnings]
    return doc


def _table(*headers: str, title: str) -> Table:
    columns = [Column(h, overflow="fold") for h in headers]
    return Table(*columns, title=title, title_justify="left")


def _print(console: Console, path: Path, a: Analysis, output_classes: frozenset[str]) -> None:
    status_style = {"ok": "green", "partial": "yellow"}.get(a.status, "red")
    console.print(f"[bold]{escape(str(path))}[/]  [{status_style}]{a.status}[/]")
    if a.error:
        console.print(f"[red]{escape(a.error)}[/]")
    raw = a.raw
    if raw is None:
        return
    ratio, label = aspect(raw.width, raw.height)
    console.print(
        f"{raw.format.upper()} {raw.width}×{raw.height}, "
        f"{megapixels(raw.width, raw.height)} MP, aspect {ratio} ({label})"
    )

    keys = _table("key", "source", "kind", "chars", title="Raw keys")
    for k, v in raw.texts.items():
        keys.add_row(escape(k), raw.sources[k], raw.kinds[k], f"{len(v):,}")
    console.print(keys if raw.texts else "[dim]no text metadata[/]")

    if a.graph is not None and a.reach is not None:
        graph, reach = a.graph, a.reach
        nodes = _table("id", "class_type", "title", "", title="Nodes")
        for n in reach.order:
            node = graph.nodes[n]
            tag = "output" if n in reach.outputs else ""
            nodes.add_row(n, escape(node.class_type), escape(node.title or ""), tag)
        for n, node in graph.nodes.items():
            if n not in reach.reachable:
                nodes.add_row(
                    n,
                    escape(node.class_type),
                    escape(node.title or ""),
                    "unreachable",
                    style="dim",
                )
        console.print(nodes)
        missing = unregistered({graph.nodes[n].class_type for n in reach.reachable}, output_classes)
        if missing:
            console.print(f"Unregistered reachable classes: {escape(', '.join(missing))}")

    if a.extraction is not None:
        _print_extraction(console, a.extraction)

    if a.warnings:
        table = _table("code", "node", "message", title="Warnings")
        for w in a.warnings:
            table.add_row(w.code, w.node_id or "", escape(w.message))
        console.print(table)


def _print_extraction(console: Console, e: Extraction) -> None:
    stages = _table(
        "#",
        "node",
        "class",
        "seed",
        "steps",
        "cfg",
        "sampler",
        "scheduler",
        "denoise",
        "start",
        "end",
        title="Sampler stages",
    )
    for s in e.stages:
        stages.add_row(
            *(
                "" if v is None else escape(str(v))
                for v in (
                    s.index,
                    s.node_id,
                    s.class_type,
                    s.seed,
                    s.steps,
                    s.cfg,
                    s.sampler_name,
                    s.scheduler,
                    s.denoise,
                    s.start_step,
                    s.end_step,
                )
            )
        )
    console.print(stages if e.stages else "[dim]no sampler stages[/]")

    if len(e.stages) > 1:
        models = _table(
            "#", "family", "base model", "text encoder", "LoRAs", "guidance", "shift", "latent",
            title="Stage models",
        )  # fmt: skip
        for s in e.stages:
            models.add_row(
                *(
                    "" if v is None else escape(str(v))
                    for v in (
                        s.index,
                        s.model_family,
                        s.base_model,
                        s.text_encoder,
                        s.lora_stack_key,
                        s.guidance,
                        s.shift,
                        s.latent_source,
                    )
                )
            )
        console.print(models)

    if not e.stages:
        console.print(f"[bold]Model chain:[/] {escape(e.base_model or '?')}")
    for s in e.stages:
        applied = sorted(
            (u for u in e.loras if u.stage_index == s.index and u.enabled),
            key=lambda u: u.position or 0,
        )
        chain = [
            s.base_model or "?",
            *(f"{u.name} ({u.strength_model})" for u in applied),
            f"{s.class_type} #{s.node_id}",
        ]
        label = "Model chain" if len(e.stages) == 1 else f"Model chain, stage {s.index}"
        console.print(f"[bold]{label}:[/] {escape(CHAIN_SEPARATOR.join(chain))}")

    if e.loras:
        loras = _table(
            "stage", "pos", "node", "entry", "name", "base", "step", "model", "clip", "",
            title="LoRAs",
        )  # fmt: skip
        for u in e.loras:
            state = "" if u.reachable else "unused"
            state = state if u.enabled else "off"
            loras.add_row(
                "" if u.stage_index is None else str(u.stage_index),
                "" if u.position is None else str(u.position),
                u.node_id,
                u.entry,
                escape(u.name),
                escape(u.base_name),
                "" if u.step is None else str(u.step),
                str(u.strength_model),
                "" if u.strength_clip is None else str(u.strength_clip),
                state,
                style=None if u.reachable and u.enabled else "dim",
            )
        console.print(loras)

    settings = Table(show_header=False, title="Settings", title_justify="left")
    rows: list[tuple[str, Any]] = [
        ("model_family", e.model_family),
        ("base_model", e.base_model),
        ("text_encoder", e.text_encoder),
        ("clip_type", e.clip_type),
        ("vae", e.vae),
        ("guidance", e.guidance),
        ("shift", e.shift),
        ("latent_source", e.latent_source),
        ("batch_size", e.batch_size),
        ("lora_stack_key", e.lora_stack_key),
        ("config_key", e.config_key),
        ("generation_key", e.generation_key),
    ]
    for name, value in rows:
        settings.add_row(name, "" if value is None else escape(str(value)))
    console.print(settings)

    for side, text in (("Positive", e.positive_prompt), ("Negative", e.negative_prompt)):
        console.print(f"[bold]{side} prompt:[/]")
        console.print(escape(text) if text is not None else "[dim](none)[/]", highlight=False)
    for s in e.stages[1:]:
        for side, text, primary in (
            ("positive", s.positive_prompt, e.positive_prompt),
            ("negative", s.negative_prompt, e.negative_prompt),
        ):
            if text != primary:
                console.print(f"[bold]Stage {s.index} {side} prompt:[/]")
                console.print(
                    escape(text) if text is not None else "[dim](none)[/]", highlight=False
                )

    for image in e.input_images:
        console.print(
            f"Input image: node {image.node_id} {escape(image.filename or '?')} "
            f"sha256 {image.sha256 or '?'}"
        )
    reachable = sum(1 for g in e.generic_inputs if g.reachable)
    console.print(f"Generic inputs: {len(e.generic_inputs)} ({reachable} reachable)")


def _collection() -> CollectionStore:
    try:
        return CollectionStore(collection_dir())
    except CollectionUnavailable as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e


@collection_app.command("export")
def export_collection(
    target: Annotated[
        Path | None,
        typer.Argument(
            help="Zip file to write, or a directory for a dated file in it"
            " (default: the current directory)."
        ),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Replace an existing file.")] = False,
) -> None:
    """Write every saved prompt and its images to one zip, the same as Export in the UI."""
    path = target or Path.cwd()
    if path.is_dir():
        path = path / f"comfylens-collection-{date.today().isoformat()}.zip"
    if path.exists() and not force:
        typer.echo(f"error: {path} exists; pass --force to replace it", err=True)
        raise typer.Exit(1)
    if not path.parent.is_dir():
        typer.echo(f"error: {path.parent} is not a directory", err=True)
        raise typer.Exit(1)
    store = _collection()
    # Written beside the target and renamed into place: a backup is never left half-written.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".comfylens-export-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as out:
            prompts, images = export_zip(store, out)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    typer.echo(f"Exported {_count(prompts, 'prompt')} and {_count(images, 'image')} to {path}")


@collection_app.command("import")
def import_collection(
    archive: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, readable=True, help="An exported zip.")
    ],
) -> None:
    """Add the prompts of an exported zip; prompts already in the collection are skipped."""
    store = _collection()
    try:
        with archive.open("rb") as f:
            stats = import_zip(store, f)
    except InvalidArchive as e:
        typer.echo(f"error: {archive}: {e}", err=True)
        raise typer.Exit(1) from e
    already = f" ({stats.skipped} already here)" if stats.skipped else ""
    typer.echo(f"Imported {_count(stats.added, 'prompt')}{already} from {archive}")


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"
