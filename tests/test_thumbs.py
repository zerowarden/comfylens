import io
from pathlib import Path

import pytest
from PIL import Image

from comfylens.index.thumbs import make_thumbnail


def encode(img: Image.Image, fmt: str, **kwargs) -> bytes:
    buf = io.BytesIO()
    img.save(buf, fmt, **kwargs)
    return buf.getvalue()


def thumb(tmp_path: Path, data: bytes, long_edge: int = 512) -> Image.Image:
    target = tmp_path / "ab" / "thumb.webp"
    assert make_thumbnail(data, target, long_edge, 82)
    assert [p.name for p in target.parent.iterdir()] == ["thumb.webp"]  # no temp files left
    img = Image.open(target)
    assert img.format == "WEBP"
    return img


def test_long_edge_and_aspect(tmp_path: Path):
    img = thumb(tmp_path, encode(Image.new("RGB", (896, 1632), "red"), "PNG"))
    assert img.size == (281, 512)
    assert img.mode == "RGB"


def test_small_images_are_not_enlarged(tmp_path: Path):
    assert thumb(tmp_path, encode(Image.new("RGB", (64, 32)), "PNG")).size == (64, 32)


def test_alpha_is_kept(tmp_path: Path):
    img = thumb(tmp_path, encode(Image.new("RGBA", (40, 40), (0, 0, 0, 0)), "PNG"))
    assert img.mode == "RGBA"
    assert img.getpixel((5, 5))[3] == 0  # type: ignore[index]


def test_palette_with_transparency(tmp_path: Path):
    palette = Image.new("P", (20, 20), 0)
    assert thumb(tmp_path, encode(palette, "PNG", transparency=0)).mode == "RGBA"
    assert thumb(tmp_path / "2", encode(Image.new("P", (20, 20)), "PNG")).mode == "RGB"


def test_16_bit_greyscale(tmp_path: Path):
    grey = Image.new("I;16", (20, 20), 65535)
    img = thumb(tmp_path, encode(grey, "PNG"))
    assert img.getpixel((1, 1))[0] > 240  # type: ignore[index]  # white, not clipped noise


def test_jpeg_exif_orientation(tmp_path: Path):
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees clockwise for display
    data = encode(Image.new("RGB", (60, 20)), "JPEG", exif=exif.tobytes())
    assert thumb(tmp_path, data).size == (20, 60)


def test_existing_target_is_kept(tmp_path: Path):
    target = tmp_path / "t.webp"
    target.write_bytes(b"old")
    assert not make_thumbnail(encode(Image.new("RGB", (8, 8)), "PNG"), target, 512, 82)
    assert target.read_bytes() == b"old"


def test_failure_raises_and_leaves_nothing(tmp_path: Path):
    with pytest.raises(OSError):
        make_thumbnail(b"not an image", tmp_path / "x" / "t.webp", 512, 82)
    assert not (tmp_path / "x" / "t.webp").exists()
