"""The /api/stats sections per family group."""

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

import polars as pl

from comfylens.analytics.categorical import seed_stats, tag_counts, value_counts
from comfylens.analytics.loras import LoraKey, lora_table, top_values
from comfylens.analytics.numeric import HistogramSpec, numeric_stats
from comfylens.analytics.scope import Resolved
from comfylens.analytics.snapshot import Snapshot
from comfylens.config import AnalysisConfig
from comfylens.extract import decode_config_key

NUMERIC_FIELDS = (
    "steps",
    "cfg",
    "denoise",
    "guidance",
    "shift",
    "stage_count",
    "megapixels",
    "width",
    "height",
    "aspect",
)
CATEGORICAL_FIELDS = (
    "base_model",
    "text_encoder",
    "clip_type",
    "vae",
    "sampler_name",
    "scheduler",
    "latent_source",
    "aspect_label",
    "resolution",
    "lora_stack_key",
)


def histogram_spec(analysis: AnalysisConfig) -> HistogramSpec:
    return HistogramSpec(analysis.discrete_max_distinct, analysis.histogram_bins)


def top_configs(rows: pl.DataFrame, top_n: int) -> list[dict[str, Any]]:
    """Top configurations as whole combinations: per-field modes need not co-occur in any image."""
    size = rows.height
    return [
        {
            "key": key,
            "count": count,
            "share": count / size,
            "fields": decode_config_key(key),
            "examples": ids,
            "example_hashes": hashes,
        }
        for key, count, ids, hashes in top_values(rows, "config_key", top_n).iter_rows()
    ]


def compute_stats(
    snap: Snapshot,
    resolved: Resolved,
    sections: list[str],
    lora_key: LoraKey,
    analysis: AnalysisConfig,
) -> list[dict[str, Any]]:
    spec = histogram_spec(analysis)
    digits, top_n = analysis.round_decimals, analysis.top_n
    # Each requested section, from the family's rows and its LoRA uses.
    builders: dict[str, Callable[[pl.DataFrame, pl.DataFrame], Any]] = {
        "numeric": lambda rows, _: {
            name: asdict(numeric_stats(rows[name], digits, spec)) for name in NUMERIC_FIELDS
        },
        "categorical": lambda rows, _: {
            **{name: value_counts(rows[name], top_n) for name in CATEGORICAL_FIELDS},
            "tags": tag_counts(rows["tags"], top_n),
        },
        "seeds": lambda rows, _: seed_stats(rows["seed"]),
        "loras": lambda rows, uses: lora_table(uses, rows.height, lora_key, digits, spec),
        "configs": lambda rows, _: top_configs(rows, top_n),
    }
    wanted = {name: build for name, build in builders.items() if name in sections}

    def block(group: str, rows: pl.DataFrame) -> dict[str, Any]:
        in_family = pl.col("file_id").is_in(rows["id"].implode())
        uses = snap.loras.filter(in_family) if "loras" in wanted else snap.loras.clear()
        built = {name: build(rows, uses) for name, build in wanted.items()}
        return {"family": group, "images": rows.height, **built}

    return [block(group, rows) for group, rows in resolved.groups()]
