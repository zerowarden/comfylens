"""The /api/stats sections per family group."""

from dataclasses import asdict
from typing import Any

import polars as pl

from comfylens.analytics.categorical import seed_stats, value_counts
from comfylens.analytics.configs import top_configs
from comfylens.analytics.loras import lora_table, stacks
from comfylens.analytics.numeric import HistogramSpec, numeric_stats
from comfylens.analytics.scope import POOLED, Resolved
from comfylens.analytics.snapshot import Snapshot
from comfylens.config import AnalysisConfig

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


def compute_stats(
    snap: Snapshot,
    resolved: Resolved,
    sections: list[str],
    lora_key: str,
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
            fields = (("model_family",) if group == POOLED else ()) + CATEGORICAL_FIELDS
            block["categorical"] = {
                name: value_counts(rows[name], analysis.top_n) for name in fields
            }
        if "seeds" in sections:
            block["seeds"] = seed_stats(rows["seed"])
        if "loras" in sections:
            uses = snap.loras.filter(pl.col("file_id").is_in(rows["id"].implode()))
            block["loras"] = lora_table(uses, size, lora_key, analysis.round_decimals, spec)  # type: ignore[arg-type]
        if "stacks" in sections:
            block["stacks"] = stacks(rows, analysis.top_n)
        if "configs" in sections:
            block["configs"] = top_configs(rows, analysis.top_n)
        out.append(block)
    return out
