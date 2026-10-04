"""Per-file work for the process pool. Pure: picklable input and output.

Each function also runs in-process when the indexer uses a single worker.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Literal

import xxhash

from comfylens.config import Config
from comfylens.extract.pipeline import Outcome, describe, extract_outcome
from comfylens.extract.types import Extraction
from comfylens.index.thumbs import make_thumbnail
from comfylens.metadata import read_metadata
from comfylens.metadata.types import Format, Status
from comfylens.paths import thumb_path
from comfylens.warn import Code, Warn


@dataclass(frozen=True, slots=True)
class Settings:
    """What every worker needs; sent once per process by the pool initializer."""

    root: Path
    thumbs: Path
    config: Config


@dataclass(frozen=True, slots=True)
class Job:
    rel_path: str
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class ThumbJob:
    """An unchanged file whose thumbnail is missing from the cache."""

    rel_path: str
    content_hash: str


# What restore_thumbnail did: "exists" when an identical file's thumbnail got there first.
ThumbOutcome = Literal["written", "exists", "failed"]


@dataclass(slots=True)
class Extracted:
    """The extraction-derived part of a file, shared by full processing and re-extraction."""

    status: Status
    error: str | None = None
    extraction: Extraction | None = None
    nodes: list[tuple[str, str, bool]] = field(default_factory=list)  # id, class, reachable
    warnings: list[Warn] = field(default_factory=list)  # extraction stage only


@dataclass(slots=True)
class ParsedFile:
    job: Job
    content_hash: str  # "" when the file could not be read
    format: Format
    width: int | None
    height: int | None
    extracted: Extracted
    texts: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    prompt_key: str | None = None
    workflow_key: str | None = None
    read_warnings: list[Warn] = field(default_factory=list)  # reading and thumbnail stages
    seconds_metadata: float = 0.0
    seconds_thumbnail: float = 0.0
    thumbnail_written: bool = False


@dataclass(slots=True)
class Reextracted:
    file_id: int
    extracted: Extracted
    seconds: float


def process_file(job: Job, settings: Settings) -> ParsedFile:
    """Read the whole file once: hash, metadata, extraction, then the thumbnail."""
    start = perf_counter()
    fallback: Format = "png" if job.rel_path.lower().endswith(".png") else "jpeg"
    try:
        data = (settings.root / job.rel_path).read_bytes()
    except OSError as e:
        return ParsedFile(job, "", fallback, None, None, Extracted("error", describe(e)))
    content_hash = xxhash.xxh3_128_hexdigest(data)

    try:
        raw = read_metadata(data)
    except Exception as e:
        parsed = ParsedFile(
            job, content_hash, fallback, None, None, Extracted("error", describe(e))
        )
    else:
        if raw.api_prompt is None:
            extracted = Extracted(raw.status)
        else:
            extracted = _extracted(extract_outcome(raw.api_prompt, settings.config))
        parsed = ParsedFile(
            job,
            content_hash,
            raw.format,
            raw.width,
            raw.height,
            extracted,
            texts=raw.texts,
            sources=raw.sources,
            prompt_key=raw.api_prompt_key,
            workflow_key=raw.workflow_key,
            read_warnings=list(raw.warnings),
        )
    parsed.seconds_metadata = perf_counter() - start

    start = perf_counter()
    try:
        parsed.thumbnail_written = _thumbnail(data, content_hash, settings)
    except Exception as e:
        parsed.read_warnings.append(Warn(Code.THUMBNAIL_FAILED, None, describe(e)))
    parsed.seconds_thumbnail = perf_counter() - start
    return parsed


def restore_thumbnail(job: ThumbJob, settings: Settings) -> ThumbOutcome:
    """Write the missing thumbnail of an unchanged file. Nothing is recorded in the catalog,
    so a failure is retried on the next run. Content that no longer matches the indexed hash
    fails: its thumbnail would be filed under another image's key."""
    try:
        data = (settings.root / job.rel_path).read_bytes()
        if xxhash.xxh3_128_hexdigest(data) != job.content_hash:
            return "failed"
        return "written" if _thumbnail(data, job.content_hash, settings) else "exists"
    except Exception:
        return "failed"


def _thumbnail(data: bytes, content_hash: str, settings: Settings) -> bool:
    thumbs = settings.config.thumbs
    target = thumb_path(settings.thumbs, content_hash)
    return make_thumbnail(data, target, thumbs.long_edge, thumbs.quality)


def reextract(file_id: int, prompt_json: str, settings: Settings) -> Reextracted:
    """Re-run extraction from the stored API prompt; the image is never opened."""
    start = perf_counter()
    try:
        prompt = json.loads(prompt_json)
    except ValueError as e:
        extracted = Extracted("error", describe(e))
    else:
        extracted = _extracted(extract_outcome(prompt, settings.config))
    return Reextracted(file_id, extracted, perf_counter() - start)


def _extracted(out: Outcome) -> Extracted:
    nodes = []
    if out.graph is not None:
        reachable = out.reach.reachable if out.reach else set()
        nodes = [(n.id, n.class_type, n.id in reachable) for n in out.graph.nodes.values()]
    return Extracted(out.status, out.error, out.extraction, nodes, out.warnings)


# Pool plumbing: settings arrive once per worker process via the initializer.
_settings: Settings | None = None


def init_pool(settings: Settings) -> None:
    global _settings
    _settings = settings


def pool_process_file(job: Job) -> ParsedFile:
    assert _settings is not None, "init_pool was not called"
    return process_file(job, _settings)


def pool_reextract(item: tuple[int, str]) -> Reextracted:
    assert _settings is not None, "init_pool was not called"
    return reextract(item[0], item[1], _settings)


def pool_restore_thumbnail(job: ThumbJob) -> ThumbOutcome:
    assert _settings is not None, "init_pool was not called"
    return restore_thumbnail(job, _settings)
