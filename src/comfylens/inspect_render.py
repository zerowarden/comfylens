"""`inspect` rendered with Rich: the file's raw keys, graph, extraction and warnings."""

import itertools
from collections.abc import Iterable, Sequence
from pathlib import Path

from rich.console import Console, RenderableType
from rich.markup import escape
from rich.table import Column, Table
from rich.text import Text

from comfylens.extract import (
    CHAIN_SEPARATOR,
    Analysis,
    Extraction,
    LoraUse,
    SamplerStage,
    size_facts,
    unregistered,
)
from comfylens.graph import Graph, Reachability
from comfylens.metadata import RawMetadata
from comfylens.warn import Warn


def render_analysis(
    console: Console, path: Path, a: Analysis, output_classes: frozenset[str]
) -> None:
    status_style = {"ok": "green", "partial": "yellow"}.get(a.status, "red")
    console.print(f"[bold]{escape(str(path))}[/]  [{status_style}]{a.status}[/]")
    if a.error:
        console.print(f"[red]{escape(a.error)}[/]")
    if a.raw is None:
        return
    sections = [
        *_raw_sections(a.raw),
        *(_graph_sections(a.graph, a.reach, output_classes) if a.graph and a.reach else []),
        *(_extraction_sections(a.extraction) if a.extraction else []),
        *([_warnings_table(a.warnings)] if a.warnings else []),
    ]
    for section in sections:
        console.print(section)


def _table(*headers: str, title: str) -> Table:
    columns = [Column(h, overflow="fold") for h in headers]
    return Table(*columns, title=title, title_justify="left")


def _cell(value: object) -> str:
    return "" if value is None else escape(str(value))


def _filled(table: Table, rows: Iterable[Sequence[object]], dim: Iterable[bool] = ()) -> Table:
    """`table` with `rows` added, each cell escaped; a true `dim` entry dims its row."""
    for row, faint in itertools.zip_longest(rows, dim, fillvalue=False):
        table.add_row(*map(_cell, row), style="dim" if faint else None)  # type: ignore[arg-type]
    return table


def _raw_sections(raw: RawMetadata) -> list[RenderableType]:
    size = size_facts(raw.width, raw.height)
    keys = _filled(
        _table("key", "source", "kind", "chars", title="Raw keys"),
        ((k, raw.sources[k], raw.kinds[k], f"{len(v):,}") for k, v in raw.texts.items()),
    )
    return [
        f"{raw.format.upper()} {raw.width}×{raw.height}, "
        f"{size['megapixels']} MP, aspect {size['aspect']} ({size['aspect_label']})",
        keys if raw.texts else "[dim]no text metadata[/]",
    ]


def _graph_sections(
    graph: Graph, reach: Reachability, output_classes: frozenset[str]
) -> list[RenderableType]:
    """Reachable nodes in order, outputs marked, then the unreachable ones dimmed."""
    unreachable = [n for n in graph.nodes if n not in reach.reachable]
    rows = [
        *((n, "output" if n in reach.outputs else "") for n in reach.order),
        *((n, "unreachable") for n in unreachable),
    ]
    nodes = _filled(
        _table("id", "class_type", "title", "", title="Nodes"),
        ((n, graph.nodes[n].class_type, graph.nodes[n].title or "", tag) for n, tag in rows),
        dim=(tag == "unreachable" for _, tag in rows),
    )
    missing = unregistered({graph.nodes[n].class_type for n in reach.reachable}, output_classes)
    note = [f"Unregistered reachable classes: {escape(', '.join(missing))}"] if missing else []
    return [nodes, *note]


def _warnings_table(warnings: list[Warn]) -> Table:
    return _filled(
        _table("code", "node", "message", title="Warnings"),
        ((w.code, w.node_id or "", w.message) for w in warnings),
    )


def _extraction_sections(e: Extraction) -> list[RenderableType]:
    return [
        _stages_table(e) if e.stages else "[dim]no sampler stages[/]",
        *([_stage_models_table(e)] if len(e.stages) > 1 else []),
        *_model_chains(e),
        *([_loras_table(e)] if e.loras else []),
        _settings_table(e),
        *_prompts(e),
        *(
            f"Input image: node {image.node_id} {escape(image.filename or '?')} "
            f"sha256 {image.sha256 or '?'}"
            for image in e.input_images
        ),
    ]


def _stages_table(e: Extraction) -> Table:
    table = _table(
        "#", "node", "class", "seed", "steps", "cfg", "sampler", "scheduler", "denoise", "start",
        "end", title="Sampler stages",
    )  # fmt: skip
    return _filled(
        table,
        (
            (s.index, s.node_id, s.class_type, s.seed, s.steps, s.cfg, s.sampler_name,
             s.scheduler, s.denoise, s.start_step, s.end_step)
            for s in e.stages
        ),
    )  # fmt: skip


def _stage_models_table(e: Extraction) -> Table:
    table = _table(
        "#", "family", "base model", "text encoder", "LoRAs", "guidance", "shift", "latent",
        title="Stage models",
    )  # fmt: skip
    return _filled(
        table,
        (
            (s.index, s.model_family, s.base_model, s.text_encoder, s.lora_stack_key,
             s.guidance, s.shift, s.latent_source)
            for s in e.stages
        ),
    )  # fmt: skip


def _model_chains(e: Extraction) -> list[str]:
    """Each stage's model, its enabled LoRAs in order, and its sampler."""
    if not e.stages:
        return [f"[bold]Model chain:[/] {escape(e.base_model or '?')}"]

    def chain(s: SamplerStage) -> str:
        applied = sorted(
            (u for u in e.loras if u.stage_index == s.index and u.enabled),
            key=lambda u: u.position or 0,
        )
        links = [
            s.base_model or "?",
            *(f"{u.name} ({u.strength_model})" for u in applied),
            f"{s.class_type} #{s.node_id}",
        ]
        label = "Model chain" if len(e.stages) == 1 else f"Model chain, stage {s.index}"
        return f"[bold]{label}:[/] {escape(CHAIN_SEPARATOR.join(links))}"

    return [chain(s) for s in e.stages]


def _loras_table(e: Extraction) -> Table:
    table = _table(
        "stage", "pos", "node", "entry", "name", "base", "step", "model", "clip", "",
        title="LoRAs",
    )  # fmt: skip
    rows = (
        (u.stage_index, u.position, u.node_id, u.entry, u.name, u.base_name, u.step,
         u.strength_model, u.strength_clip, _lora_state(u))
        for u in e.loras
    )  # fmt: skip
    return _filled(table, rows, dim=(_lora_state(u) != "" for u in e.loras))


def _lora_state(u: LoraUse) -> str:
    return "off" if not u.enabled else "unused" if not u.reachable else ""


_SETTINGS = (
    "model_family", "base_model", "text_encoder", "clip_type", "vae", "guidance", "shift",
    "latent_source", "batch_size", "lora_stack_key", "config_key", "generation_key",
)  # fmt: skip


def _settings_table(e: Extraction) -> Table:
    table = Table(show_header=False, title="Settings", title_justify="left")
    return _filled(table, ((name, getattr(e, name)) for name in _SETTINGS))


def _prompts(e: Extraction) -> list[RenderableType]:
    """The primary prompts, then each later stage's where they differ; as Text, which is never
    highlighted."""
    later = [
        (f"Stage {s.index} {side}", text)
        for s in e.stages[1:]
        for side, text, primary in (
            ("positive", s.positive_prompt, e.positive_prompt),
            ("negative", s.negative_prompt, e.negative_prompt),
        )
        if text != primary
    ]
    prompts = [("Positive", e.positive_prompt), ("Negative", e.negative_prompt), *later]
    return [
        line
        for label, text in prompts
        for line in (
            f"[bold]{label} prompt:[/]",
            Text("(none)", "dim") if text is None else Text(text),
        )
    ]
