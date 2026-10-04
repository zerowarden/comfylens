"""Configuration: built-in defaults merged with the user's TOML file.

Every key must exist in data/default_config.toml. A user file is merged over the defaults
key by key: tables merge recursively, every other value (arrays included) replaces the default.
"""

import json
import os
import re
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import xxhash

from comfylens.paths import config_path


class ConfigError(ValueError):
    """The configuration is invalid; the message names the offending key."""


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    open_browser: bool


@dataclass(frozen=True)
class IndexConfig:
    extensions: tuple[str, ...]
    exclude_globs: tuple[str, ...]
    follow_symlinks: bool
    workers: int
    batch_size: int


def resolve_workers(requested: int) -> int:
    """0 means os.cpu_count() - 2, at least 1."""
    return requested if requested > 0 else max(1, (os.cpu_count() or 3) - 2)


@dataclass(frozen=True)
class ThumbsConfig:
    long_edge: int
    quality: int


@dataclass(frozen=True)
class AnalysisConfig:
    group_by_family: bool
    dedupe_identical_files: bool
    round_decimals: int
    config_round_decimals: int
    top_n: int
    histogram_bins: int
    discrete_max_distinct: int


@dataclass(frozen=True)
class PromptsConfig:
    max_phrase_words: int
    max_ngram: int
    min_df: int
    template_threshold: float
    template_min_scope: int
    stopwords_file: str
    distinctive_alpha0: float


@dataclass(frozen=True)
class FilenamePattern:
    regex: re.Pattern[str]
    format: str


@dataclass(frozen=True)
class TimestampsConfig:
    source: str
    filename_patterns: tuple[FilenamePattern, ...]
    burst_window_seconds: float
    burst_min_distinct: int


@dataclass(frozen=True)
class LoraConfig:
    step_suffix_regex: re.Pattern[str]


@dataclass(frozen=True)
class GraphConfig:
    output_classes: frozenset[str]
    output_name_regex: re.Pattern[str]


@dataclass(frozen=True)
class FamilyCondition:
    """One entry of a rule's `any` list; every key it sets must match."""

    unet_regex: re.Pattern[str] | None = None
    ckpt_regex: re.Pattern[str] | None = None
    clip_type: str | None = None
    class_regex: re.Pattern[str] | None = None


@dataclass(frozen=True)
class FamilyRule:
    name: str
    any: tuple[FamilyCondition, ...]


@dataclass(frozen=True)
class Config:
    server: ServerConfig
    index: IndexConfig
    thumbs: ThumbsConfig
    analysis: AnalysisConfig
    prompts: PromptsConfig
    timestamps: TimestampsConfig
    lora: LoraConfig
    graph: GraphConfig
    families: tuple[FamilyRule, ...]
    # Hash of everything that changes stored extraction results; a change triggers re-extraction.
    config_hash: str


def load_config(path: Path | None = None) -> Config:
    """Load the defaults merged with `path` (default: the XDG config file, if it exists)."""
    path = path or config_path()
    user: dict[str, Any] = {}
    if path.is_file():
        try:
            user = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{path}: {e}") from e
    return build_config(user)


def build_config(user: dict[str, Any]) -> Config:
    """Merge `user` over the bundled defaults and validate the result."""
    defaults = tomllib.loads(
        resources.files("comfylens.data").joinpath("default_config.toml").read_text("utf-8")
    )
    return _build(_merge(defaults, user, ""))


def _merge(defaults: dict[str, Any], user: dict[str, Any], where: str) -> dict[str, Any]:
    out = dict(defaults)
    for key, value in user.items():
        name = f"{where}{key}"
        if key not in defaults:
            raise ConfigError(f"unknown config key: {name}")
        default = defaults[key]
        if isinstance(default, dict):
            if not isinstance(value, dict):
                raise ConfigError(f"{name} must be a table")
            out[key] = _merge(default, value, f"{name}.")
        else:
            out[key] = _coerce(name, default, value)
    return out


def _coerce(name: str, default: Any, value: Any) -> Any:
    if isinstance(default, bool):
        ok = isinstance(value, bool)
    elif isinstance(default, int):
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif isinstance(default, float):
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        value = float(value) if ok else value
    else:
        ok = isinstance(value, type(default))
    if not ok:
        raise ConfigError(f"{name} must be of type {type(default).__name__}")
    return value


def _regex(name: str, pattern: Any) -> re.Pattern[str]:
    if not isinstance(pattern, str):
        raise ConfigError(f"{name} must be a string")
    try:
        return re.compile(pattern)
    except re.error as e:
        raise ConfigError(f"{name}: invalid regex: {e}") from e


def _strings(name: str, values: list[Any]) -> tuple[str, ...]:
    if not all(isinstance(v, str) for v in values):
        raise ConfigError(f"{name} must be a list of strings")
    return tuple(values)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


def _build(m: dict[str, Any]) -> Config:
    server = ServerConfig(**m["server"])
    _require(1 <= server.port <= 65535, "server.port must be between 1 and 65535")

    i = m["index"]
    index = IndexConfig(
        extensions=tuple(e.lower() for e in _strings("index.extensions", i["extensions"])),
        exclude_globs=_strings("index.exclude_globs", i["exclude_globs"]),
        follow_symlinks=i["follow_symlinks"],
        workers=i["workers"],
        batch_size=i["batch_size"],
    )
    _require(index.workers >= 0, "index.workers must be >= 0")
    _require(index.batch_size >= 1, "index.batch_size must be >= 1")

    thumbs = ThumbsConfig(**m["thumbs"])
    _require(thumbs.long_edge >= 16, "thumbs.long_edge must be >= 16")
    _require(0 <= thumbs.quality <= 100, "thumbs.quality must be between 0 and 100")

    analysis = AnalysisConfig(**m["analysis"])
    _require(analysis.round_decimals >= 0, "analysis.round_decimals must be >= 0")
    _require(analysis.config_round_decimals >= 0, "analysis.config_round_decimals must be >= 0")

    prompts = PromptsConfig(**m["prompts"])
    _require(0 < prompts.template_threshold <= 1, "prompts.template_threshold must be in (0, 1]")
    _require(prompts.distinctive_alpha0 > 0, "prompts.distinctive_alpha0 must be > 0")

    t = m["timestamps"]
    _require(
        t["source"] in ("mtime", "filename"), 'timestamps.source must be "mtime" or "filename"'
    )
    patterns: list[FilenamePattern] = []
    for n, entry in enumerate(t["filename_patterns"]):
        name = f"timestamps.filename_patterns[{n}]"
        _require(
            isinstance(entry, dict) and set(entry) == {"regex", "format"},
            f"{name} must be a table with keys regex and format",
        )
        regex = _regex(f"{name}.regex", entry["regex"])
        _require("ts" in regex.groupindex, f"{name}.regex needs a named group 'ts'")
        _require(isinstance(entry["format"], str), f"{name}.format must be a string")
        patterns.append(FilenamePattern(regex, entry["format"]))
    timestamps = TimestampsConfig(
        source=t["source"],
        filename_patterns=tuple(patterns),
        burst_window_seconds=t["burst_window_seconds"],
        burst_min_distinct=t["burst_min_distinct"],
    )

    step_regex = _regex("lora.step_suffix_regex", m["lora"]["step_suffix_regex"])
    _require(
        {"base", "step"} <= set(step_regex.groupindex),
        "lora.step_suffix_regex needs named groups 'base' and 'step'",
    )
    lora = LoraConfig(step_regex)

    g = m["graph"]
    graph = GraphConfig(
        output_classes=frozenset(_strings("graph.output_classes", g["output_classes"])),
        output_name_regex=_regex("graph.output_name_regex", g["output_name_regex"]),
    )

    families = tuple(_family(n, rule) for n, rule in enumerate(m["families"]))

    hashed = {
        "graph": m["graph"],
        "lora": m["lora"],
        "families": m["families"],
        # Stored lora_stack_key and config_key depend on it.
        "config_round_decimals": analysis.config_round_decimals,
    }
    config_hash = xxhash.xxh3_64_hexdigest(json.dumps(hashed, sort_keys=True).encode())

    return Config(
        server, index, thumbs, analysis, prompts, timestamps, lora, graph, families, config_hash
    )


_CONDITION_KEYS = {"unet_regex", "ckpt_regex", "clip_type", "class_regex"}


def _family(n: int, rule: Any) -> FamilyRule:
    where = f"families[{n}]"
    _require(isinstance(rule, dict) and set(rule) == {"name", "any"}, f"{where} needs name and any")
    _require(isinstance(rule["name"], str) and rule["name"] != "", f"{where}.name must be a string")
    _require(
        isinstance(rule["any"], list) and len(rule["any"]) > 0,
        f"{where}.any must be a non-empty list",
    )
    conditions: list[FamilyCondition] = []
    for k, cond in enumerate(rule["any"]):
        name = f"{where}.any[{k}]"
        _require(isinstance(cond, dict) and len(cond) > 0, f"{name} must be a non-empty table")
        unknown = set(cond) - _CONDITION_KEYS
        _require(not unknown, f"{name}: unknown keys {sorted(unknown)}")
        clip_type = cond.get("clip_type")
        _require(clip_type is None or isinstance(clip_type, str), f"{name}.clip_type: string")
        regexes = {
            key: _regex(f"{name}.{key}", cond[key])
            for key in ("unet_regex", "ckpt_regex", "class_regex")
            if key in cond
        }
        conditions.append(FamilyCondition(clip_type=clip_type, **regexes))
    return FamilyRule(rule["name"], tuple(conditions))
