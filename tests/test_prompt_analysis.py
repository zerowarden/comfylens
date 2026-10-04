from typing import Literal

import polars as pl
import pytest

from comfylens.analytics.prompts import Side, analyze_prompts, build_prompt_frames, prompt_key
from comfylens.config import PromptsConfig, build_config

TEMPLATE = "Preserve the subject's identity and pose."


@pytest.fixture
def cfg() -> PromptsConfig:
    return build_config({}).prompts


def run(
    rows,
    cfg,
    *,
    ids=None,
    include_template=False,
    by: Literal["image", "unique_prompt"] = "image",
    side: Side = "positive",
):
    frames = build_prompt_frames(rows, cfg)
    ids = ids or [r[0] for r in rows]
    hashes = [f"h{i}" for i in ids]
    scope = pl.DataFrame(
        {"id": ids, "content_hash": hashes, "group": ["g"] * len(ids), "generated_at": ids}
    )
    (group,) = analyze_prompts(
        frames, scope, side, include_template=include_template, by=by, config=cfg
    )
    return group


def terms(group, kind):
    return {r["term"]: r["df"] for r in group[kind]}


def test_prompt_key_ignores_whitespace_differences():
    assert prompt_key("a  cat\r\n") == prompt_key("a cat")
    assert prompt_key("   ") is None and prompt_key(None) is None


def test_document_frequency_counts_images_once(cfg):
    rows = [
        (1, "red fox, red fox, snow", None),
        (2, "red fox in the forest", None),
        (3, "a blue whale", None),
    ]
    g = run(rows, cfg)
    assert g["images"] == 3
    assert terms(g, "bigrams")["red fox"] == 2  # repeated within one prompt: counted once
    assert g["bigrams"][0]["share"] == pytest.approx(2 / 3)


def test_template_sentences_are_reported_and_excluded(cfg):
    rows = [(i, f"{TEMPLATE} A {w} in the rain.", None) for i, w in enumerate(
        ["fox", "fox", "cat", "owl", "fox", "dog"], start=1)]  # fmt: skip
    g = run(rows, cfg)
    assert [t["text"] for t in g["templates"]] == ["preserve the subject's identity and pose"]
    assert g["templates"][0]["share"] == 1.0
    assert "subject's identity" not in terms(g, "bigrams")
    assert terms(g, "unigrams")["fox"] == 3
    with_template = run(rows, cfg, include_template=True)
    # "identity" itself is subsumed by "subject's identity", which has the same df.
    assert terms(with_template, "bigrams")["subject's identity"] == 6


def test_small_scopes_detect_no_templates(cfg):
    rows = [(i, f"{TEMPLATE} A fox.", None) for i in range(1, 5)]  # 4 < template_min_scope
    g = run(rows, cfg)
    assert g["templates"] == []
    assert "subject's identity" in terms(g, "bigrams")


def test_all_template_is_reported(cfg):
    rows = [(i, TEMPLATE, None) for i in range(1, 8)]
    g = run(rows, cfg)
    assert g["all_template"] is True
    assert g["unigrams"] == [] and g["phrases"] == []


def test_min_df_applies_from_ten_images(cfg):
    rows = [(i, "common words here" if i <= 9 else "rare thing", None) for i in range(1, 11)]
    g = run(rows, cfg)
    assert "rare" not in terms(g, "unigrams")  # df 1 < min_df 2 with 10 images
    small = run(rows, cfg, ids=[1, 2, 10])
    assert terms(small, "bigrams")["rare thing"] == 1  # fewer than 10 images: df >= 1


def test_subsumption_drops_contained_ngrams(cfg):
    # Different sentences each time, so none of them is template text.
    rows = [(i, f"realistic photograph, {w}", None) for i, w in enumerate("abcdefghij", 1)]
    rows += [(11, "realistic", None), (12, "photograph of a cat", None)]
    g = run(rows, cfg)
    # "realistic photograph" (df 10) holds >= 90% of "realistic" (11) and "photograph" (11).
    assert "realistic photograph" in terms(g, "bigrams")
    assert "realistic" not in terms(g, "unigrams")
    assert "photograph" not in terms(g, "unigrams")
    assert "cat" not in terms(g, "unigrams")  # df 1 < min_df


def test_by_unique_prompt_and_distinct_prompts(cfg):
    rows = [(1, "a fox", None), (2, "a fox", None), (3, "a fox", None), (4, "an owl", "blur")]
    g = run(rows, cfg, by="unique_prompt")
    assert terms(g, "unigrams") == {"fox": 1, "owl": 1}
    assert g["distinct_total"] == 2
    top = g["distinct"][0]
    assert (top["text"], top["count"], top["share"], top["examples"]) == (
        "a fox",
        3,
        0.75,
        [3, 2, 1],
    )
    assert top["example_hashes"] == ["h3", "h2", "h1"]
    assert len(top["key"]) == 16
    negative = run(rows, cfg, side="negative")
    assert (negative["images"], negative["distinct_total"]) == (1, 1)
