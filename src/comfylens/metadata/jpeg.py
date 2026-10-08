"""JPEG probe chain.

JPEG savers disagree on where metadata goes, so every probe runs and every hit is kept
with its source. Probes, in order: EXIF IFD0 `key:{json}` values (ComfyUI's WebP
convention), Exif UserComment, ImageDescription, XMP and COM segments.
"""

import bisect
import html
import json
import re
import warnings
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from PIL import Image

from comfylens.metadata.png import decode_text
from comfylens.metadata.types import Scan, TextHit, Truncated, until_truncated
from comfylens.metadata.xmp import XML_LI, read_tags
from comfylens.warn import Code, Warn

SOI = b"\xff\xd8"
EXIF_PREFIX = b"Exif\x00\x00"
XMP_PREFIX = b"http://ns.adobe.com/xap/1.0/\x00"
# SOF0-SOF15, excluding DHT (C4), JPG (C8) and DAC (CC).
_SOF_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
# Markers with no length field: RSTn and TEM.
STANDALONE_MARKERS = frozenset(range(0xD0, 0xD8)) | {0x01}
SOS, EOI = 0xDA, 0xD9
_APP1, _COM = 0xE1, 0xFE

_EXIF_IFD = 0x8769
_USER_COMMENT = 0x9286
_IMAGE_DESCRIPTION = 0x010E
_TAG_NAMES = {0x0110: "Model", 0x010F: "Make", 0x010E: "ImageDescription"}

# ComfyUI-style "prompt:{...}": an identifier, a colon, then a JSON object.
_PREFIXED = re.compile(r"\s*([A-Za-z_][\w-]{0,63}):\s*(?=\{)")


class NotJPEG(ValueError):
    """The data does not start with a JPEG SOI marker."""


@dataclass(frozen=True, slots=True)
class Segment:
    marker: int
    start: int  # of the first 0xFF, fill bytes included
    stop: int  # after the payload; for SOS, after its header only
    payload: memoryview  # empty for markers without a length field


def jpeg_segments(view: memoryview, pos: int = len(SOI)) -> Iterator[Segment]:
    """Marker segments from `pos` through the first SOS or EOI. Raises Truncated."""
    while True:
        segment = _segment(view, pos)
        yield segment
        if segment.marker in (SOS, EOI):
            return
        pos = segment.stop


def _segment(view: memoryview, start: int) -> Segment:
    pos = start
    while pos < len(view) and view[pos] == 0xFF:  # fill bytes may pad any marker
        pos += 1
    if pos == start or pos >= len(view):
        raise Truncated("the JPEG is truncated or malformed")
    marker = view[pos]
    if marker in STANDALONE_MARKERS or marker == EOI:
        return Segment(marker, start, pos + 1, view[0:0])
    length = int.from_bytes(view[pos + 1 : pos + 3])
    if pos + 3 > len(view) or length < 2 or pos + 1 + length > len(view):
        raise Truncated("the JPEG ends inside a segment")
    return Segment(marker, start, pos + 1 + length, view[pos + 3 : pos + 1 + length])


def read_jpeg(data: bytes | memoryview) -> Scan:
    view = memoryview(data)
    if bytes(view[:2]) != SOI:
        raise NotJPEG("missing JPEG SOI marker")
    segments, truncated = until_truncated(jpeg_segments(view))
    app1 = [bytes(s.payload) for s in segments if s.marker == _APP1]
    exif = next((p for p in app1 if p.startswith(EXIF_PREFIX)), None)
    xmp = [decode_text(p[len(XMP_PREFIX) :]) for p in app1 if p.startswith(XMP_PREFIX)]
    own = [(packet, read_tags(packet)) for packet in xmp]
    comments = [decode_text(bytes(s.payload)).rstrip("\0") for s in segments if s.marker == _COM]
    hits = [
        *(_exif_hits(exif) if exif is not None else []),
        *(hit for packet, tags in own if tags is None for hit in _probe_xmp(packet)),
        *(_split_prefixed(text, "comment", "jpeg:COM") for text in comments),
    ]
    warnings = [Warn(Code.TRUNCATED, None, "JPEG ends inside a segment")] if truncated else []
    return Scan(
        "jpeg",
        *_size(view, segments),
        hits=hits,
        warnings=warnings,
        tags=next((tags for _, tags in reversed(own) if tags is not None), []),
    )


def _size(view: memoryview, segments: list[Segment]) -> tuple[int, int]:
    """Width and height from the first SOF, else from Pillow."""
    sof = next(
        (s.payload for s in segments if s.marker in _SOF_MARKERS and len(s.payload) >= 5), None
    )
    if sof is not None:
        return int.from_bytes(sof[3:5]), int.from_bytes(sof[1:3])
    with Image.open(BytesIO(view)) as img:
        return img.size


def _exif_hits(segment: bytes) -> list[TextHit]:
    # Parse only the collected segment: Image.open fails on files truncated before SOS.
    exif = Image.Exif()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # Pillow warns on short reads and returns what it has
        exif.load(segment)
    hits = _probe_ifd0(exif) + _probe_user_comment(exif.get_ifd(_EXIF_IFD).get(_USER_COMMENT))
    return hits + _probe_description(exif.get(_IMAGE_DESCRIPTION), hits)


def _exif_str(value: Any) -> str | None:
    """Pillow decodes ASCII tags as Latin-1; recover UTF-8 written into them."""
    if isinstance(value, bytes):
        return decode_text(value.rstrip(b"\0"))
    if isinstance(value, str):
        try:
            return value.encode("latin-1").decode("utf-8")
        except UnicodeError:
            return value
    return None


def _split_prefixed(text: str, default_key: str, source: str) -> TextHit:
    m = _PREFIXED.match(text)
    if m:
        return TextHit(m.group(1), text[m.end() :], source)
    return TextHit(default_key, text, source)


def _probe_ifd0(exif: Image.Exif) -> list[TextHit]:
    """Probe 1: ComfyUI writes `prompt:{...}` at 0x0110, then other keys from 0x010F down."""
    hits = []
    for tag in range(0x0110, 0x00FF, -1):
        text = _exif_str(exif.get(tag))
        if text is None:
            continue
        hit = _split_prefixed(text, "", f"jpeg:exif:{_TAG_NAMES.get(tag, f'0x{tag:04X}')}")
        if hit.key:
            hits.append(hit)
    return hits


def _probe_user_comment(value: Any) -> list[TextHit]:
    """Probe 2: the first 8 bytes of UserComment name its character set."""
    if isinstance(value, str):
        text = value
    elif isinstance(value, bytes) and value:
        text = decode_user_comment(value)
    else:
        return []
    text = text.rstrip("\0")
    if not text.strip():
        return []
    return [_split_prefixed(text, "UserComment", "jpeg:exif:UserComment")]


def decode_user_comment(raw: bytes) -> str:
    head, body = raw[:8], raw[8:]
    if head == b"UNICODE\0":
        candidates = []
        for codec in ("utf-16-be", "utf-16-le"):
            try:
                candidates.append(body.decode(codec))
            except UnicodeDecodeError:
                continue
        for test in (_looks_like_json, _printable):
            for text in candidates:
                if test(text):
                    return text
        return candidates[0] if candidates else decode_text(body)
    if head in (b"ASCII\0\0\0", b"\0" * 8, b"JIS\0\0\0\0\0"):
        return decode_text(body)
    return decode_text(raw)  # no charset header at all


def _looks_like_json(text: str) -> bool:
    stripped = text.rstrip("\0").strip()
    if not stripped.startswith("{"):
        return False
    try:
        json.loads(stripped)
    except ValueError:
        return False
    return True


def _printable(text: str) -> bool:
    return all(c.isprintable() or c in "\n\r\t" for c in text.rstrip("\0"))


def _probe_description(value: Any, earlier: list[TextHit]) -> list[TextHit]:
    """Probe 3: ImageDescription as plain JSON or A1111 text, unless probe 1 claimed it."""
    text = _exif_str(value)
    if text is None or not text.strip():
        return []
    if any(h.source == "jpeg:exif:ImageDescription" for h in earlier):
        return []
    return [TextHit("ImageDescription", text, "jpeg:exif:ImageDescription")]


_XML_ATTR = re.compile(r"""([\w.-]+:)?([\w.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_XML_OPEN = re.compile(r"<(?![/?!])(?:([\w.-]+):)?([\w.-]+)")
_CDATA = re.compile(r"^\s*<!\[CDATA\[(.*)\]\]>\s*$", re.S)


def _probe_xmp(packet: str) -> list[TextHit]:
    """Probe 4: keep the whole packet, plus every attribute value or rdf:li holding JSON.

    Regexes rather than an XML parser: packets may be malformed, and no entity is expanded.
    """
    hits = [TextHit("xmp", packet, "jpeg:xmp")]
    for m in _XML_ATTR.finditer(packet):
        value = html.unescape(m.group(3) if m.group(3) is not None else m.group(4))
        if value.lstrip().startswith("{"):
            hits.append(TextHit(m.group(2), value, "jpeg:xmp"))

    # An rdf:li is named after the nearest enclosing property element (dc:description, ...).
    opens = [(m.start(), m.group(2)) for m in _XML_OPEN.finditer(packet) if m.group(1) != "rdf"]
    starts = [pos for pos, _ in opens]
    for m in XML_LI.finditer(packet):
        inner = m.group(1)
        cdata = _CDATA.match(inner)
        value = cdata.group(1) if cdata else html.unescape(inner)
        if not value.lstrip().startswith("{"):
            continue
        k = bisect.bisect_left(starts, m.start()) - 1
        hits.append(TextHit(opens[k][1] if k >= 0 else "xmp_li", value, "jpeg:xmp"))
    return hits
