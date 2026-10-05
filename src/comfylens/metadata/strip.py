"""Copies of PNG and JPEG files without their metadata, the image data untouched.

Nothing is decoded or re-encoded: the kept chunks and segments are copied byte for byte, so the
copy has the original's exact pixels. Kept is what decoding and colour need: for PNG the header,
palette, transparency, colour space and profile, animation frames and image data; for JPEG the
tables, frame and scan headers, entropy-coded data, JFIF header, ICC profile and Adobe colour
transform. Everything else goes, including ComfyUI's prompt and workflow, EXIF, XMP, IPTC,
comments, timestamps, physical size, embedded thumbnails and any bytes after the image ends.
"""

import struct

from comfylens.metadata.jpeg import SOI
from comfylens.metadata.png import SIGNATURE


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
_PNG_CHUNK = struct.Struct(">I4s")

_EOI, _SOS, _APP0, _APP2, _APP14, _COM = 0xD9, 0xDA, 0xE0, 0xE2, 0xEE, 0xFE
_APPS = range(0xE0, 0xF0)
_STANDALONE = frozenset(range(0xD0, 0xD8)) | {0x01}  # RSTn and TEM carry no length
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
    out: list[bytes | memoryview] = [SIGNATURE]
    pos, end = len(SIGNATURE), len(view)
    while True:
        if pos + 12 > end:
            raise CannotStrip("the PNG ends before its IEND chunk")
        length, ctype = _PNG_CHUNK.unpack_from(view, pos)
        stop = pos + 12 + length  # length and type, data, CRC
        if stop > end:
            raise CannotStrip("the PNG ends inside a chunk")
        if ctype in _PNG_KEEP:
            out.append(view[pos:stop])
        pos = stop
        if ctype == b"IEND":
            return b"".join(out)


def strip_jpeg(data: bytes) -> bytes:
    if not data.startswith(SOI):
        raise CannotStrip("missing JPEG SOI marker")
    view = memoryview(data)
    out: list[bytes | memoryview] = [SOI]
    pos, end = len(SOI), len(view)
    while True:
        if pos >= end or view[pos] != 0xFF:
            raise CannotStrip("the JPEG is truncated or malformed")
        while pos < end and view[pos] == 0xFF:  # fill bytes may pad any marker
            pos += 1
        if pos >= end:
            raise CannotStrip("the JPEG ends inside a marker")
        marker = view[pos]
        pos += 1
        if marker == _EOI:
            out.append(bytes((0xFF, _EOI)))
            return b"".join(out)
        if marker in _STANDALONE:
            out.append(bytes((0xFF, marker)))
            continue
        if pos + 2 > end:
            raise CannotStrip("the JPEG ends inside a segment")
        length = int.from_bytes(view[pos : pos + 2])
        if length < 2 or pos + length > end:
            raise CannotStrip("the JPEG ends inside a segment")
        payload = view[pos + 2 : pos + length]
        if marker == _APP0 and bytes(payload[: len(_JFIF)]) == _JFIF:
            if len(payload) < _JFIF_HEADER:
                raise CannotStrip("the JPEG has a short JFIF header")
            # The header without its thumbnail: a zero width and height, no pixels.
            jfif = bytes(payload[:_JFIF_HEADER]) + b"\0\0"
            out.append(bytes((0xFF, _APP0)) + (len(jfif) + 2).to_bytes(2) + jfif)
        elif (marker not in _APPS and marker != _COM) or _keeps_app(marker, payload):
            out.append(view[pos - 2 : pos + length])
        pos += length
        if marker == _SOS:
            scan_end = _scan_end(data, pos)
            out.append(view[pos:scan_end])
            pos = scan_end


def _keeps_app(marker: int, payload: memoryview) -> bool:
    """The application segments that change how the pixels decode or look."""
    if marker == _APP2:
        return bytes(payload[: len(_ICC)]) == _ICC
    if marker == _APP14:
        return bytes(payload[: len(_ADOBE)]) == _ADOBE
    return False


def _scan_end(data: bytes, pos: int) -> int:
    """Where the entropy-coded data from `pos` ends: the next marker other than RSTn.

    Inside the data, 0xFF is followed by a stuffed 0x00, a restart marker or more 0xFF fill.
    """
    while True:
        pos = data.find(b"\xff", pos)
        if pos < 0 or pos + 1 >= len(data):
            raise CannotStrip("the JPEG ends inside its image data")
        following = data[pos + 1]
        if following == 0xFF:
            pos += 1
        elif following == 0 or 0xD0 <= following <= 0xD7:
            pos += 2
        else:
            return pos
