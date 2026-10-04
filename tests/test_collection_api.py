import io
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import golden_png, ids_by_path, png_with_text, server_of, wait_for, write_file
from fastapi.testclient import TestClient
from graph_builder import basic_txt2img
from PIL import Image

from comfylens.api.app import create_app
from comfylens.collection import drafts
from comfylens.config import Config
from comfylens.index.indexer import Indexer
from comfylens.paths import catalog_path, collection_dir, thumbs_dir

T0 = 1_790_000_000
EVIL = {"Origin": "http://evil.example"}


def flux(seed: int, prompt: str, lora: float | None = None) -> bytes:
    g = basic_txt2img()
    g.prompt["7"]["inputs"]["seed"] = seed
    g.prompt["4"]["inputs"]["text"] = prompt
    if lora is not None:
        g.node(
            "20", "LoraLoaderModelOnly", lora_name="fox.safetensors", strength_model=lora,
            model=("1", 0),
        )  # fmt: skip
        g.prompt["7"]["inputs"]["model"] = ["20", 0]
    return png_with_text({"prompt": g.prompt}, (16, 24))


@pytest.fixture
def library(tmp_path: Path, config: Config) -> Path:
    root = tmp_path / "library"
    write_file(root, "golden.png", golden_png(), T0)
    write_file(root, "copy/golden.png", golden_png(), T0 + 60)
    write_file(root, "fox1.png", flux(1, "a red fox in the snow", 0.8), T0 + 100)
    write_file(root, "fox1b.png", flux(5, "a red fox  in the snow"), T0 + 200)  # same prompt
    write_file(root, "fox2.png", flux(2, "a red fox at night"), T0 + 300)
    write_file(root, "owl.png", flux(4, "an owl on a branch"), T0 + 400)
    write_file(root, "plain.png", png_with_text({}), T0 + 500)
    Indexer(root, config, workers=1).run()
    return root


def make_client(library: Path, config: Config) -> TestClient:
    return TestClient(create_app(library, config, index_on_start=False, web_dir=None))


@pytest.fixture
def client(library: Path, config: Config) -> Iterator[TestClient]:
    with make_client(library, config) as c:
        wait_for(lambda: c.get("/api/library").json()["prompts_ready"])
        yield c


def saved_paths(client: TestClient, filters: dict[str, Any] | None = None) -> set[str]:
    items = client.post("/api/images/query", json={"filters": filters or {}, "limit": 100}).json()[
        "items"
    ]
    if filters:
        return {i["rel_path"] for i in items}
    return {i["rel_path"] for i in items if i["saved"]}


def save_from_library(client: TestClient, file_id: int, **fields: Any) -> dict[str, Any]:
    draft = client.post(f"/api/collection/drafts/from-image/{file_id}", json={}).json()
    body = {
        "title": draft["title"],
        "positive": draft["positive"],
        "negative": draft["negative"],
        "model_family": draft["model_family"],
        "settings": draft["settings"],
        "references": [draft["original"]["content_hash"]],
        **fields,
    }
    response = client.post("/api/collection/prompts", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_save_from_library(client: TestClient, library: Path):
    ids = ids_by_path(client)
    fox1 = library / "fox1.png"
    before = (fox1.read_bytes(), fox1.stat().st_mtime_ns)

    draft = client.post(f"/api/collection/drafts/from-image/{ids['fox1.png']}", json={}).json()
    assert draft["metadata"] == "comfyui"
    assert draft["positive"] == "a red fox in the snow"
    assert draft["settings"]["loras"] == [
        {"name": "fox", "strength_model": 0.8, "strength_clip": None}
    ]
    assert draft["original"]["library_ids"] == [ids["fox1.png"]]

    saved = save_from_library(client, ids["fox1.png"], tags=["Foxes"])
    assert saved["tags"] == ["foxes"]
    assert [r["library_ids"] for r in saved["references"]] == [[ids["fox1.png"]]]
    assert (fox1.read_bytes(), fox1.stat().st_mtime_ns) == before  # the library is never written
    assert list((collection_dir() / "originals").rglob("*.png"))
    assert saved_paths(client) == {"fox1.png"}

    original = client.get(f"/api/collection/originals/{draft['original']['content_hash']}")
    assert original.status_code == 200 and original.content == fox1.read_bytes()
    raw = client.get(f"/api/collection/originals/{draft['original']['content_hash']}/raw").json()
    assert raw["prompt"]["7"]["class_type"] == "KSampler" and raw["workflow"] is None


def test_identical_copies_are_both_saved(client: TestClient):
    ids = ids_by_path(client)
    save_from_library(client, ids["golden.png"])
    assert saved_paths(client) == {"golden.png", "copy/golden.png"}


def test_link_attempts(client: TestClient):
    ids = ids_by_path(client)
    prompt = save_from_library(client, ids["fox1.png"])
    url = f"/api/collection/prompts/{prompt['id']}/attempts"
    linked = client.post(url, json={"file_ids": [ids["fox2.png"], ids["owl.png"], 999_999]})
    assert linked.json() == {"added": 2, "skipped": [999_999]}
    assert client.post(url, json={"file_ids": [ids["fox2.png"]]}).json()["added"] == 0
    assert saved_paths(client) == {"fox1.png", "fox2.png", "owl.png"}

    got = client.get(f"/api/collection/prompts/{prompt['id']}").json()
    assert [a["library_ids"] for a in got["attempts"]] == [[ids["fox2.png"]], [ids["owl.png"]]]
    owl_hash = got["attempts"][1]["content_hash"]
    after = client.post(f"{url}/remove", json={"hashes": [owl_hash]}).json()
    assert len(after["attempts"]) == 1
    assert (
        client.post("/api/collection/prompts/999/attempts", json={"file_ids": [1]}).status_code
        == 404
    )


def test_saved_prompt_filter_and_counts(client: TestClient):
    ids = ids_by_path(client)
    prompt = save_from_library(client, ids["fox1.png"])
    client.post(
        f"/api/collection/prompts/{prompt['id']}/attempts", json={"file_ids": [ids["owl.png"]]}
    )
    # Linked (fox1, owl) plus the same prompt with other whitespace (fox1b).
    expected = {"fox1.png", "fox1b.png", "owl.png"}
    assert saved_paths(client, {"saved_prompt": prompt["id"]}) == expected
    listed = client.get("/api/collection/prompts").json()
    assert listed["items"][0]["library_count"] == 3
    assert client.get(f"/api/collection/prompts/{prompt['id']}").json()["library_count"] == 3
    stats = client.post("/api/stats", json={"filters": {"saved_prompt": prompt["id"]}}).json()
    assert stats["scope"]["scope_size"] == 3
    timeline = client.post("/api/timeline", json={"filters": {"saved": True}}).json()
    assert sum(sum(counts) for counts in timeline["series"].values()) == 2

    assert saved_paths(client, {"saved": True}) == {"fox1.png", "owl.png"}
    assert "fox1.png" not in saved_paths(client, {"saved": False})
    assert saved_paths(client, {"saved_prompt": 999}) == set()


def test_saved_prompt_filter_before_prompt_frames(client: TestClient):
    ids = ids_by_path(client)
    prompt = save_from_library(client, ids["fox1.png"])
    server_of(client).store.current.prompts = None  # as during warm-up
    assert saved_paths(client, {"saved_prompt": prompt["id"]}) == {"fox1.png", "fox1b.png"}
    assert client.get("/api/collection/prompts").json()["items"][0]["library_count"] is None


def test_for_image(client: TestClient):
    ids = ids_by_path(client)
    prompt = save_from_library(client, ids["fox1.png"], title="Snow fox")
    same = client.get(f"/api/collection/for-image/{ids['fox1b.png']}").json()
    assert same == {
        "linked": [],
        "matching": [{"id": prompt["id"], "title": "Snow fox", "role": None}],
    }
    own = client.get(f"/api/collection/for-image/{ids['fox1.png']}").json()
    assert own == {
        "linked": [{"id": prompt["id"], "title": "Snow fox", "role": "reference"}],
        "matching": [],
    }
    assert client.get(f"/api/collection/for-image/{ids['plain.png']}").json() == {
        "linked": [],
        "matching": [],
    }
    assert client.get("/api/collection/for-image/abc").status_code == 404


def test_upload(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    headers = {"Content-Type": "image/png"}
    draft = client.post("/api/collection/drafts/upload", content=golden_png(), headers=headers)
    assert draft.status_code == 200
    assert draft.json()["model_family"] == "qwen-image-2.1"
    # The library holds the same bytes twice.
    assert len(draft.json()["original"]["library_ids"]) == 2

    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, "WEBP")
    webp = client.post("/api/collection/drafts/upload", content=buf.getvalue())
    assert webp.json()["metadata"] == "none" and webp.json()["original"]["format"] == "webp"

    bad = client.post("/api/collection/drafts/upload", content=b"xx")
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "unsupported_image"
    monkeypatch.setattr(drafts, "MAX_UPLOAD_BYTES", 10)
    monkeypatch.setattr("comfylens.api.routes_collection.MAX_UPLOAD_BYTES", 10)
    big = client.post("/api/collection/drafts/upload", content=golden_png())
    assert big.status_code == 413 and big.json()["error"]["code"] == "too_large"


def test_text_draft_and_manual_prompt(client: TestClient):
    draft = client.post("/api/collection/drafts/text", json={"positive": "a cat. sleeping"}).json()
    assert draft["original"] is None and draft["title"] == "a cat"
    created = client.post(
        "/api/collection/prompts", json={"title": "Cat", "positive": "a cat", "attempts": []}
    )
    assert created.status_code == 200 and created.json()["references"] == []


def test_validation_errors(client: TestClient):
    unknown = client.post(
        "/api/collection/prompts", json={"title": "t", "positive": "", "references": ["a" * 32]}
    )
    assert unknown.status_code == 400 and unknown.json()["error"]["code"] == "unknown_original"
    bad_hash = client.post(
        "/api/collection/prompts", json={"title": "t", "positive": "", "references": ["x"]}
    )
    assert bad_hash.status_code == 400
    bad_tag = client.post(
        "/api/collection/prompts", json={"title": "t", "positive": "", "tags": ["a,b"]}
    )
    assert bad_tag.status_code == 400 and bad_tag.json()["error"]["code"] == "invalid_request"
    assert client.get("/api/collection/prompts/abc").status_code == 404
    assert client.get("/api/collection/originals/../../etc").status_code == 404


def test_cross_origin_writes_are_refused(client: TestClient):
    response = client.post(
        "/api/collection/prompts", json={"title": "t", "positive": ""}, headers=EVIL
    )
    assert response.status_code == 403
    upload = client.post("/api/collection/drafts/upload", content=golden_png(), headers=EVIL)
    assert upload.status_code == 403
    assert client.get("/api/collection/prompts").json()["items"] == []


def test_update_and_delete(client: TestClient):
    ids = ids_by_path(client)
    prompt = save_from_library(client, ids["fox1.png"])
    body = {"title": "Renamed", "positive": "a red fox in the snow", "references": []}
    updated = client.post(f"/api/collection/prompts/{prompt['id']}", json=body).json()
    assert updated["title"] == "Renamed" and updated["references"] == []
    assert saved_paths(client) == set()

    assert client.post(f"/api/collection/prompts/{prompt['id']}/delete", json={}).json() == {
        "deleted": True
    }
    assert client.get(f"/api/collection/prompts/{prompt['id']}").status_code == 404
    assert client.post(f"/api/collection/prompts/{prompt['id']}/delete", json={}).status_code == 404


def test_trashed_attempt_stays_listed(client: TestClient):
    ids = ids_by_path(client)
    prompt = save_from_library(client, ids["owl.png"])
    client.post("/api/images/trash", json={"ids": [ids["owl.png"]]})
    got = client.get(f"/api/collection/prompts/{prompt['id']}").json()
    assert got["references"][0]["library_ids"] == []


def test_renamed_file_stays_saved(client: TestClient):
    ids = ids_by_path(client)
    save_from_library(client, ids["owl.png"])
    client.post(f"/api/images/{ids['owl.png']}/rename", json={"name": "owl-renamed.png"})
    assert saved_paths(client) == {"owl-renamed.png"}


def test_thumbnail_rebuilt_from_original(client: TestClient):
    upload = client.post("/api/collection/drafts/upload", content=flux(9, "a heron")).json()
    shutil.rmtree(thumbs_dir())
    thumb = client.get(f"/thumbs/{upload['original']['content_hash']}.webp")
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/webp"
    assert client.get(f"/thumbs/{'0' * 32}.webp").status_code == 404


def test_collection_survives_a_new_catalog(library: Path, config: Config):
    with make_client(library, config) as c:
        wait_for(lambda: c.get("/api/library").json()["prompts_ready"])
        save_from_library(c, ids_by_path(c)["fox1.png"])
    catalog_path(library).unlink()
    Indexer(library, config, workers=1).run()
    with make_client(library, config) as c:
        assert len(c.get("/api/collection/prompts").json()["items"]) == 1
        assert saved_paths(c) == {"fox1.png"}


def test_newer_collection_leaves_the_library_working(library: Path, config: Config):
    with make_client(library, config) as c:
        c.post("/api/collection/prompts", json={"title": "t", "positive": "x"})
    path = collection_dir() / "collection.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with make_client(library, config) as c:
        listed = c.get("/api/collection/prompts")
        assert listed.status_code == 503
        assert listed.json()["error"]["code"] == "collection_unavailable"
        page = c.post("/api/images/query", json={}).json()
        assert page["total"] == 7 and not any(i["saved"] for i in page["items"])
        assert c.post("/api/images/query", json={"filters": {"saved": True}}).json()["total"] == 0


def test_export_and_import(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    ids = ids_by_path(client)
    prompt = save_from_library(client, ids["fox1.png"], tags=["fox"])
    export = client.get("/api/collection/export")
    assert export.status_code == 200
    assert export.headers["content-type"] == "application/zip"
    assert "comfylens-collection-" in export.headers["content-disposition"]

    client.post(f"/api/collection/prompts/{prompt['id']}/delete", json={})
    headers = {"Content-Type": "application/zip"}
    first = client.post("/api/collection/import", content=export.content, headers=headers)
    assert first.json() == {"added": 1, "skipped": 0, "images": 1}
    restored = client.get("/api/collection/prompts").json()["items"]
    assert [(p["title"], p["tags"]) for p in restored] == [(prompt["title"], ["fox"])]
    assert saved_paths(client) == {"fox1.png"}
    again = client.post("/api/collection/import", content=export.content, headers=headers)
    assert again.json() == {"added": 0, "skipped": 1, "images": 1}

    bad = client.post("/api/collection/import", content=b"nope", headers=headers)
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_archive"
    evil = client.post("/api/collection/import", content=export.content, headers=EVIL)
    assert evil.status_code == 403
    monkeypatch.setattr("comfylens.api.routes_collection.MAX_ARCHIVE_BYTES", 10)
    big = client.post("/api/collection/import", content=export.content, headers=headers)
    assert big.status_code == 413


def test_upload_reads_a1111_parameters(client: TestClient):
    text = (
        "a lighthouse at dusk <lora:moody:0.6>\nNegative prompt: text\n"
        "Steps: 30, Sampler: Euler a, CFG scale: 5, Seed: 99"
    )
    draft = client.post(
        "/api/collection/drafts/upload", content=png_with_text({"parameters": text})
    ).json()
    assert draft["metadata"] == "a1111"
    assert draft["title"] == "a lighthouse at dusk"
    assert draft["settings"]["loras"] == [
        {"name": "moody", "strength_model": 0.6, "strength_clip": 0.6}
    ]
