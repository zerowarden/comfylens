import contextlib
import errno
import ipaddress
import json
import socket
import sys
import threading
import time
import webbrowser
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeRemainingColumn

from comfylens.collection import (
    CollectionStore,
    CollectionUnavailable,
    InvalidArchive,
    export_filename,
    export_zip,
    import_zip,
)
from comfylens.config import Config, ConfigError, load_config
from comfylens.db import CatalogMissing, connect_readonly
from comfylens.extract import analyze
from comfylens.fileio import write_atomic
from comfylens.index import Indexer, IndexLocked, IndexStatus, UnsafeLocation
from comfylens.inspect_data import to_dict
from comfylens.inspect_render import render_analysis
from comfylens.paths import catalog_path, collection_dir
from comfylens.rc import RcError, scan_directory
from comfylens.report_data import build_report
from comfylens.report_render import render_report

app = typer.Typer(no_args_is_help=True, add_completion=False)
collection_app = typer.Typer(
    no_args_is_help=True, help="Back up and restore the saved-prompt collection."
)
app.add_typer(collection_app, name="collection")


@app.callback()
def main() -> None:
    """Index ComfyUI output images and report the generation settings they used."""


Library = Annotated[
    Path | None,
    typer.Argument(
        exists=True,
        file_okay=False,
        readable=True,
        help="Library directory (default: scan.directory from ~/.comfylensrc).",
    ),
]
JsonFlag = Annotated[bool, typer.Option("--json", help="Print JSON instead of tables.")]

# serve tries this many ports from the configured one before taking any free port.
_PORT_TRIES = 20


def _config() -> Config:
    try:
        return load_config()
    except ConfigError as e:
        typer.echo(f"config error: {e}", err=True)
        raise typer.Exit(2) from e


def _library(library: Path | None) -> Path:
    """The library to use: the argument when given, else the .comfylensrc scan directory."""
    if library is not None:
        return library
    try:
        return scan_directory()
    except RcError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from e


@app.command("index")
def index_library(
    library: Library = None,
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
    root = _library(library)
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

        indexer = Indexer(root, config, workers=workers, on_status=show)
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
    library: Library = None,
    as_json: JsonFlag = False,
    family: Annotated[
        str | None, typer.Option(help="Limit the per-family section to one family.")
    ] = None,
) -> None:
    """Summarize an existing index: parse rate, unhandled classes, warnings, statistics."""
    config = _config()
    root = _library(library)
    try:
        conn = connect_readonly(catalog_path(root))
    except CatalogMissing as e:
        typer.echo(f"No usable index for {root}. Run: comfylens index {root}", err=True)
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
    library: Library = None,
    port: Annotated[
        int | None,
        typer.Option(help="Port (default from config: 8765); the next free one if taken."),
    ] = None,
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

    from comfylens.api import create_app

    config = _config()
    root = _library(library)
    host = host or config.server.host
    port = port or config.server.port
    if not _is_loopback(host):
        typer.echo(
            f"Warning: serving on {host}, which is not a loopback address. comfylens has no"
            " authentication: anyone who can reach this port can view, rename and trash images.",
            err=True,
        )
    sock = _listen(host, port)
    bound = sock.getsockname()[1]
    if bound != port:
        typer.echo(f"Port {port} is in use; serving on {bound} instead.", err=True)
    url = f"http://{'localhost' if _is_loopback(host) else host}:{bound}/"

    def announce(server: uvicorn.Server) -> None:
        while not server.started and not server.should_exit:
            time.sleep(0.05)
        if not server.started:
            return  # startup failed: the process is exiting
        typer.echo(f"comfylens is serving {root.resolve()} at {url}")
        if watch:
            typer.echo("Watching for new and changed images.")
        if config.server.open_browser and not no_open:
            threading.Timer(0.5, webbrowser.open, [url]).start()

    application = create_app(root, config, index_on_start=not no_index, watch=watch)
    server = uvicorn.Server(uvicorn.Config(application, host=host, port=bound, log_level="warning"))
    threading.Thread(target=announce, args=(server,), name="startup-announce", daemon=True).start()
    with contextlib.suppress(KeyboardInterrupt):
        server.run(sockets=[sock])


@app.command("free-port", hidden=True)
def free_port(
    port: Annotated[int | None, typer.Option()] = None,
    host: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Print the port serve would take; make dev hands it to Vite's proxy."""
    config = _config()
    with _listen(host or config.server.host, port or config.server.port) as sock:
        typer.echo(sock.getsockname()[1])


def _listen(host: str, port: int) -> socket.socket:
    """A socket bound to `port`, or to the next free port when it is taken."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        for candidate in range(port, min(port + _PORT_TRIES, 65536)):
            try:
                return _bind(family, host, candidate)
            except OSError as e:
                if e.errno != errno.EADDRINUSE:
                    raise
        return _bind(family, host, 0)
    except OSError as e:
        typer.echo(f"cannot listen on {host}:{port}: {e.strerror or e}", err=True)
        raise typer.Exit(1) from e


def _bind(family: socket.AddressFamily, host: str, port: int) -> socket.socket:
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
    except OSError:
        sock.close()
        raise
    return sock


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
        render_analysis(Console(), file, result, config.graph.output_classes)


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
        path = path / export_filename(date.today())
    if path.exists() and not force:
        typer.echo(f"error: {path} exists; pass --force to replace it", err=True)
        raise typer.Exit(1)
    if not path.parent.is_dir():
        typer.echo(f"error: {path.parent} is not a directory", err=True)
        raise typer.Exit(1)
    store = _collection()
    # Written beside the target and renamed into place: a backup is never left half-written.
    prompts, images = write_atomic(
        path, lambda out: export_zip(store, out), prefix=".comfylens-export-"
    )
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
