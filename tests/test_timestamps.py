import re
import time
from datetime import datetime

from comfylens.config import FilenamePattern, build_config
from comfylens.index.timestamps import burst_clusters, generated_at

S = 1_000_000_000  # one second in ns


def test_mtime_source():
    ts = build_config({}).timestamps
    assert generated_at("a.png", 1_790_649_651_329_171_267, ts) == 1_790_649_651


def test_filename_source_reads_local_time_and_falls_back():
    pattern = r"(?P<ts>\d{8}-\d{6})"
    ts = build_config(
        {
            "timestamps": {
                "source": "filename",
                "filename_patterns": [{"regex": pattern, "format": "%Y%m%d-%H%M%S"}],
            }
        }
    ).timestamps
    assert ts.filename_patterns == (FilenamePattern(re.compile(pattern), "%Y%m%d-%H%M%S"),)
    expected = int(time.mktime(datetime(2026, 9, 29, 10, 40, 51).timetuple()))
    assert generated_at("day/ComfyUI_20260929-104051_0001.png", 5 * S, ts) == expected
    assert generated_at("ComfyUI_00001_.png", 5 * S, ts) == 5  # no match: mtime
    assert generated_at("x_20261399-999999.png", 7 * S, ts) == 7  # unparsable: mtime


def test_a_batch_sharing_one_key_is_not_flagged():
    rows = [(i, 100 * S + i * 10_000_000, "same-batch") for i in range(40)]
    assert burst_clusters(rows, 2.0, 10) == []


def test_slow_generation_is_not_flagged():
    rows = [(i, i * 30 * S, f"gen{i}") for i in range(50)]
    assert burst_clusters(rows, 2.0, 10) == []


def test_bulk_copy_is_flagged_and_windows_merge():
    normal = [(i, i * 60 * S, f"old{i}") for i in range(5)]
    # 30 distinct generations copied within 3 s: overlapping 2 s windows merge into one cluster.
    copied = [(100 + i, 10_000 * S + i * 100_000_000, f"gen{i}") for i in range(30)]
    later = [(200, 20_000 * S, "late")]
    (cluster,) = burst_clusters(normal + copied + later, 2.0, 10)
    assert cluster.file_ids == tuple(range(100, 130))
    assert cluster.distinct_generations == 30
    assert cluster.to_json()["files"] == 30
    assert cluster.start_ns == 10_000 * S


def test_threshold_counts_distinct_keys():
    rows = [(i, 50 * S + i, f"g{i % 9}") for i in range(90)]  # 9 distinct keys only
    assert burst_clusters(rows, 2.0, 10) == []
    assert len(burst_clusters(rows, 2.0, 9)) == 1
