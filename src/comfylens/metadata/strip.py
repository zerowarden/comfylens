"""Copies of PNG and JPEG files without their metadata, the image data untouched.

Nothing is decoded or re-encoded: the kept chunks and segments are copied byte for byte, so the
copy has the original's exact pixels. Kept is what decoding and colour need: for PNG the header,
palette, transparency, colour space and profile, animation frames and image data; for JPEG the
tables, frame and scan headers, entropy-coded data, JFIF header, ICC profile and Adobe colour
transform. Everything else goes, including ComfyUI's prompt and workflow, EXIF, XMP, IPTC,
comments, timestamps, physical size, embedded thumbnails and any bytes after the image ends.
"""

from collections.abc import Iterator

from comfylens.metadata.jpeg import EOI, SOI, Segment, jpeg_segments
from comfylens.metadata.png import SIGNATURE, png_chunks
from comfylens.metadata.types import Truncated


class CannotStrip(ValueError):
    """Not a PNG or JPEG, or too damaged to copy without guessing."""


_PNG_KEEP = frozenset(
    {
        b"IHDR",
        b"PLTE",
        b"IDAT",
        b"IEND",
        b"tRNS",  # transparency
        b"gAMA",  # colour: gamma, chromaticities, sRGB intent, ICC profile, significant bits
        b"cHRM",
        b"sRGB",
        b"iCCP",
        b"sBIT",
        b"cICP",  # HDR colour: coding points, mastering display, content light level
        b"mDCV",
        b"cLLI",
        b"acTL",  # APNG animation control and frames
        b"fcTL",
        b"fdAT",
    }
)
_APP0, _APP2, _APP14, _COM = 0xE0, 0xE2, 0xEE, 0xFE
_APPS = range(0xE0, 0xF0)
_JFIF = b"JFIF\0"
_JFIF_HEADER = 12  # identifier, version, density units, x and y density; then thumbnail size
_ICC = b"ICC_PROFILE\0"
_ADOBE = b"Adobe"


def strip_metadata(data: bytes) -> bytes:
    """`data` without its metadata. Raises CannotStrip."""
    if data.startswith(SIGNATURE):
        return strip_png(data)
    if data.startswith(SOI):
        return strip_jpeg(data)
    raise CannotStrip("only PNG and JPEG files can be exported without metadata")


def strip_png(data: bytes) -> bytes:
    if not data.startswith(SIGNATURE):
        raise CannotStrip("missing PNG signature")
    view = memoryview(data)
    try:
        chunks = list(png_chunks(view))
    except Truncated as e:
        raise CannotStrip(str(e)) from e
    return b"".join([SIGNATURE, *(view[c.start : c.stop] for c in chunks if c.type in _PNG_KEEP)])


def strip_jpeg(data: bytes) -> bytes:
    if not data.startswith(SOI):
        raise CannotStrip("missing JPEG SOI marker")
    try:
        return b"".join([SOI, *_jpeg_kept(data)])
    except Truncated as e:
        raise CannotStrip(str(e)) from e


def _jpeg_kept(data: bytes) -> Iterator[bytes | memoryview]:
    """The kept segments, each scan's entropy-coded data after its SOS, through EOI. Bytes after
    EOI are dropped."""
    view, pos = memoryview(data), len(SOI)
    while True:
        segments = list(jpeg_segments(view, pos))
        yield from (kept for s in segments if (kept := _kept(view, s)) is not None)
        last = segments[-1]
        if last.marker == EOI:
            return
        pos = _scan_end(data, last.stop)
        yield view[last.stop : pos]


def _kept(view: memoryview, s: Segment) -> bytes | memoryview | None:
    """The segment as the copy holds it: JFIF without its thumbnail, only the application
    segments that change how the pixels decode or look, and everything else as it is."""
    if s.marker == _APP0 and bytes(s.payload[: len(_JFIF)]) == _JFIF:
        if len(s.payload) < _JFIF_HEADER:
            raise CannotStrip("the JPEG has a short JFIF header")
        jfif = bytes(s.payload[:_JFIF_HEADER]) + b"\0\0"  # a zero width and height, no pixels
        return bytes((0xFF, _APP0)) + (len(jfif) + 2).to_bytes(2) + jfif
    if s.marker in _APPS or s.marker == _COM:
        return view[s.start : s.stop] if _keeps_app(s.marker, s.payload) else None
    return view[s.start : s.stop]


def _keeps_app(marker: int, payload: memoryview) -> bool:
    prefix = {_APP2: _ICC, _APP14: _ADOBE}.get(marker)
    return prefix is not None and bytes(payload[: len(prefix)]) == prefix


def _scan_end(data: bytes, pos: int) -> int:
    """Where the entropy-coded data from `pos` ends: the next marker other than RSTn.

    Inside the data, 0xFF is followed by a stuffed 0x00, a restart marker or more 0xFF fill.
    """
    while True:
        pos = data.find(b"\xff", pos)
        if pos < 0 or pos + 1 >= len(data):
            raise Truncated("the JPEG ends inside its image data")
        following = data[pos + 1]
        if following == 0xFF:
            pos += 1
        elif following == 0 or 0xD0 <= following <= 0xD7:
            pos += 2
        else:
            return pos
