from comfylens.analytics.text import (
    load_stopwords,
    normalize,
    paragraphs,
    segments,
    sentences,
    tokens,
    units,
)


def test_weight_syntax_and_brackets():
    assert normalize("(red hat:1.2), ((blue:1.1) sky:.9), [x], {y}") == "red hat, blue sky, x, y"
    assert normalize(r"a \(literal\) paren") == "a (literal) paren"
    assert normalize("(unweighted group)") == "unweighted group"


def test_lora_tags_removed():
    assert normalize("a cat <lora:cat_v2:0.8> <LYCO:x:1> sitting") == "a cat   sitting"


def test_nfkc_and_lowercase():
    assert normalize("ＦＵＬＬ Width") == "full width"  # noqa: RUF001


def test_soft_wrapped_lines_join_and_paragraphs_split():
    text = "one sentence wrapped\nacross lines.\n\nsecond\nparagraph"
    assert paragraphs(text) == ["one sentence wrapped across lines.", "second paragraph"]


def test_sentences():
    assert sentences("Hello there. How are you? Fine!Great; ok... done 1.5 units") == [
        "hello there",
        "how are you",
        "fine!great",
        "ok",
        "done 1.5 units",
    ]


def test_segments_and_tokens():
    assert segments("a, b: c,, d") == ["a", "b", "c", "d"]
    assert tokens("the cat's well-lit room 2025") == ["the", "cat's", "well-lit", "room", "2025"]


def test_cjk_bigrams():
    assert tokens("猫が好き cat 犬") == ["猫が", "が好", "好き", "cat", "犬"]


SW = frozenset({"the", "a", "and", "of", "in", "from"})


def test_phrases_trim_stopwords():
    found = units("and camera angle, a portrait of the queen", SW, 6, 3)
    phrases = {t for k, t in found if k == "phrase"}
    assert phrases == {"camera angle", "portrait of the queen"}


def test_ngrams_respect_stopword_boundaries_and_numbers():
    found = units("the cat in the hat 2025", SW, 6, 3)
    grams = {(k, t) for k, t in found if k != "phrase"}
    assert ("1g", "cat") in grams and ("1g", "the") not in grams
    assert ("2g", "hat 2025") in grams
    assert ("1g", "2025") not in grams  # pure number
    assert ("3g", "cat in the") not in grams  # ends with a stopword
    assert not any(t.startswith("the ") for _, t in grams)


def test_ngrams_never_cross_segments():
    found = units("red fox, blue sky", SW, 6, 3)
    assert ("2g", "fox blue") not in found
    assert ("2g", "red fox") in found


def test_long_segments_are_not_phrases():
    found = units("one two three four five six seven", SW, 6, 3)
    assert not any(k == "phrase" for k, _ in found)


def test_bundled_stopwords():
    words = load_stopwords()
    assert {"the", "and", "of"} <= words and "fox" not in words
    assert len(words) > 100
