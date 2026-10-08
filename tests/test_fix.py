import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import golden_png, ids_by_path, server_of, txt2img_png, wait_for, write_file
from fastapi.testclient import TestClient
from PIL import Image

from comfylens.api.app import create_app
from comfylens.config import Config
from comfylens.index.indexer import Indexer
from comfylens.metadata import read_metadata

T0 = 1_790_000_000


@pytest.fixture
def library(tmp_path: Path, config: Config) -> Path:
    root = tmp_path / "library"
    write_file(root, "golden.png", golden_png(), T0)  # node 25: a LoRA connected to nothing
    write_file(root, "copy/golden.png", golden_png(), T0 + 60)
    write_file(root, "clean.png", txt2img_png(1), T0 + 120)
    Indexer(root, config, workers=1).run()
    return root


@pytest.fixture
def client(library: Path, config: Config) -> Iterator[TestClient]:
    with TestClient(create_app(library, config, index_on_start=False, web_dir=None)) as c:
        yield c


def fix(client: TestClient) -> dict:
    r = client.post("/api/index/fix")
    assert r.status_code == 202, r.text
    server = server_of(client)
    wait_for(lambda: not server.indexing)
    return client.get("/api/index/status").json()


def items(client: TestClient) -> dict[str, dict]:
    return {i["rel_path"]: i for i in client.post("/api/images/query", json={}).json()["items"]}


def pixels(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as img:
        return img.tobytes()


def documents(data: bytes) -> tuple[dict, dict]:
    """The API prompt and the workflow a file holds."""
    raw = read_metadata(data)
    assert raw.api_prompt is not None and raw.workflow is not None
    return raw.api_prompt, raw.workflow


def warnings(client: TestClient, file_id: int) -> list[str]:
    return [w["code"] for w in client.get(f"/api/images/{file_id}").json()["warnings"]]


def test_fix_rewrites_unused_loras_in_place(client: TestClient, library: Path):
    path = library / "golden.png"
    before, stat = path.read_bytes(), path.stat()
    clean = (library / "clean.png").read_bytes()
    ids = ids_by_path(client)
    hashes = {rel: item["content_hash"] for rel, item in items(client).items()}
    assert "UNUSED_LORA" in warnings(client, ids["golden.png"])
    # Tags and a saved-prompt link must survive the rewrite.
    client.post("/api/images/tags", json={"ids": [ids["golden.png"]], "add": ["fox"]})
    body = {"title": "Golden", "positive": "p", "attempts": [hashes["golden.png"]]}
    assert client.post("/api/collection/prompts", json=body).status_code == 200

    status = fix(client)
    assert status["state"] == "idle"
    assert status["last_fix"] | {"finished_at": 0} == {
        "fixed": 2,
        "first_failure": None,
        "failed": 0,
        "error": None,
        "finished_at": 0,
    }
    after = path.read_bytes()
    prompt, workflow = documents(after)
    assert set(prompt) == set(documents(before)[0]) - {"25"}
    assert 25 not in {n["id"] for n in workflow["nodes"]}
    assert read_metadata(after).tags == ["fox"]
    assert pixels(after) == pixels(before)
    assert (path.stat().st_mtime_ns, path.stat().st_mode) == (stat.st_mtime_ns, stat.st_mode)
    assert (library / "clean.png").read_bytes() == clean  # nothing to fix there

    # The catalog has re-read both copies under their new, shared hash; the link followed.
    got = items(client)
    assert got["golden.png"]["content_hash"] == got["copy/golden.png"]["content_hash"]
    assert got["golden.png"]["content_hash"] != hashes["golden.png"]
    assert got["golden.png"]["saved"] and got["golden.png"]["tags"] == ["fox"]
    assert "UNUSED_LORA" not in warnings(client, ids["golden.png"])

    # Nothing is left to fix.
    assert fix(client)["last_fix"]["fixed"] == 0
    assert path.read_bytes() == after


def test_a_file_changed_since_indexing_is_reported_and_left(client: TestClient, library: Path):
    write_file(library, "golden.png", golden_png((40, 40)), T0)  # same mtime, new size
    status = fix(client)["last_fix"]
    assert (status["fixed"], status["failed"]) == (1, 1)
    assert status["first_failure"] == "golden.png: the file changed since it was indexed"
    assert "25" in documents((library / "golden.png").read_bytes())[0]


def test_fix_refuses_while_a_run_is_under_way_and_other_sites(client: TestClient):
    server = server_of(client)
    assert server.start_index()
    assert client.post("/api/index/fix").status_code == 409
    wait_for(lambda: not server.indexing)
    r = client.post("/api/index/fix", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
