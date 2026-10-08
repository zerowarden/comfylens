"""Tags written into PNG and JPEG files as a comfylens XMP packet, spliced in byte for byte.

Every other byte is kept, so taking the packet out gives back the exact file: the content hash
leaves it out, and tagging never changes a file's identity.
"""

import contextlib

import xxhash

from comfylens.metadata import xmp
from comfylens.metadata.jpeg import SOI, XMP_PREFIX, jpeg_segments
from comfylens.metadata.png import SIGNATURE, XMP_KEYWORD, chunk_bytes, png_chunks
from comfylens.metadata.types import Truncated


class CannotTag(ValueError):
    """Not a PNG or JPEG, too damaged to splice, holding another program's XMP, or too many
    tags."""


_FOREIGN = "the file already holds XMP metadata from another program"
_PNG_XMP = XMP_KEYWORD.encode() + b"\0"
_APP1 = 0xE1
_LEADING = {*range(0xE0, 0xF0), 0xFE}  # APPn and COM


def hash_content(data: bytes) -> str:
    """xxh3_128 of the file as it would be without its comfylens packet."""
    if xmp.NAMESPACE_BYTES in data:  # most files hold none: skip the walk
        with contextlib.suppress(CannotTag):  # unspliceable: hashed as it is
            data = write_tags(data, [])
    return xxhash.xxh3_128_hexdigest(data)


def write_tags(data: bytes, tags: list[str]) -> bytes:
    """`data` with its comfylens packet holding `tags`, or without one when `tags` is empty.
    Raises CannotTag."""
    if len(tags) > xmp.MAX_TAGS:
        raise CannotTag(f"a file holds at most {xmp.MAX_TAGS} tags")
    packet = xmp.build_packet(tags) if tags else None
    splice = _png if data.startswith(SIGNATURE) else _jpeg if data.startswith(SOI) else None
    if splice is None:
        raise CannotTag("only PNG and JPEG files can be tagged")
    try:
        return splice(memoryview(data), packet)
    except Truncated as e:
        raise CannotTag(str(e)) from e


def _png(view: memoryview, packet: bytes | None) -> bytes:
    """The packet goes right after IHDR, the first chunk, as an uncompressed iTXt chunk."""
    chunks = list(png_chunks(view))
    kept = [
        view[c.start : c.stop]
        for c in chunks
        if c.type != b"iTXt" or _keeps(c.data, _PNG_XMP, packet)
    ]
    # Uncompressed, with no language or translated keyword.
    inserted = [_itxt(_PNG_XMP + b"\0\0\0\0" + packet)] if packet else []
    after_end = view[chunks[-1].stop :]  # bytes after the image end stay too
    return b"".join([SIGNATURE, *kept[:1], *inserted, *kept[1:], after_end])


def _jpeg(view: memoryview, packet: bytes | None) -> bytes:
    """The packet goes after the leading APPn (JFIF, Exif) and COM segments, as APP1."""
    segments = list(jpeg_segments(view))  # through SOS or EOI, which is never leading
    split = next(i for i, s in enumerate(segments) if s.marker not in _LEADING)
    kept = [
        view[s.start : s.stop]
        if s.marker != _APP1 or _keeps(s.payload, XMP_PREFIX, packet)
        else b""
        for s in segments[:-1]
    ]
    inserted = [_app1(XMP_PREFIX + packet)] if packet else []
    rest = view[segments[-1].start :]  # the image data and everything after it, untouched
    return b"".join([SOI, *kept[:split], *inserted, *kept[split:], rest])


def _itxt(text: bytes) -> bytes:
    return chunk_bytes(b"iTXt", text)


def _app1(payload: bytes) -> bytes:
    return bytes((0xFF, _APP1)) + (len(payload) + 2).to_bytes(2) + payload


def _keeps(body: memoryview, prefix: bytes, packet: bytes | None) -> bool:
    """Whether a chunk or segment stays: all but comfylens's packet. Another program's packet
    stays, and blocks writing one of ours."""
    data = bytes(body)
    if not data.startswith(prefix):
        return True
    if xmp.NAMESPACE_BYTES in data:
        return False
    if packet is not None:
        raise CannotTag(_FOREIGN)
    return True
