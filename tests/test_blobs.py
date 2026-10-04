import json

import pytest

from comfylens.metadata.blobs import classify, shape_of
from comfylens.warn import Code

API = {"1": {"class_type": "KSampler", "inputs": {}}, "2": {"class_type": "X", "inputs": {}}}
WORKFLOW = {"nodes": [], "links": [], "version": 0.4}


def test_api_prompt_workflow_and_other():
    found = classify(
        {"prompt": json.dumps(API), "workflow": json.dumps(WORKFLOW), "other": '{"a": 1}'}
    )
    assert found.kinds == {"prompt": "api_prompt", "workflow": "workflow", "other": "json"}
    assert found.api_prompt == API
    assert found.workflow == WORKFLOW
    assert found.warnings == []


def test_api_prompt_needs_80_percent_nodes():
    four_of_five = {**API, "3": API["1"], "4": API["1"], "extra": 1}
    three_of_four = {**API, "3": API["1"], "extra": 1}
    assert shape_of(four_of_five) == "api_prompt"
    assert shape_of(three_of_four) == "json"
    assert shape_of({}) == "json"


def test_key_and_shape_mismatch_trusts_shape():
    found = classify({"prompt": json.dumps(WORKFLOW), "workflow": json.dumps(API)})
    assert found.api_prompt == API
    assert found.workflow == WORKFLOW
    assert [w.code for w in found.warnings] == [Code.METADATA_KEY_MISMATCH] * 2


def test_agreeing_key_is_preferred():
    other_api = {"9": {"class_type": "Other", "inputs": {}}}
    found = classify({"UserComment": json.dumps(other_api), "prompt": json.dumps(API)})
    assert found.api_prompt == API
    assert found.warnings == []


def test_nan_and_infinity_parse():
    text = '{"1": {"class_type": "KSampler", "inputs": {"cfg": NaN, "x": Infinity}}}'
    found = classify({"prompt": text})
    cfg = found.api_prompt["1"]["inputs"]["cfg"]  # type: ignore[index]
    assert cfg != cfg  # NaN


def test_invalid_json_is_text():
    found = classify({"comment": "{not json"})
    assert found.kinds == {"comment": "text"}
    assert found.api_prompt is None


def test_a1111_parameters():
    text = "a cat\nNegative prompt: dog\nSteps: 20, Sampler: Euler a, CFG scale: 7"
    found = classify({"parameters": text, "UserComment": text})
    assert found.kinds == {"parameters": "a1111", "UserComment": "a1111"}
    assert [w.code for w in found.warnings] == [Code.UNSUPPORTED_FORMAT]


def test_oversized_blob_is_skipped(monkeypatch: pytest.MonkeyPatch):
    import comfylens.metadata.blobs as blobs

    monkeypatch.setattr(blobs, "MAX_TEXT_BYTES", 10)
    found = classify({"prompt": json.dumps(API)})
    assert found.kinds["prompt"] == "oversized"
    assert found.api_prompt is None
