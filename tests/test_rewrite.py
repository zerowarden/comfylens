import zlib

import pytest
from conftest import chunk, ihdr

from comfylens.metadata.png import SIGNATURE, read_png
from comfylens.metadata.rewrite import CannotRewrite, replace_png_texts

IDAT = chunk(b"IDAT", zlib.compress(b"\0" * 16))
IEND = chunk(b"IEND", b"")


def itxt(key: bytes, text: bytes, *, compressed: bool) -> bytes:
    payload = zlib.compress(text) if compressed else text
    return chunk(b"iTXt", key + b"\0" + bytes([compressed, 0]) + b"en\0Prompt\0" + payload)


def png(*chunks: bytes) -> bytes:
    return SIGNATURE + ihdr(7, 5) + b"".join(chunks) + IDAT + IEND


@pytest.mark.parametrize(
    "make",
    [
        lambda text: chunk(b"tEXt", b"prompt\0" + text),
        lambda text: chunk(b"zTXt", b"prompt\0\0" + zlib.compress(text)),
        lambda text: itxt(b"prompt", text, compressed=False),
        lambda text: itxt(b"prompt", text, compressed=True),
    ],
    ids=["tEXt", "zTXt", "iTXt", "iTXt-compressed"],
)
def test_a_text_is_replaced_in_a_chunk_of_the_same_kind(make):
    other = chunk(b"tEXt", b"workflow\0{}")
    data = png(make(b'{"old": 1}'), other) + b"trailing"
    new = replace_png_texts(data, {'{"old": 1}': '{"new": 22}'})
    assert new == png(make(b'{"new": 22}'), other) + b"trailing"
    (hit, _) = read_png(new).hits
    assert (hit.key, hit.text) == ("prompt", '{"new": 22}')


def test_refuses_what_it_cannot_rewrite():
    with pytest.raises(CannotRewrite, match="only PNG"):
        replace_png_texts(b"\xff\xd8\xff", {"a": "b"})
    with pytest.raises(CannotRewrite, match="not found"):
        replace_png_texts(png(chunk(b"tEXt", b"k\0v")), {"other": "b"})
    with pytest.raises(CannotRewrite, match="PNG ends"):
        replace_png_texts(png(chunk(b"tEXt", b"k\0v"))[:-20], {"v": "b"})
