import zlib

import pytest
from conftest import chunk, ihdr

from comfylens.metadata.png import SIGNATURE, NotPNG, read_png
from comfylens.warn import Code

IDAT = chunk(b"IDAT", zlib.compress(b"\0" * 16))
IEND = chunk(b"IEND", b"")


def png(*chunks: bytes) -> bytes:
    return SIGNATURE + ihdr(7, 5) + b"".join(chunks) + IEND


def ztxt(key: str, text: str) -> bytes:
    return chunk(b"zTXt", key.encode("latin-1") + b"\0\0" + zlib.compress(text.encode()))


def itxt(key: str, text: str, *, compressed: bool) -> bytes:
    payload = zlib.compress(text.encode()) if compressed else text.encode()
    header = key.encode() + b"\0" + bytes([int(compressed), 0]) + b"en\0" + b"Prompt\0"
    return chunk(b"iTXt", header + payload)


def test_dimensions_and_text_chunks():
    scan = read_png(
        png(
            chunk(b"tEXt", b"prompt\0{}"),
            ztxt("workflow", '{"nodes": []}'),
            itxt("plain", "über", compressed=False),
            itxt("packed", "zipped ü", compressed=True),
        )
    )
    assert (scan.format, scan.width, scan.height) == ("png", 7, 5)
    assert [(h.key, h.text, h.source) for h in scan.hits] == [
        ("prompt", "{}", "png:tEXt"),
        ("workflow", '{"nodes": []}', "png:zTXt"),
        ("plain", "über", "png:iTXt"),
        ("packed", "zipped ü", "png:iTXt"),
    ]
    assert scan.warnings == []


def test_text_decodes_utf8_then_latin1():
    scan = read_png(
        png(
            chunk(b"tEXt", b"utf8\0" + "café ✓".encode()),
            chunk(b"tEXt", b"latin1\0caf\xe9"),
        )
    )
    assert [h.text for h in scan.hits] == ["café ✓", "café"]


def test_text_after_idat_is_read():
    scan = read_png(png(IDAT, chunk(b"tEXt", b"prompt\0late")))
    assert [h.text for h in scan.hits] == ["late"]


def test_truncated_file_returns_what_was_read():
    data = png(chunk(b"tEXt", b"prompt\0first"), IDAT, chunk(b"tEXt", b"workflow\0second"))
    cut = data[: data.index(b"workflow") + 4]
    scan = read_png(cut)
    assert [h.key for h in scan.hits] == ["prompt"]
    assert [w.code for w in scan.warnings] == [Code.TRUNCATED]


def test_missing_iend_is_truncated():
    data = png(chunk(b"tEXt", b"k\0v"))[: -len(IEND)]
    assert [w.code for w in read_png(data).warnings] == [Code.TRUNCATED]


def test_corrupt_ztxt_is_skipped():
    bad = chunk(b"zTXt", b"key\0\0not zlib data")
    scan = read_png(png(bad, chunk(b"tEXt", b"ok\0yes")))
    assert [h.key for h in scan.hits] == ["ok"]


def test_ztxt_inflation_is_capped(monkeypatch: pytest.MonkeyPatch):
    import comfylens.metadata.png as png_module

    monkeypatch.setattr(png_module, "MAX_TEXT_BYTES", 100)
    scan = read_png(png(ztxt("big", "x" * 101), ztxt("small", "x" * 100)))
    assert [h.key for h in scan.hits] == ["small"]


def test_non_png_input_raises():
    with pytest.raises(NotPNG):
        read_png(b"\xff\xd8\xff\xe0 not a png")


def test_png_without_ihdr_raises():
    with pytest.raises(ValueError, match="IHDR"):
        read_png(SIGNATURE + IEND)


def test_accepts_memoryview():
    scan = read_png(memoryview(png(chunk(b"tEXt", b"k\0v"))))
    assert scan.hits[0].text == "v"
