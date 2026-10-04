"""Warning codes attached to files during reading and extraction."""

from dataclasses import dataclass
from enum import StrEnum


class Code(StrEnum):
    TRUNCATED = "TRUNCATED"
    METADATA_KEY_MISMATCH = "METADATA_KEY_MISMATCH"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    UNSUPPORTED_SUBGRAPH = "UNSUPPORTED_SUBGRAPH"
    NO_OUTPUT_NODE = "NO_OUTPUT_NODE"
    MULTIPLE_OUTPUT_BRANCHES = "MULTIPLE_OUTPUT_BRANCHES"
    GRAPH_CYCLE = "GRAPH_CYCLE"
    NO_SAMPLER = "NO_SAMPLER"
    UNKNOWN_MODEL_PATCH = "UNKNOWN_MODEL_PATCH"
    MODEL_CHAIN_BROKEN = "MODEL_CHAIN_BROKEN"
    UNUSED_LORA = "UNUSED_LORA"
    MULTIPLE_PROMPT_SOURCES = "MULTIPLE_PROMPT_SOURCES"
    HEURISTIC_PROMPT = "HEURISTIC_PROMPT"
    PROMPT_UNRESOLVED = "PROMPT_UNRESOLVED"
    # The encoded prompt was written at run time by an LLM node (TextGenerate); only its
    # input is in the metadata, and that input is what the prompt fields hold.
    GENERATED_PROMPT = "GENERATED_PROMPT"
    THUMBNAIL_FAILED = "THUMBNAIL_FAILED"
    TIMESTAMP_SUSPECT = "TIMESTAMP_SUSPECT"


@dataclass(frozen=True, slots=True)
class Warn:
    code: Code
    node_id: str | None
    message: str


# Codes produced by graph analysis and extraction. Re-extraction from raw JSON replaces exactly
# these; reading (TRUNCATED, ...), thumbnail and timestamp warnings stay.
EXTRACTION_CODES = frozenset(
    {
        Code.UNSUPPORTED_SUBGRAPH,
        Code.NO_OUTPUT_NODE,
        Code.MULTIPLE_OUTPUT_BRANCHES,
        Code.GRAPH_CYCLE,
        Code.NO_SAMPLER,
        Code.UNKNOWN_MODEL_PATCH,
        Code.MODEL_CHAIN_BROKEN,
        Code.UNUSED_LORA,
        Code.MULTIPLE_PROMPT_SOURCES,
        Code.HEURISTIC_PROMPT,
        Code.PROMPT_UNRESOLVED,
        Code.GENERATED_PROMPT,
    }
)


# Codes produced while reading a file: metadata, thumbnail and timestamp stages. Re-extraction
# from raw JSON never replaces these.
READ_CODES = frozenset(
    {
        Code.TRUNCATED,
        Code.METADATA_KEY_MISMATCH,
        Code.UNSUPPORTED_FORMAT,
        Code.THUMBNAIL_FAILED,
        Code.TIMESTAMP_SUSPECT,
    }
)


# Notes that change no extracted value: an unused LoRA, a node the model passes through, an
# image made without a sampler. They are kept and shown, but do not mark a file as having
# warnings (the grid badge and the has_warnings filter).
INFORMATIONAL_CODES = frozenset(
    {Code.UNUSED_LORA, Code.UNKNOWN_MODEL_PATCH, Code.NO_SAMPLER, Code.GENERATED_PROMPT}
)
