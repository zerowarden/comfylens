"""Prompt analysis.

Prompts repeat heavily, so each distinct prompt is segmented once into frames keyed by its
prompt key; a query joins the scope's image count per key onto them and aggregates in Polars.
"""

from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any, Literal

import polars as pl
import xxhash

from comfylens.analytics.loras import EXAMPLES, recent_examples
from comfylens.analytics.text import load_stopwords, sentences, units
from comfylens.config import PromptsConfig
from comfylens.extract.normalize import prompt_ws

Side = Literal["positive", "negative"]
# Whether each image counts once, or each distinct prompt does.
By = Literal["image", "unique_prompt"]
NGRAM_KINDS = ("1g", "2g", "3g")
TOP_TERMS = 50
TOP_DISTINCT = 50
SUBSUME_CANDIDATES = 500
SUBSUME_SHARE = 0.9
SMALL_SCOPE = 10  # below this many images, keep terms seen once
_POOL_THRESHOLD = 5000  # distinct prompts; fewer are segmented in-process


@dataclass(frozen=True, slots=True)
class PromptFrames:
    file_keys: pl.DataFrame  # file_id, positive, negative: prompt keys (UInt64) or null
    texts: pl.DataFrame  # key, text
    sentences: pl.DataFrame  # key, sentence (UInt64 hash), sentence_text
    units: pl.DataFrame  # key, sentence, kind, term; unique per sentence


_FILE_KEYS_SCHEMA = {"file_id": pl.Int64, "positive": pl.UInt64, "negative": pl.UInt64}
_TEXTS_SCHEMA = {"key": pl.UInt64, "text": pl.String}
_SENTENCES_SCHEMA = {"key": pl.UInt64, "sentence": pl.UInt64, "sentence_text": pl.String}
_UNITS_SCHEMA = {"key": pl.UInt64, "sentence": pl.UInt64, "kind": pl.String, "term": pl.String}


def empty_prompt_frames() -> PromptFrames:
    return PromptFrames(
        pl.DataFrame(schema=_FILE_KEYS_SCHEMA),
        pl.DataFrame(schema=_TEXTS_SCHEMA),
        pl.DataFrame(schema=_SENTENCES_SCHEMA),
        pl.DataFrame(schema=_UNITS_SCHEMA),
    )


def prompt_key(text: str | None) -> int | None:
    """xxh3_64 of the whitespace-normalized prompt; None for an empty prompt."""
    normalized = prompt_ws(text or "")
    return xxhash.xxh3_64_intdigest(normalized.encode()) if normalized else None


def build_prompt_frames(
    rows: Sequence[tuple[int, str | None, str | None]],
    config: PromptsConfig,
    workers: int = 1,
) -> PromptFrames:
    """`rows` are (file_id, positive_prompt, negative_prompt); `workers` for the pool path."""
    texts: dict[int, str] = {}
    file_keys = []
    for file_id, positive, negative in rows:
        keys = []
        for text in (positive, negative):
            key = prompt_key(text)
            if key is not None:
                texts.setdefault(key, text or "")
            keys.append(key)
        file_keys.append((file_id, *keys))

    items = list(texts.items())
    stopwords = load_stopwords(config.stopwords_file)
    args = (stopwords, config.max_phrase_words, config.max_ngram)
    if len(items) < _POOL_THRESHOLD:
        parts = [_segment(items, *args)]
    else:
        workers = max(1, workers)
        size = max(500, len(items) // (workers * 4))
        chunks = [items[i : i + size] for i in range(0, len(items), size)]
        with ProcessPoolExecutor(workers) as pool:
            parts = list(pool.map(_segment, chunks, *([a] * len(chunks) for a in args)))

    return PromptFrames(
        file_keys=pl.DataFrame(file_keys, schema=_FILE_KEYS_SCHEMA, orient="row"),
        texts=pl.DataFrame(
            {"key": list(texts), "text": list(texts.values())}, schema=_TEXTS_SCHEMA
        ),
        sentences=pl.concat([p[0] for p in parts]),
        units=pl.concat([p[1] for p in parts]),
    )


def _segment(
    items: list[tuple[int, str]], stopwords: frozenset[str], max_phrase_words: int, max_ngram: int
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Sentences and units of each distinct prompt. Runs in pool workers."""
    sentence_rows: list[tuple[int, int, str]] = []
    unit_rows: list[tuple[int, int, str, str]] = []
    for key, text in items:
        seen: set[int] = set()
        for sentence in sentences(text):
            sentence_hash = xxhash.xxh3_64_intdigest(sentence.encode())
            if sentence_hash in seen:
                continue
            seen.add(sentence_hash)
            sentence_rows.append((key, sentence_hash, sentence))
            for kind, term in units(sentence, stopwords, max_phrase_words, max_ngram):
                unit_rows.append((key, sentence_hash, kind, term))
    return (
        pl.DataFrame(sentence_rows, schema=_SENTENCES_SCHEMA, orient="row"),
        pl.DataFrame(unit_rows, schema=_UNITS_SCHEMA, orient="row"),
    )


def analyze_prompts(
    frames: PromptFrames,
    scope: pl.DataFrame,
    side: Side,
    *,
    include_template: bool,
    by: By,
    config: PromptsConfig,
) -> list[dict[str, Any]]:
    """One block per group of `scope`: columns id, content_hash, group, generated_at.

    Groups come largest first.
    """
    rows = with_keys(frames, scope, side)
    sizes = rows.group_by("group").len().sort("len", "group", descending=[True, False])
    return [
        _group(frames, rows.filter(pl.col("group") == group), group, include_template, by, config)
        for group in sizes["group"]
    ]


def with_keys(frames: PromptFrames, scope: pl.DataFrame, side: Side) -> pl.DataFrame:
    """Scope rows with the prompt key of `side` as column `key`; rows without one dropped."""
    return scope.join(
        frames.file_keys.select("file_id", pl.col(side).alias("key")),
        left_on="id",
        right_on="file_id",
    ).filter(pl.col("key").is_not_null())


def document_weight(by: By) -> pl.Expr:
    """A `count` column's document frequency: images, or 1 per distinct prompt."""
    return pl.col("count") if by == "image" else pl.lit(1, pl.UInt32)


def unit_counts(
    frames: PromptFrames, weighted: pl.DataFrame, excluded_sentences: pl.Series | None = None
) -> pl.DataFrame:
    """kind, term, df: each image (or prompt) counts once per term, whatever its repeats."""
    found = frames.units.join(weighted, on="key")
    if excluded_sentences is not None and excluded_sentences.len():
        found = found.filter(~pl.col("sentence").is_in(excluded_sentences.implode()))
    return (
        found.unique(["key", "kind", "term"])
        .group_by("kind", "term")
        .agg(pl.col("w").sum().alias("df"))
    )


def _group(
    frames: PromptFrames,
    keyed: pl.DataFrame,
    group: str,
    include_template: bool,
    by: By,
    config: PromptsConfig,
) -> dict[str, Any]:
    per_key = keyed.group_by("key").agg(
        pl.len().alias("count"),
        pl.col("generated_at").min().alias("first"),
        pl.col("generated_at").max().alias("last"),
        recent_examples("id").head(EXAMPLES).alias("ex"),
        recent_examples("content_hash").head(EXAMPLES).alias("ex_hashes"),
    )
    images = int(per_key["count"].sum())
    # Document frequency counts images, or distinct prompts with by="unique_prompt".
    weighted = per_key.select("key", document_weight(by).alias("w"))
    total = int(weighted["w"].sum())

    sentence_df = (
        frames.sentences.join(weighted, on="key")
        .group_by("sentence")
        .agg(pl.col("w").sum().alias("df"), pl.col("sentence_text").first().alias("text"))
    )
    templates = sentence_df.head(0)
    if total >= config.template_min_scope:
        templates = sentence_df.filter(pl.col("df") >= config.template_threshold * total)
    all_template = templates.height > 0 and templates.height == sentence_df.height

    excluded = templates["sentence"] if not include_template else None
    counts = unit_counts(frames, weighted, excluded).filter(
        pl.col("df") >= (config.min_df if images >= SMALL_SCOPE else 1)
    )
    counts = _drop_subsumed(counts)

    def terms(kind: str) -> list[dict[str, Any]]:
        top = (
            counts.filter(pl.col("kind") == kind)
            .sort("df", "term", descending=[True, False])
            .head(TOP_TERMS)
        )
        return [
            {"term": t, "df": d, "share": d / total}
            for t, d in top.select("term", "df").iter_rows()
        ]

    distinct = (
        per_key.sort("count", "key", descending=[True, False])
        .head(TOP_DISTINCT)
        .join(frames.texts, on="key", how="left", maintain_order="left")
    )
    return {
        "family": group,
        "images": images,
        "distinct_total": per_key.height,
        "all_template": all_template,
        "templates": [
            {"text": text, "df": df, "share": df / total}
            for text, df in templates.sort("df", "text", descending=[True, False])
            .select("text", "df")
            .iter_rows()
        ],
        "phrases": terms("phrase"),
        "unigrams": terms("1g"),
        "bigrams": terms("2g"),
        "trigrams": terms("3g"),
        "distinct": [
            {
                "key": f"{key:016x}",
                "text": text,
                "count": count,
                "share": count / images,
                "first": first,
                "last": last,
                "examples": ex,
                "example_hashes": ex_hashes,
            }
            for key, count, first, last, ex, ex_hashes, text in distinct.select(
                "key", "count", "first", "last", "ex", "ex_hashes", "text"
            ).iter_rows()
        ],
    }


def _drop_subsumed(counts: pl.DataFrame) -> pl.DataFrame:
    """Drop an n-gram when a longer one containing it has at least 90% of its df.

    Only the top 500 n-gram candidates are compared, so "realistic photograph" does not
    also list "realistic" and "photograph" with the same counts.
    """
    candidates = (
        counts.filter(pl.col("kind").is_in(NGRAM_KINDS))
        .sort("df", "term", descending=[True, False])
        .head(SUBSUME_CANDIDATES)
    )
    df = dict(zip(candidates["term"], candidates["df"], strict=True))
    # For every candidate, the largest df of a longer candidate that contains it.
    containing: dict[str, int] = {}
    for term, count in df.items():
        words = term.split(" ")
        for n in range(1, len(words)):
            for i in range(len(words) - n + 1):
                inner = " ".join(words[i : i + n])
                if inner in df:
                    containing[inner] = max(containing.get(inner, 0), count)
    dropped = [t for t, count in df.items() if containing.get(t, 0) >= SUBSUME_SHARE * count]
    if not dropped:
        return counts
    return counts.filter(~(pl.col("kind").is_in(NGRAM_KINDS) & pl.col("term").is_in(dropped)))
