"""generated_at and the burst plausibility check.

ComfyUI embeds no generation time, so the timeline uses file times. A burst of many distinct
generations stamped within seconds means a bulk copy reset the times, not generation.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from comfylens.config import TimestampsConfig


def generated_at(rel_path: str, mtime_ns: int, config: TimestampsConfig) -> int:
    """Unix seconds: from the path when a filename pattern matches, else from mtime."""
    if config.source == "filename":
        for pattern in config.filename_patterns:
            m = pattern.regex.search(rel_path)
            if m is None:
                continue
            try:
                # A naive datetime: read in the system's local time zone.
                return int(datetime.strptime(m.group("ts"), pattern.format).timestamp())
            except ValueError, OverflowError:
                continue
    return mtime_ns // 1_000_000_000


@dataclass(frozen=True, slots=True)
class Cluster:
    start_ns: int
    end_ns: int
    file_ids: tuple[int, ...]
    distinct_generations: int

    def to_json(self) -> dict[str, float | int]:
        return {
            "start": self.start_ns / 1e9,
            "end": self.end_ns / 1e9,
            "files": len(self.file_ids),
            "distinct_generations": self.distinct_generations,
        }


def burst_clusters(
    rows: Sequence[tuple[int, int, str]], window_seconds: float, min_distinct: int
) -> list[Cluster]:
    """Clusters of files whose mtimes look like a bulk copy.

    `rows` are (file_id, mtime_ns, generation_key). A window of `window_seconds` with at least
    `min_distinct` distinct keys is suspect; a batch shares one key, so it counts once.
    Overlapping suspect windows merge into one cluster.
    """
    ordered = sorted(rows, key=lambda r: (r[1], r[0]))
    window_ns = int(window_seconds * 1e9)
    counts: Counter[str] = Counter()
    spans: list[list[int]] = []  # [first index, last index] of merged suspect windows
    left = 0
    for right, (_, t, key) in enumerate(ordered):
        counts[key] += 1
        while t - ordered[left][1] > window_ns:
            old = ordered[left][2]
            counts[old] -= 1
            if counts[old] == 0:
                del counts[old]
            left += 1
        if len(counts) >= min_distinct:
            if spans and left <= spans[-1][1]:
                spans[-1][1] = right
            else:
                spans.append([left, right])

    clusters = []
    for first, last in spans:
        members = ordered[first : last + 1]
        clusters.append(
            Cluster(
                start_ns=members[0][1],
                end_ns=members[-1][1],
                file_ids=tuple(r[0] for r in members),
                distinct_generations=len({r[2] for r in members}),
            )
        )
    return clusters
