"""Turn a file's bytes into RawMetadata: dimensions plus every text payload found."""

from comfylens.metadata.blobs import classify
from comfylens.metadata.jpeg import SOI, read_jpeg
from comfylens.metadata.png import SIGNATURE, read_png
from comfylens.metadata.types import RawMetadata, Scan

__all__ = ["RawMetadata", "UnsupportedFormat", "read_metadata"]


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
