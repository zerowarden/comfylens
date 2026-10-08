import shutil
import subprocess
from io import BytesIO
from pathlib import Path

import pytest
import xxhash
from conftest import API_PROMPT, API_TEXT, chunk, png_with_text
from conftest import jpeg_segment as segment
from PIL import Image

from comfylens.metadata import read_metadata
from comfylens.metadata.jpeg import XMP_PREFIX
from comfylens.metadata.png import SIGNATURE, XMP_KEYWORD
from comfylens.metadata.tags import CannotTag, hash_content, write_tags
from comfylens.metadata.xmp import MAX_TAGS, NAMESPACE, read_tags

FOREIGN_XMP = '<x:xmpmeta xmlns:x="adobe:ns:meta/"><dc:subject>other</dc:subject></x:xmpmeta>'


def jpeg(*segments: bytes) -> bytes:
    """A JPEG with an Exif segment, then `segments` right after SOI."""
    buf = BytesIO()
    exif = Image.Exif()
    exif[0x0110] = f"prompt:{API_TEXT}"
    Image.new("RGB", (16, 8), (200, 10, 10)).save(buf, "JPEG", exif=exif.tobytes())
    data = buf.getvalue()
    return data[:2] + b"".join(segments) + data[2:]


def png() -> bytes:
    return png_with_text({"prompt": API_PROMPT})


def pixels(data: bytes) -> bytes:
    with Image.open(BytesIO(data)) as img:
        return img.tobytes()


@pytest.mark.parametrize("make", [png, jpeg], ids=["png", "jpeg"])
def test_round_trip_keeps_everything_else(make):
    original = make()
    tagged = write_tags(original, ["fox", 'a & <b> "c"', "ünï ✓"])
    raw = read_metadata(tagged)
    assert sorted(raw.tags) == ['a & <b> "c"', "fox", "ünï ✓"]
    assert raw.api_prompt == API_PROMPT  # the generation metadata is still read
    assert all(NAMESPACE not in text for text in raw.texts.values())  # the packet is no hit
    assert pixels(tagged) == pixels(original)
    # Taking the tags out gives back the exact file, so its identity never changes.
    assert write_tags(tagged, []) == original
    assert hash_content(tagged) == hash_content(original) == xxhash.xxh3_128_hexdigest(original)


@pytest.mark.parametrize("make", [png, jpeg], ids=["png", "jpeg"])
def test_retagging_replaces_the_packet(make):
    retagged = write_tags(write_tags(make(), ["fox"]), ["owl"])
    assert read_metadata(retagged).tags == ["owl"]
    assert retagged.count(NAMESPACE.encode()) == 1
    assert write_tags(retagged, []) == make()


def test_png_packet_follows_ihdr_uncompressed():
    tagged = write_tags(png(), ["fox"])
    ihdr_end = len(SIGNATURE) + 8 + 13 + 4
    assert tagged[ihdr_end + 4 : ihdr_end + 8] == b"iTXt"
    assert tagged[ihdr_end + 8 :].startswith(XMP_KEYWORD.encode() + b"\0\0\0\0\0<?xpacket")


def test_jpeg_packet_follows_the_leading_app_segments():
    original = jpeg(segment(0xFE, b"a comment"))
    tagged = write_tags(original, ["fox"])
    exif = original.index(b"Exif\0\0") - 4
    exif_end = exif + 2 + int.from_bytes(original[exif + 2 : exif + 4])
    assert tagged[:exif_end] == original[:exif_end]  # SOI, the comment, JFIF and Exif
    assert tagged[exif_end : exif_end + 2] == b"\xff\xe1"
    assert tagged[exif_end + 4 :].startswith(XMP_PREFIX)


@pytest.mark.parametrize(
    "data",
    [
        png()[:-12]
        + chunk(b"iTXt", XMP_KEYWORD.encode() + b"\0\0\0\0\0" + FOREIGN_XMP.encode())
        + png()[-12:],
        jpeg(segment(0xE1, XMP_PREFIX + FOREIGN_XMP.encode())),
    ],
    ids=["png", "jpeg"],
)
def test_another_programs_xmp_is_never_replaced(data: bytes):
    with pytest.raises(CannotTag, match="another program"):
        write_tags(data, ["fox"])
    assert write_tags(data, []) == data  # nothing of ours to remove; theirs stays
    assert read_metadata(data).tags == []


@pytest.mark.parametrize("make", [png, jpeg], ids=["png", "jpeg"])
def test_bytes_after_the_image_end_are_kept(make):
    original = make() + b"trailing"
    tagged = write_tags(original, ["fox"])
    assert tagged.endswith(b"trailing") and write_tags(tagged, []) == original


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"GIF89a", "only PNG and JPEG"),
        (png()[:40], "PNG ends"),
        (jpeg()[:3], "JPEG"),
    ],
)
def test_unsplicable_files_are_refused(data: bytes, message: str):
    with pytest.raises(CannotTag, match=message):
        write_tags(data, ["fox"])


def test_damaged_file_with_a_packet_is_hashed_as_it_is():
    data = write_tags(png(), ["fox"])[:-30]  # IEND and the end of IDAT are gone
    assert hash_content(data) == xxhash.xxh3_128_hexdigest(data)


def test_tag_count_is_capped():
    write_tags(jpeg(), [f"t{i}" for i in range(MAX_TAGS)])
    with pytest.raises(CannotTag, match=f"at most {MAX_TAGS}"):
        write_tags(png(), [f"t{i}" for i in range(MAX_TAGS + 1)])


def test_read_tags():
    assert read_tags(FOREIGN_XMP) is None
    packet = (
        f'<x:xmpmeta xmlns:comfylens="{NAMESPACE}"><dc:subject><rdf:Bag>'
        "<rdf:li> owl </rdf:li><rdf:li>fox</rdf:li><rdf:li>owl</rdf:li><rdf:li> </rdf:li>"
        "</rdf:Bag></dc:subject><dc:title><rdf:Alt><rdf:li>not a tag</rdf:li></rdf:Alt>"
        "</dc:title></x:xmpmeta>"
    )
    assert read_tags(packet) == ["fox", "owl"]
    assert read_tags(f'<x:xmpmeta xmlns:comfylens="{NAMESPACE}"/>') == []


@pytest.mark.skipif(shutil.which("exiftool") is None, reason="exiftool is not installed")
@pytest.mark.parametrize("suffix", ["png", "jpg"])
def test_other_tools_read_the_tags_as_keywords(tmp_path: Path, suffix: str):
    path = tmp_path / f"tagged.{suffix}"
    original = png() if suffix == "png" else jpeg()

    def exiftool(*args: str) -> str:
        return subprocess.run(
            ["exiftool", *args, str(path)], check=True, capture_output=True, text=True
        ).stdout

    path.write_bytes(original)
    untagged = exiftool("-s3", "-validate", "-warning")
    path.write_bytes(write_tags(original, ["fox", "red & blue"]))
    assert exiftool("-s3", "-sep", "|", "-XMP-dc:Subject") == "fox|red & blue\n"
    assert exiftool("-s3", "-validate", "-warning") == untagged  # no new warning
    # A tool that edits the keywords keeps the packet comfylens's own.
    exiftool("-q", "-overwrite_original", "-XMP-dc:Subject+=owl")
    assert read_metadata(path.read_bytes()).tags == ["fox", "owl", "red & blue"]
