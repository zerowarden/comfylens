"""The XMP packet comfylens writes: tags as dc:subject keywords, which other photo tools show,
marked with the comfylens namespace so the packet is recognised as comfylens's own."""

import html
import re
from xml.sax.saxutils import escape

NAMESPACE = "https://github.com/zerowarden/comfylens/ns/1.0/"
NAMESPACE_BYTES = NAMESPACE.encode()  # marks a packet, or a file holding one, as comfylens's
MAX_TAG_LENGTH = 64  # characters
MAX_TAGS = 100  # per file; with MAX_TAG_LENGTH, the packet fits one JPEG segment

XML_LI = re.compile(r"<rdf:li\b[^>]*>(.*?)</rdf:li>", re.S)
_SUBJECT = re.compile(r"<dc:subject\b[^>]*>(.*?)</dc:subject>", re.S)


def build_packet(tags: list[str]) -> bytes:
    items = "".join(f"<rdf:li>{escape(t)}</rdf:li>" for t in tags)
    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/"'
        f' xmlns:comfylens="{NAMESPACE}" comfylens:version="1">'
        f"<dc:subject><rdf:Bag>{items}</rdf:Bag></dc:subject>"
        '</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
    ).encode()


def read_tags(packet: str) -> list[str] | None:
    """The tags of a comfylens packet, sorted and unique; None for any other text.

    Regexes rather than an XML parser, as for the other XMP probes: no entity is expanded.
    """
    if NAMESPACE not in packet:
        return None
    subject = _SUBJECT.search(packet)
    found = XML_LI.findall(subject.group(1)) if subject else []
    return sorted({t for raw in found if (t := html.unescape(raw).strip())})
