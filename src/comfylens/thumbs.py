"""WebP thumbnails in the cache directory, keyed by content hash."""

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

from comfylens.fileio import write_atomic


def make_thumbnail(data: bytes, target: Path, long_edge: int, quality: int) -> bool:
    """Write `target` unless it exists. Returns whether a file was written; raises on failure."""
    if target.exists():
        return False
    with Image.open(BytesIO(data)) as opened:
        if opened.format == "JPEG":
            opened.draft("RGB", (long_edge, long_edge))  # decode at reduced scale
        img = ImageOps.exif_transpose(opened)
    img = _webp_mode(img)
    img.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)

    # Write beside the target, then rename into place: readers never see a partial file,
    # and two workers thumbnailing identical files cannot corrupt each other.
    write_atomic(target, lambda f: img.save(f, "WEBP", quality=quality, method=4))
    return True


def _webp_mode(img: Image.Image) -> Image.Image:
    """Keep alpha; convert palette, 16-bit and other modes to RGBA or RGB."""
    if img.mode in ("I;16", "I;16B", "I;16L", "I"):
        img = img.point(lambda v: v / 256).convert("L")  # 16-bit grey -> 8-bit
    has_alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
    wanted = "RGBA" if has_alpha else "RGB"
    return img if img.mode == wanted else img.convert(wanted)
