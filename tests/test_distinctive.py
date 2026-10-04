import math

import polars as pl
import pytest

from comfylens.analytics.distinctive import distinctive_terms
from comfylens.analytics.prompts import build_prompt_frames
from comfylens.config import build_config

ALPHA0 = 500.0


@pytest.fixture
def frames():
    rows = [(i, "a fox in the snow", None) for i in range(1, 6)]  # the selection
    rows += [(6, "a zebra fox in the snow", None)]  # also selected: one rare term
    rows += [(i, "an owl in the snow", None) for i in range(7, 31)]  # the rest
    return build_prompt_frames(rows, build_config({}).prompts)


def ids(*values):
    return pl.DataFrame(
        {"id": list(values), "group": ["g"] * len(values)},
        schema={"id": pl.Int64, "group": pl.String},
    )


def run(frames, selection, rest, library=None):
    library = library if library is not None else ids(*range(1, 31))
    return distinctive_terms(frames, selection, rest, library, "positive", "image", ALPHA0)["g"]


def test_terms_of_each_side_rank_first(frames):
    out = run(frames, ids(*range(1, 7)), ids(*range(7, 31)))
    assert (out["selection_images"], out["rest_images"]) == (6, 24)
    top = out["unigrams"]["selection"][0]
    assert (top["term"], top["selection_df"], top["rest_df"]) == ("fox", 6, 0)
    assert top["selection_share"] == 1.0 and top["z"] > 0
    assert out["unigrams"]["rest"][0]["term"] == "owl"
    # Shared by every image: not distinctive either way.
    everywhere = [t for lst in out["unigrams"].values() for t in lst if t["term"] == "snow"]
    assert all(abs(t["z"]) < 0.5 for t in everywhere)


def test_small_samples_are_shrunk_large_ones_are_significant():
    """alpha0 pseudo-counts keep 6 images from looking significant; 60 against 240 are."""
    rows = [(i, "a fox in the snow", None) for i in range(1, 61)]
    rows += [(i, "an owl in the snow", None) for i in range(61, 301)]
    frames = build_prompt_frames(rows, build_config({}).prompts)
    out = run(frames, ids(*range(1, 61)), ids(*range(61, 301)), ids(*range(1, 301)))
    assert out["unigrams"]["selection"][0]["term"] == "fox"
    assert out["unigrams"]["selection"][0]["z"] > 1.96
    assert out["unigrams"]["rest"][0]["z"] < -1.96


def test_a_rare_term_does_not_outrank_a_consistent_one(frames):
    out = run(frames, ids(*range(1, 7)), ids(*range(7, 31)))
    z = {t["term"]: t["z"] for t in out["unigrams"]["selection"]}
    assert z["fox"] > z["zebra"] > 0


def test_matches_the_formula(frames):
    out = run(frames, ids(*range(1, 7)), ids(*range(7, 31)))
    # Unigram counts: selection fox 6, snow 6, zebra 1 (n_s = 13); rest owl 24, snow 24
    # (n_r = 48); library fox 6, snow 30, zebra 1, owl 24 (n_p = 61).
    y_s, y_r, n_s, n_r = 6, 0, 13, 48
    a = ALPHA0 * 6 / 61
    delta = math.log((y_s + a) / (n_s + ALPHA0 - y_s - a)) - math.log(
        (y_r + a) / (n_r + ALPHA0 - y_r - a)
    )
    expected = delta / math.sqrt(1 / (y_s + a) + 1 / (y_r + a))
    fox = next(t for t in out["unigrams"]["selection"] if t["term"] == "fox")
    assert fox["z"] == pytest.approx(expected)


def test_empty_rest(frames):
    out = run(frames, ids(1, 2), ids())
    assert out["rest_images"] == 0
    assert out["unigrams"]["rest"] == []
