"""Turn a file's bytes into RawMetadata: dimensions plus every text payload found."""

from comfylens.metadata.blobs import classify
from comfylens.metadata.jpeg import SOI, decode_user_comment, read_jpeg
from comfylens.metadata.png import SIGNATURE, read_png
from comfylens.metadata.rewrite import CannotRewrite, replace_png_texts
from comfylens.metadata.strip import CannotStrip, strip_metadata
from comfylens.metadata.tags import CannotTag, hash_content, write_tags
from comfylens.metadata.types import Format, RawMetadata, Scan, Status, is_api_node
from comfylens.metadata.xmp import MAX_TAG_LENGTH, MAX_TAGS

__all__ = [
    "MAX_TAGS",
    "MAX_TAG_LENGTH",
    "CannotRewrite",
    "CannotStrip",
    "CannotTag",
    "Format",
    "RawMetadata",
    "Status",
    "UnsupportedFormat",
    "decode_user_comment",
    "hash_content",
    "is_api_node",
    "read_metadata",
    "replace_png_texts",
    "strip_metadata",
    "write_tags",
]


class UnsupportedFormat(ValueError):
    """Neither a PNG nor a JPEG."""


def read_metadata(data: bytes | memoryview) -> RawMetadata:
    """Detect the format from the content, scan it, and classify every text payload."""
    head = bytes(data[:8])
    if head == SIGNATURE:
        scan = read_png(data)
    elif head.startswith(SOI):
        scan = read_jpeg(data)
    else:
        raise UnsupportedFormat("not a PNG or JPEG file")
    texts, sources = _unique_keys(scan)
    found = classify(texts)
    return RawMetadata(
        format=scan.format,
        width=scan.width,
        height=scan.height,
        texts=texts,
        sources=sources,
        kinds=found.kinds,
        api_prompt_key=found.api_prompt_key,
        api_prompt=found.api_prompt,
        workflow_key=found.workflow_key,
        workflow=found.workflow,
        warnings=scan.warnings + found.warnings,
        tags=scan.tags,
    )


def _unique_keys(scan: Scan) -> tuple[dict[str, str], dict[str, str]]:
    """Keep every hit: a repeated key becomes `key#2`, `key#3`, ..."""
    texts: dict[str, str] = {}
    sources: dict[str, str] = {}
    for hit in scan.hits:
        key, n = hit.key, 1
        while key in texts:
            n += 1
            key = f"{hit.key}#{n}"
        texts[key] = hit.text
        sources[key] = hit.source
    return texts, sources
