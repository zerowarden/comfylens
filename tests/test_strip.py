import json
import random
import struct
from io import BytesIO

import pytest
from conftest import chunk, golden_png
from PIL import Image, ImageCms

from comfylens.metadata import read_metadata
from comfylens.metadata.jpeg import EXIF_PREFIX, XMP_PREFIX
from comfylens.metadata.png import SIGNATURE
from comfylens.metadata.strip import CannotStrip, strip_jpeg, strip_metadata, strip_png

API = {"3": {"class_type": "KSampler", "inputs": {"seed": 1}}}
ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def noise(size: tuple[int, int] = (48, 32), mode: str = "RGB") -> Image.Image:
    """Random pixels, so a re-encode would show in the comparison."""
    rng = random.Random(7)
    bands = len(mode)
    return Image.frombytes(
        mode, size, bytes(rng.randrange(256) for _ in range(size[0] * size[1] * bands))
    )


def pixels(data: bytes) -> tuple[str, tuple[int, int], bytes]:
    with Image.open(BytesIO(data)) as img:
        img.load()
        return img.mode, img.size, img.tobytes()


def png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    out, pos = [], len(SIGNATURE)
    while pos < len(data):
        length, ctype = struct.unpack_from(">I4s", data, pos)
        out.append((ctype, data[pos + 8 : pos + 8 + length]))
        pos += 12 + length
    return out


def jpeg_segments(data: bytes) -> list[tuple[int, bytes]]:
    """Markers and payloads up to the first SOS."""
    out, pos = [], 2
    while data[pos + 1] != 0xDA:
        marker, length = data[pos + 1], int.from_bytes(data[pos + 2 : pos + 4])
        out.append((marker, data[pos + 4 : pos + 2 + length]))
        pos += 2 + length
    return out


def segment(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + (len(payload) + 2).to_bytes(2) + payload


def with_segments(data: bytes, *segments: bytes) -> bytes:
    """`segments` right after SOI."""
    return data[:2] + b"".join(segments) + data[2:]


def comfy_exif() -> Image.Exif:
    exif = Image.Exif()
    exif[0x0110] = "prompt:" + json.dumps(API)
    exif[0x010F] = "workflow:{}"
    exif[0x0132] = "2026:10:05 12:00:00"
    return exif


# --- PNG ----------------------------------------------------------------------------------------


def test_png_loses_text_and_keeps_pixels_and_colour():
    buf = BytesIO()
    noise().save(buf, "PNG", icc_profile=ICC, dpi=(300, 300))
    original = buf.getvalue()
    end = original.rindex(b"IEND") - 4
    extra = (
        chunk(b"tEXt", b"prompt\0" + json.dumps(API).encode())
        + chunk(b"zTXt", b"workflow\0\0" + b"x\x9c\x03\x00\x00\x00\x00\x01")
        + chunk(b"iTXt", b"parameters\0\0\0\0\0Steps: 20")
        + chunk(b"eXIf", comfy_exif().tobytes())
        + chunk(b"tIME", bytes(7))
        + chunk(b"prVt", b"private")
    )
    original = original[:end] + extra + original[end:]
    assert read_metadata(original).texts

    stripped = strip_png(original)
    types = [t for t, _ in png_chunks(stripped)]
    assert types[0] == b"IHDR" and types[-1] == b"IEND"
    assert b"iCCP" in types
    assert not {b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME", b"pHYs", b"prVt"} & set(types)
    assert read_metadata(stripped).texts == {}
    # The image data is copied, not re-encoded.
    idat = b"".join(d for t, d in png_chunks(original) if t == b"IDAT")
    assert b"".join(d for t, d in png_chunks(stripped) if t == b"IDAT") == idat
    assert pixels(stripped) == pixels(original)
    with Image.open(BytesIO(stripped)) as img:
        assert img.info.get("icc_profile") == ICC


def test_png_keeps_palette_and_transparency():
    buf = BytesIO()
    noise(mode="RGB").quantize(16).save(buf, "PNG", transparency=0)
    original = buf.getvalue()
    stripped = strip_png(original)
    assert pixels(stripped) == pixels(original)
    with Image.open(BytesIO(stripped)) as img:
        assert img.mode == "P" and img.info["transparency"] == 0


def test_apng_keeps_its_frames():
    frames = [Image.new("RGB", (8, 8), c) for c in ("red", "green", "blue")]
    buf = BytesIO()
    frames[0].save(buf, "PNG", save_all=True, append_images=frames[1:], duration=100)
    stripped = strip_png(with_prompt(buf.getvalue()))
    with Image.open(BytesIO(stripped)) as img:
        assert getattr(img, "n_frames", 1) == 3
        img.seek(2)
        assert img.convert("RGB").getpixel((0, 0)) == (0, 0, 255)


def with_prompt(data: bytes) -> bytes:
    """`data` with ComfyUI's text chunks before IEND."""
    end = data.rindex(b"IEND") - 4
    return data[:end] + chunk(b"tEXt", b"prompt\0" + json.dumps(API).encode()) + data[end:]


def test_golden_png_has_no_metadata_left():
    original = golden_png()
    stripped = strip_metadata(original)
    meta = read_metadata(stripped)
    assert meta.texts == {} and meta.api_prompt is None and meta.workflow is None
    assert pixels(stripped) == pixels(original)


@pytest.mark.parametrize("cut", [10, 40, -6])
def test_truncated_png_is_refused(cut: int):
    with pytest.raises(CannotStrip):
        strip_png(golden_png()[:cut])


# --- JPEG ---------------------------------------------------------------------------------------


# The fake MPF segment makes Pillow warn about the original; the copy no longer has it.
@pytest.mark.filterwarnings("ignore:Image appears to be a malformed MPO file")
@pytest.mark.parametrize("options", [{}, {"progressive": True}, {"restart_marker_blocks": 1}])
def test_jpeg_loses_exif_xmp_and_comments_and_keeps_the_scans(options: dict[str, object]):
    buf = BytesIO()
    noise().save(buf, "JPEG", quality=90, exif=comfy_exif().tobytes(), icc_profile=ICC, **options)
    original = with_segments(
        buf.getvalue(),
        segment(0xE1, XMP_PREFIX + b"<x:xmpmeta>prompt</x:xmpmeta>"),
        segment(0xED, b"Photoshop 3.0\0IPTC"),
        segment(0xFE, b"parameters: Steps: 20"),
        segment(0xE2, b"MPF\0multi-picture"),
    )
    assert read_metadata(original).texts

    stripped = strip_jpeg(original)
    markers = [m for m, _ in jpeg_segments(stripped)]
    assert 0xE1 not in markers and 0xED not in markers and 0xFE not in markers
    assert [p[:12] for m, p in jpeg_segments(stripped) if m == 0xE2] == [b"ICC_PROFILE\0"]
    assert read_metadata(stripped).texts == {}
    # Everything from the first SOS on is the original's, and so are the pixels.
    assert stripped[stripped.index(b"\xff\xda") :] == original[original.index(b"\xff\xda") :]
    assert pixels(stripped) == pixels(original)
    with Image.open(BytesIO(stripped)) as img:
        assert img.info.get("icc_profile") == ICC
        assert not img.getexif()


def test_jpeg_comment_between_scans_is_dropped():
    buf = BytesIO()
    noise().save(buf, "JPEG", progressive=True)
    original = buf.getvalue()
    second_sos = original.index(b"\xff\xda", original.index(b"\xff\xda") + 2)
    original = original[:second_sos] + segment(0xFE, b"hidden") + original[second_sos:]
    stripped = strip_jpeg(original)
    assert b"hidden" not in stripped
    assert pixels(stripped) == pixels(original)


def test_jpeg_keeps_jfif_without_its_thumbnail_and_the_adobe_transform():
    buf = BytesIO()
    noise().convert("CMYK").save(buf, "JPEG")  # Pillow writes an Adobe segment for CMYK
    thumb = b"JFIF\0\x01\x02\x01\x00\x48\x00\x48" + b"\x02\x01" + bytes(6)  # a 2x1 RGB thumbnail
    data = buf.getvalue()
    jfif_end = 2 + 2 + int.from_bytes(data[4:6]) if data[3] == 0xE0 else 2
    original = data[:2] + segment(0xE0, thumb) + data[jfif_end:]
    stripped = strip_jpeg(original)
    segments = jpeg_segments(stripped)
    assert (0xE0, b"JFIF\0\x01\x02\x01\x00\x48\x00\x48\0\0") in segments
    assert any(m == 0xEE and p.startswith(b"Adobe") for m, p in segments)
    assert pixels(stripped) == pixels(original)


def test_jpeg_drops_bytes_after_the_image():
    buf = BytesIO()
    noise().save(buf, "JPEG")
    original = buf.getvalue()
    stripped = strip_jpeg(original + b"\xff\xd8appended second image or trailer")
    assert stripped == strip_jpeg(original)
    assert stripped.endswith(b"\xff\xd9")


@pytest.mark.parametrize("cut", [3, 30, -2])
def test_truncated_jpeg_is_refused(cut: int):
    buf = BytesIO()
    noise().save(buf, "JPEG", exif=comfy_exif().tobytes())
    with pytest.raises(CannotStrip):
        strip_jpeg(buf.getvalue()[:cut])


def test_jpeg_exif_prefix_is_gone():
    buf = BytesIO()
    noise().save(buf, "JPEG", exif=comfy_exif().tobytes())
    assert EXIF_PREFIX in buf.getvalue()
    assert EXIF_PREFIX not in strip_metadata(buf.getvalue())


def test_other_formats_are_refused():
    buf = BytesIO()
    noise().save(buf, "WEBP", lossless=True)
    with pytest.raises(CannotStrip, match="only PNG and JPEG"):
        strip_metadata(buf.getvalue())
