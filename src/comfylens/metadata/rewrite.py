"""PNG text chunks rewritten in place, every other byte kept.

A replaced chunk keeps its type, keyword, position and, for iTXt, its compression flag,
language and translated keyword. Its text is written as UTF-8 (JSON from json.dumps is ASCII).
"""

import zlib
from collections.abc import Callable

from comfylens.metadata.png import SIGNATURE, chunk_bytes, png_chunks, text_chunk
from comfylens.metadata.types import Truncated


class CannotRewrite(ValueError):
    """Not a PNG, too damaged to splice, or a text to replace is not in it."""


def replace_png_texts(data: bytes, texts: dict[str, str]) -> bytes:
    """`data` with each text chunk whose text is a key of `texts` holding its value instead."""
    if not data.startswith(SIGNATURE):
        raise CannotRewrite("only PNG files can be fixed")
    view = memoryview(data)
    try:
        chunks = list(png_chunks(view))
    except Truncated as e:
        raise CannotRewrite(str(e)) from e
    # Each text chunk decoded once: (chunk, its text hit or None).
    hits = [(c, text_chunk(c.type, bytes(c.data)) if c.type in _REBUILD else None) for c in chunks]
    if missing := texts.keys() - {hit.text for _, hit in hits if hit}:
        raise CannotRewrite(f"{len(missing)} text chunk(s) to rewrite were not found")
    parts = [
        _rebuilt(c.type, bytes(c.data), texts[hit.text])
        if hit and hit.text in texts
        else view[c.start : c.stop]
        for c, hit in hits
    ]
    return b"".join([SIGNATURE, *parts, view[chunks[-1].stop :]])


def _rebuilt(ctype: bytes, body: bytes, text: str) -> bytes:
    """The whole chunk again, with `text` in place of its text."""
    keyword, _, rest = body.partition(b"\0")
    new = keyword + b"\0" + _REBUILD[ctype](rest, text.encode())
    return chunk_bytes(ctype, new)


def _itxt(rest: bytes, text: bytes) -> bytes:
    """The compression flag and method, language and translated keyword stay as they were."""
    compressed = rest[0] == 1
    language, _, after = rest[2:].partition(b"\0")
    translated, _, _ = after.partition(b"\0")
    payload = zlib.compress(text) if compressed else text
    return rest[:2] + language + b"\0" + translated + b"\0" + payload


# What follows the keyword's NUL, by chunk type, from the old remainder and the new text.
_REBUILD: dict[bytes, Callable[[bytes, bytes], bytes]] = {
    b"tEXt": lambda _rest, text: text,
    b"zTXt": lambda _rest, text: b"\0" + zlib.compress(text),  # compression method 0: zlib
    b"iTXt": _itxt,
}
