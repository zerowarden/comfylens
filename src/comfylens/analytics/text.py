"""Prompt normalization, segmentation, and the units counted: phrases and n-grams."""

import re
import unicodedata
from importlib import resources
from pathlib import Path

_LORA_TAG = re.compile(r"<(?:lora|lyco):[^>]*>")
# "(text:1.2)" with unescaped parentheses and no nested ones; applied until nothing changes.
_WEIGHTED = re.compile(r"(?<!\\)\(([^()]*?)\s*:\s*-?(?:\d+(?:\.\d*)?|\.\d+)\s*(?<!\\)\)")
_BRACKETS = re.compile(r"(?<!\\)[()\[\]{}]")
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n\s*")
_SENTENCE_END = re.compile(r"[.!?]+(?=\s|$)|;")
_SEGMENT_END = re.compile(r"[,:]")
_TOKEN = re.compile(r"[\w'-]+")
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


def normalize(text: str) -> str:
    """NFKC and lowercase; drop LoRA tags; strip weight syntax and brackets."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = _LORA_TAG.sub("", text)
    while True:
        unweighted = _WEIGHTED.sub(r"\1", text)
        if unweighted == text:
            break
        text = unweighted
    text = _BRACKETS.sub("", text)
    return text.replace("\\(", "(").replace("\\)", ")")


def paragraphs(text: str) -> list[str]:
    """Two or more newlines break paragraphs; a single newline is a soft wrap."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return [p.replace("\n", " ").strip() for p in _PARAGRAPH_BREAK.split(text) if p.strip()]


def sentences(prompt: str) -> list[str]:
    """Normalized sentences, split on . ! ? before whitespace, and on ;."""
    return [
        s.strip()
        for p in paragraphs(normalize(prompt))
        for s in _SENTENCE_END.split(p)
        if s.strip()
    ]


def segments(sentence: str) -> list[str]:
    return [s.strip() for s in _SEGMENT_END.split(sentence) if s.strip()]


def tokens(segment: str) -> list[str]:
    """Word tokens; a token containing CJK becomes its character bigrams."""
    out: list[str] = []
    for token in _TOKEN.findall(segment):
        if _CJK.search(token) and len(token) > 1:
            out += [token[i : i + 2] for i in range(len(token) - 1)]
        else:
            out.append(token)
    return out


_NUMBER = re.compile(r"[\d.,'-]+")


def load_stopwords(path: str = "") -> frozenset[str]:
    """The bundled list, or one word per line from `path`; # starts a comment."""
    if path:
        text = Path(path).expanduser().read_text("utf-8")
    else:
        text = resources.files("comfylens.data").joinpath("stopwords_en.txt").read_text("utf-8")
    words = (line.split("#", 1)[0].strip().lower() for line in text.splitlines())
    return frozenset(w for w in words if w)


def units(
    sentence: str, stopwords: frozenset[str], max_phrase_words: int, max_ngram: int
) -> set[tuple[str, str]]:
    """(kind, term) pairs in one normalized sentence: phrases and n-grams, deduplicated.

    Phrases are whole segments after trimming leading and trailing stopwords. N-grams stay
    within a segment and never start or end with a stopword. Neither is ever pure numbers.
    """
    found: set[tuple[str, str]] = set()
    for segment in segments(sentence):
        words = tokens(segment)
        start, end = 0, len(words)
        while start < end and words[start] in stopwords:
            start += 1
        while end > start and words[end - 1] in stopwords:
            end -= 1
        phrase = words[start:end]
        if 1 <= len(phrase) <= max_phrase_words and not all(_NUMBER.fullmatch(w) for w in phrase):
            found.add(("phrase", " ".join(phrase)))
        for n in range(1, max_ngram + 1):
            for i in range(len(words) - n + 1):
                gram = words[i : i + n]
                if gram[0] in stopwords or gram[-1] in stopwords:
                    continue
                if all(_NUMBER.fullmatch(w) for w in gram):
                    continue
                found.add((f"{n}g", " ".join(gram)))
    return found
