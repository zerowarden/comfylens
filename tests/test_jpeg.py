from io import BytesIO

import pytest
from conftest import API_PROMPT as API
from conftest import API_TEXT
from conftest import jpeg_segment as segment
from PIL import Image

from comfylens.metadata import read_metadata
from comfylens.metadata.jpeg import XMP_PREFIX, NotJPEG, decode_user_comment, read_jpeg
from comfylens.warn import Code


def jpeg(exif: Image.Exif | None = None, *segments: bytes, size=(16, 8)) -> bytes:
    buf = BytesIO()
    # Not `if exif`: an Exif with only a sub-IFD set has len() == 0.
    exif_bytes = exif.tobytes() if exif is not None else b""
    Image.new("RGB", size, (200, 10, 10)).save(buf, "JPEG", exif=exif_bytes)
    data = buf.getvalue()
    return data[:2] + b"".join(segments) + data[2:]


def hits(data: bytes) -> list[tuple[str, str, str]]:
    return [(h.key, h.text, h.source) for h in read_jpeg(data).hits]


def test_dimensions_from_sof():
    scan = read_jpeg(jpeg(size=(24, 10)))
    assert (scan.format, scan.width, scan.height, scan.hits) == ("jpeg", 24, 10, [])


def test_probe1_ifd0_prefixed_values():
    exif = Image.Exif()
    exif[0x0110] = f"prompt:{API_TEXT}"
    exif[0x010F] = 'workflow:{"nodes": [], "links": []}'
    assert hits(jpeg(exif)) == [
        ("prompt", API_TEXT, "jpeg:exif:Model"),
        ("workflow", '{"nodes": [], "links": []}', "jpeg:exif:Make"),
    ]
    raw = read_metadata(jpeg(exif))
    assert raw.api_prompt == API
    assert raw.status == "ok"


def test_probe1_ignores_ordinary_camera_names():
    exif = Image.Exif()
    exif[0x0110] = "Canon EOS R5"
    exif[0x010F] = "Canon: Inc"
    assert hits(jpeg(exif)) == []


@pytest.mark.parametrize(
    "header,body",
    [
        (b"ASCII\0\0\0", API_TEXT.encode()),
        (b"UNICODE\0", API_TEXT.encode("utf-16-be")),
        (b"UNICODE\0", API_TEXT.encode("utf-16-le")),
        (b"\0" * 8, API_TEXT.encode()),
    ],
    ids=["ascii", "utf16be", "utf16le", "undefined"],
)
def test_probe2_user_comment(header: bytes, body: bytes):
    exif = Image.Exif()
    exif.get_ifd(0x8769)[0x9286] = header + body
    assert hits(jpeg(exif)) == [("UserComment", API_TEXT, "jpeg:exif:UserComment")]
    assert read_metadata(jpeg(exif)).api_prompt == API


def test_user_comment_prefixed_and_printable_choice():
    text = "prompt:" + API_TEXT
    assert decode_user_comment(b"UNICODE\0" + text.encode("utf-16-le")) == text
    # Not JSON: the printable decoding wins.
    assert decode_user_comment(b"UNICODE\0" + "plain words".encode("utf-16-le")) == "plain words"


def test_probe3_image_description_recovers_utf8():
    exif = Image.Exif()
    exif[0x010E] = "a café at dusk\nSteps: 20, Sampler: Euler".encode()
    assert hits(jpeg(exif)) == [
        (
            "ImageDescription",
            "a café at dusk\nSteps: 20, Sampler: Euler",
            "jpeg:exif:ImageDescription",
        )
    ]
    assert read_metadata(jpeg(exif)).kinds == {"ImageDescription": "a1111"}


def test_probe4_xmp_attribute_and_rdf_li():
    escaped = API_TEXT.replace("&", "&amp;").replace('"', "&quot;")
    packet = (
        '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="x">'
        f'<rdf:Description comfy:workflow="{{&quot;nodes&quot;: [], &quot;links&quot;: []}}">'
        f'<dc:description><rdf:Alt><rdf:li xml:lang="x-default">{escaped}</rdf:li>'
        "</rdf:Alt></dc:description></rdf:Description></rdf:RDF></x:xmpmeta>"
    )
    data = jpeg(None, segment(0xE1, XMP_PREFIX + packet.encode()))
    found = hits(data)
    assert found[0] == ("xmp", packet, "jpeg:xmp")
    assert found[1:] == [
        ("workflow", '{"nodes": [], "links": []}', "jpeg:xmp"),
        ("description", API_TEXT, "jpeg:xmp"),
    ]
    raw = read_metadata(data)
    assert raw.api_prompt == API
    assert raw.workflow == {"nodes": [], "links": []}


def test_probe5_com_segment():
    data = jpeg(None, segment(0xFE, API_TEXT.encode() + b"\0"))
    assert hits(data) == [("comment", API_TEXT, "jpeg:COM")]
    assert read_metadata(data).api_prompt == API


def test_repeated_keys_are_kept_apart():
    exif = Image.Exif()
    exif[0x0110] = f"prompt:{API_TEXT}"
    data = jpeg(exif, segment(0xFE, f"prompt:{API_TEXT}".encode()))
    raw = read_metadata(data)
    assert raw.sources == {"prompt": "jpeg:exif:Model", "prompt#2": "jpeg:COM"}
    assert raw.api_prompt == API


def test_truncated_file_returns_what_was_read():
    exif = Image.Exif()
    exif[0x0110] = f"prompt:{API_TEXT}"
    full = jpeg(exif, segment(0xFE, b"x" * 50))
    # Cut inside the segment after SOF: Pillow could not open this file at all.
    sof = full.index(b"\xff\xc0")
    after_sof = sof + 2 + int.from_bytes(full[sof + 2 : sof + 4])
    scan = read_jpeg(full[: after_sof + 6])
    assert (scan.width, scan.height) == (16, 8)
    assert [h.key for h in scan.hits] == ["prompt", "comment"]  # both precede SOF
    assert [w.code for w in scan.warnings] == [Code.TRUNCATED]


def test_truncated_before_sof_raises():
    with pytest.raises(OSError):
        read_jpeg(b"\xff\xd8" + segment(0xFE, b"hello")[:-2])


def test_non_jpeg_input_raises():
    with pytest.raises(NotJPEG):
        read_jpeg(b"\x89PNG\r\n\x1a\n")
