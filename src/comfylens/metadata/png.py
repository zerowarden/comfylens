"""PNG chunk walker: dimensions and text chunks, without decoding pixels."""

import struct
import zlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from comfylens.metadata.types import MAX_TEXT_BYTES, Scan, TextHit, Truncated, until_truncated
from comfylens.metadata.xmp import read_tags
from comfylens.warn import Code, Warn

SIGNATURE = b"\x89PNG\r\n\x1a\n"
XMP_KEYWORD = "XML:com.adobe.xmp"  # the iTXt keyword the XMP specification gives PNG
_CHUNK_HEADER = struct.Struct(">I4s")
_IHDR = struct.Struct(">II")


class NotPNG(ValueError):
    """The data does not start with the PNG signature."""


@dataclass(frozen=True, slots=True)
class Chunk:
    type: bytes
    start: int  # of the length field
    stop: int  # after the CRC
    data: memoryview


def png_chunks(view: memoryview) -> Iterator[Chunk]:
    """Every chunk after the signature, through IEND; CRCs are not verified. Raises Truncated."""
    pos = len(SIGNATURE)
    while True:
        if pos + 12 > len(view):
            raise Truncated("the PNG ends before its IEND chunk")
        length, ctype = _CHUNK_HEADER.unpack_from(view, pos)
        stop = pos + 12 + length  # length and type, data, CRC
        if stop > len(view):
            raise Truncated("the PNG ends inside a chunk")
        yield Chunk(ctype, pos, stop, view[pos + 8 : stop - 4])
        if ctype == b"IEND":
            return
        pos = stop


def chunk_bytes(ctype: bytes, body: bytes) -> bytes:
    """A whole PNG chunk: length, type, body and CRC."""
    return _CHUNK_HEADER.pack(len(body), ctype) + body + zlib.crc32(ctype + body).to_bytes(4)


def read_png(data: bytes | memoryview) -> Scan:
    view = memoryview(data)
    if bytes(view[:8]) != SIGNATURE:
        raise NotPNG("missing PNG signature")
    # Text chunks may follow the image data, so every chunk is read.
    chunks, truncated = until_truncated(png_chunks(view))
    ihdr = next((c.data for c in chunks if c.type == b"IHDR" and len(c.data) >= 8), None)
    if ihdr is None:
        raise ValueError("PNG has no IHDR chunk")
    texts = [
        hit
        for c in chunks
        if c.type in _TEXT_PAYLOADS and (hit := text_chunk(c.type, bytes(c.data)))
    ]
    own = [(hit, _own_tags(hit)) for hit in texts]
    warnings = [Warn(Code.TRUNCATED, None, "PNG ends before IEND")] if truncated else []
    return Scan(
        "png",
        *_IHDR.unpack_from(ihdr),
        hits=[hit for hit, tags in own if tags is None],
        warnings=warnings,
        tags=next((tags for _, tags in reversed(own) if tags is not None), []),
    )


def _own_tags(hit: TextHit) -> list[str] | None:
    return read_tags(hit.text) if hit.key == XMP_KEYWORD else None


def _itxt_payload(rest: bytes) -> bytes | None:
    """Compression flag and method, language and translated keyword, then the text."""
    if len(rest) < 2:
        return None
    parts = rest[2:].split(b"\0", 2)
    payload = parts[2] if len(parts) == 3 else b""
    return _inflate(payload) if rest[0] == 1 else payload


# What follows a text chunk's keyword, by chunk type, to its text bytes.
_TEXT_PAYLOADS: dict[bytes, Callable[[bytes], bytes | None]] = {
    b"tEXt": lambda rest: rest,
    b"zTXt": lambda rest: _inflate(rest[1:]),  # one compression-method byte, then zlib data
    b"iTXt": _itxt_payload,
}


def text_chunk(ctype: bytes, data: bytes) -> TextHit | None:
    keyword, sep, rest = data.partition(b"\0")
    payload = _TEXT_PAYLOADS[ctype](rest) if sep else None
    if payload is None:
        return None
    return TextHit(keyword.decode("latin-1"), decode_text(payload), f"png:{ctype.decode()}")


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
