"""The hand-mirrored type lists must match the backend models, literals and schema."""

import re
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import get_args

from pydantic import BaseModel

from comfylens.analytics import scope, timeline
from comfylens.api import routes_images, schemas
from comfylens.db import read as db_read
from comfylens.extract.types import LoraUse, SamplerStage
from comfylens.index import write as index_write
from comfylens.metadata import types as metadata_types

ROOT = Path(__file__).parents[1]
TYPES_TS = ROOT / "frontend" / "src" / "api" / "types.ts"
SCHEMA_SQL = (ROOT / "src/comfylens/db/schema.sql").read_text("utf-8")

_INTERFACE = re.compile(r"export interface (\w+)(?: extends (\w+))? \{(.*?)\n\}", re.S)
_ALIAS = re.compile(r"export type (\w+) = ([^;]+);")
_FIELD = re.compile(r"^\s*(\w+):")


def _ts_interfaces(text: str) -> dict[str, set[str]]:
    raw = {name: (parent, body) for name, parent, body in _INTERFACE.findall(text)}

    def fields(name: str) -> set[str]:
        parent, body = raw[name]
        own = {m.group(1) for line in body.splitlines() if (m := _FIELD.match(line))}
        return own | (fields(parent) if parent else set())

    return {name: fields(name) for name in raw}


def _ts_literals(text: str) -> dict[str, set[str]]:
    return {name: set(re.findall(r'"([^"]+)"', body)) for name, body in _ALIAS.findall(text)}


def _backend_models() -> dict[str, type[BaseModel]]:
    found: dict[str, type[BaseModel]] = {}
    for module in (schemas, scope):
        for name in dir(module):
            value = getattr(module, name)
            if isinstance(value, type) and issubclass(value, BaseModel) and value is not BaseModel:
                found[name] = value
    return found


def _backend_literals() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for module in (schemas, scope, timeline, metadata_types):
        for name in dir(module):
            value = getattr(module, name)
            if get_args(value) and all(isinstance(a, str) for a in get_args(value)):
                found[name] = set(get_args(value))
    return found


def test_every_interface_matches_a_model_field_for_field():
    ts = _ts_interfaces(TYPES_TS.read_text("utf-8"))
    backend = {name: set(model.model_fields) for name, model in _backend_models().items()}
    assert set(ts) == set(backend)
    assert {name: fields for name, fields in ts.items() if fields != backend[name]} == {}


def test_mirrored_literal_unions_match():
    ts = _ts_literals(TYPES_TS.read_text("utf-8"))
    backend = _backend_literals()
    mirror = {
        "Status",
        "SortKey",
        "NumericFilterField",
        "Bucket",
        "Section",
        "ImageRole",
        "DraftMetadata",
    }
    assert {name: ts[name] for name in mirror} == {name: backend[name] for name in mirror}


def test_trash_batch_matches_the_frontend():
    # A smaller server limit would turn every large trash from the UI into 400 errors.
    files_ts = (ROOT / "frontend/src/lib/files.ts").read_text("utf-8")
    match = re.search(r"export const TRASH_BATCH = (\d+);", files_ts)
    assert match is not None
    assert int(match.group(1)) == schemas.TRASH_BATCH


def _table_columns(schema: str) -> dict[str, set[str]]:
    schema = re.sub(r"--[^\n]*", "", schema)
    return {
        name: set(re.findall(r"\b(\w+)\s+(?:INTEGER|TEXT|REAL)\b", body))
        for name, body in re.findall(r"CREATE TABLE (\w+) \((.*?)\);", schema, re.S)
    }


def test_sampler_stage_fields_stay_in_sync():
    # The dataclass, the API model and the table carry the same fields; the column for
    # `index` is `stage_index`.
    stage = {f.name for f in dataclass_fields(SamplerStage)}
    assert stage == set(schemas.DetailStage.model_fields)
    columns = _table_columns(SCHEMA_SQL)["sampler_stages"]
    assert columns - {"file_id"} == (stage - {"index"}) | {"stage_index"}


def test_insert_columns_match_dataclasses_and_the_schema():
    # The writer derives each INSERT from these tuples, so a mismatch here means stored
    # values no longer line up with their columns.
    tables = _table_columns(SCHEMA_SQL)
    stage = ({f.name for f in dataclass_fields(SamplerStage)} - {"index"}) | {"stage_index"}
    assert set(index_write.SAMPLER_STAGE_COLUMNS) == stage
    assert set(index_write.LORA_COLUMNS) == {f.name for f in dataclass_fields(LoraUse)}
    assert set(index_write.GENERATIONS_COLUMNS) == tables["generations"] - {"file_id"}
    assert set(index_write.FILES_COLUMNS) == tables["files"] - {
        "id",
        "generated_at",
        "timestamp_suspect",
    }


def test_prompt_settings_shapes_match_the_shared_model():
    # Drafts, the A1111 parser and empty settings all re-spell the PromptSettings keys.
    from comfylens.collection import a1111, drafts
    from comfylens.collection.models import (
        PROMPT_SETTING_KEYS,
        SAVED_LORA_KEYS,
        PromptSettings,
        SavedLora,
    )
    from comfylens.extract.types import Extraction

    assert set(PROMPT_SETTING_KEYS) == set(PromptSettings.model_fields)
    assert set(SAVED_LORA_KEYS) == set(SavedLora.model_fields)
    assert set(drafts.empty_settings()) == set(PROMPT_SETTING_KEYS)
    parsed = a1111.parse_parameters("a fox\nSteps: 20, Seed: 1")
    assert parsed is not None
    assert set(parsed["settings"]) == set(PROMPT_SETTING_KEYS)
    assert set(a1111.loras("x <lora:fox:0.8>")[0]) == set(SAVED_LORA_KEYS)
    empty = Extraction(
        stages=[],
        model_family="unknown",
        base_model=None,
        text_encoders=[],
        clip_type=None,
        vae=None,
        loras=[],
        positive_prompt=None,
        negative_prompt=None,
        guidance=None,
        shift=None,
        latent_source=None,
        batch_size=None,
        input_images=[],
        generic_inputs=[],
        lora_stack_key="(none)",
        config_key="",
        generation_key="",
        warnings=[],
    )
    assert set(drafts.settings_of(empty)) == set(PROMPT_SETTING_KEYS)


def test_read_schemas_select_catalog_columns():
    # db/read.py re-lists the columns it reads; a typo or a renamed column would silently
    # produce an empty or misaligned frame.
    tables = _table_columns(SCHEMA_SQL)
    assert set(db_read.FILES_SCHEMA) <= tables["files"]
    assert set(db_read.GENERATIONS_SCHEMA) <= tables["generations"]
    assert set(db_read.LORAS_SCHEMA) <= tables["loras"]


def test_every_sort_key_has_a_column():
    assert set(routes_images._SORT_COLUMNS) == set(get_args(schemas.SortKey))
