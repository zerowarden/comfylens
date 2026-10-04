"""PNG chunk walker: dimensions and text chunks, without decoding pixels."""

import struct
import zlib

from comfylens.metadata.types import MAX_TEXT_BYTES, Scan, TextHit
from comfylens.warn import Code, Warn

SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CHUNK_HEADER = struct.Struct(">I4s")
_IHDR = struct.Struct(">II")


class NotPNG(ValueError):
    """The data does not start with the PNG signature."""


def read_png(data: bytes | memoryview) -> Scan:
    view = memoryview(data)
    if bytes(view[:8]) != SIGNATURE:
        raise NotPNG("missing PNG signature")

    size: tuple[int, int] | None = None
    hits: list[TextHit] = []
    pos, end, complete = 8, len(view), False
    while pos + 8 <= end:
        length, ctype = _CHUNK_HEADER.unpack_from(view, pos)
        start, stop = pos + 8, pos + 8 + length
        if stop > end:
            break
        if ctype == b"IHDR" and length >= 8:
            size = _IHDR.unpack_from(view, start)
        elif ctype in (b"tEXt", b"zTXt", b"iTXt"):
            hit = _text_chunk(ctype.decode("ascii"), bytes(view[start:stop]))
            if hit is not None:
                hits.append(hit)
        elif ctype == b"IEND":
            complete = True
            break
        # IDAT and every other chunk are skipped: text chunks may follow image data.
        pos = stop + 4  # CRCs are not verified

    if size is None:
        raise ValueError("PNG has no IHDR chunk")
    warnings = [] if complete else [Warn(Code.TRUNCATED, None, "PNG ends before IEND")]
    return Scan("png", size[0], size[1], hits, warnings)


def _text_chunk(ctype: str, data: bytes) -> TextHit | None:
    keyword, sep, rest = data.partition(b"\0")
    if not sep:
        return None
    if ctype == "zTXt":
        # One compression-method byte, then zlib data.
        payload = _inflate(rest[1:])
    elif ctype == "iTXt":
        if len(rest) < 2:
            return None
        compressed = rest[0] == 1
        _language, _, rest = rest[2:].partition(b"\0")
        _translated, _, payload = rest.partition(b"\0")
        if compressed:
            payload = _inflate(payload)
    else:
        payload = rest
    if payload is None:
        return None
    return TextHit(keyword.decode("latin-1"), decode_text(payload), f"png:{ctype}")


def _inflate(data: bytes) -> bytes | None:
    """Inflate zlib data, refusing corrupt streams and outputs above MAX_TEXT_BYTES."""
    inflater = zlib.decompressobj()
    try:
        out = inflater.decompress(data, MAX_TEXT_BYTES + 1)
    except zlib.error:
        return None
    return None if len(out) > MAX_TEXT_BYTES else out


def decode_text(raw: bytes) -> str:
    """UTF-8, falling back to Latin-1: the PNG spec says Latin-1, but writers emit UTF-8."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")
