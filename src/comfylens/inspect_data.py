"""The `inspect` document: one file's analysis as plain data (also the golden-test format)."""

from dataclasses import asdict
from typing import Any

from comfylens.extract import Analysis, size_facts, unregistered
from comfylens.version import EXTRACTOR_VERSION, SCHEMA_VERSION


def to_dict(a: Analysis, output_classes: frozenset[str]) -> dict[str, Any]:
    """The `inspect --json` document; also the golden-test format."""
    doc: dict[str, Any] = {
        "versions": {"extractor": EXTRACTOR_VERSION, "schema": SCHEMA_VERSION},
        "status": a.status,
        "error": a.error,
    }
    if a.raw is not None:
        raw = a.raw
        doc["file"] = {
            "format": raw.format,
            "width": raw.width,
            "height": raw.height,
            **size_facts(raw.width, raw.height),
        }
        doc["raw_keys"] = [
            {"key": k, "source": raw.sources[k], "kind": raw.kinds[k], "chars": len(v)}
            for k, v in raw.texts.items()
        ]
    if a.graph is not None and a.reach is not None:
        graph, reach = a.graph, a.reach
        ordered = reach.order + [n for n in graph.nodes if n not in reach.reachable]
        doc["outputs"] = reach.outputs
        doc["nodes"] = [
            {
                "id": n,
                "class_type": graph.nodes[n].class_type,
                "title": graph.nodes[n].title,
                "reachable": n in reach.reachable,
            }
            for n in ordered
        ]
        doc["unregistered"] = unregistered(
            {graph.nodes[n].class_type for n in reach.reachable}, output_classes
        )
    if a.extraction is not None:
        extraction = asdict(a.extraction)
        del extraction["warnings"]
        extraction["text_encoder"] = a.extraction.text_encoder
        doc["extraction"] = extraction
    doc["warnings"] = [asdict(w) for w in a.warnings]
    return doc
