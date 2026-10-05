"""The /api/stats sections per family group."""

from dataclasses import asdict
from typing import Any

import polars as pl

from comfylens.analytics.categorical import seed_stats, value_counts
from comfylens.analytics.loras import LoraKey, lora_graph, lora_table, top_values
from comfylens.analytics.numeric import HistogramSpec, numeric_stats
from comfylens.analytics.scope import Resolved
from comfylens.analytics.snapshot import Snapshot
from comfylens.config import AnalysisConfig
from comfylens.extract.keys import decode_config_key

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
    out = []
    for group, rows in resolved.groups():
        size = rows.height
        block: dict[str, Any] = {"family": group, "images": size}
        if "numeric" in sections:
            block["numeric"] = {
                name: asdict(numeric_stats(rows[name], analysis.round_decimals, spec))
                for name in NUMERIC_FIELDS
            }
        if "categorical" in sections:
            block["categorical"] = {
                name: value_counts(rows[name], analysis.top_n) for name in CATEGORICAL_FIELDS
            }
        if "seeds" in sections:
            block["seeds"] = seed_stats(rows["seed"])
        if "loras" in sections or "graph" in sections:
            uses = snap.loras.filter(pl.col("file_id").is_in(rows["id"].implode()))
        if "loras" in sections:
            block["loras"] = lora_table(uses, size, lora_key, analysis.round_decimals, spec)
        if "graph" in sections:
            block["graph"] = lora_graph(uses, lora_key, analysis.top_n)
        if "configs" in sections:
            block["configs"] = top_configs(rows, analysis.top_n)
        out.append(block)
    return out
