"""The hand-mirrored type lists must match the backend models, literals and schema."""

import re
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import get_args

from pydantic import BaseModel

from comfylens.analytics import scope, timeline
from comfylens.api import schemas
from comfylens.extract.types import SamplerStage
from comfylens.metadata import types as metadata_types

ROOT = Path(__file__).parents[1]
TYPES_TS = ROOT / "frontend" / "src" / "api" / "types.ts"

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
    mirror = {"Status", "SortKey", "NumericFilterField", "Bucket", "Section"}
    assert {name: ts[name] for name in mirror} == {name: backend[name] for name in mirror}


def test_sampler_stage_fields_stay_in_sync():
    # The dataclass, the API model and the table carry the same fields; the column for
    # `index` is `stage_index`.
    stage = {f.name for f in dataclass_fields(SamplerStage)}
    assert stage == set(schemas.DetailStage.model_fields)
    schema = (ROOT / "src/comfylens/db/schema.sql").read_text()
    create = re.search(r"CREATE TABLE sampler_stages \((.*?)\);", schema, re.S)
    assert create is not None
    columns = set(re.findall(r"\b(\w+)\s+(?:INTEGER|TEXT|REAL)\b", create.group(1)))
    assert columns - {"file_id"} == (stage - {"index"}) | {"stage_index"}
