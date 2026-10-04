"""Top configurations as whole combinations: per-field modes need not co-occur in any image."""

from typing import Any

import polars as pl

from comfylens.analytics.loras import top_values
from comfylens.extract.keys import decode_config_key


def top_configs(rows: pl.DataFrame, top_n: int) -> list[dict[str, Any]]:
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
