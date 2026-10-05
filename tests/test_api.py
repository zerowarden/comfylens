import shutil
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import (
    flux,
    golden_png,
    ids_by_path,
    library_snapshot,
    png_with_text,
    server_of,
    wait_for,
    write_file,
)
from fastapi.testclient import TestClient

from comfylens.api.app import create_app
from comfylens.config import Config
from comfylens.index.indexer import Indexer
from comfylens.metadata import read_metadata
from comfylens.metadata.strip import strip_metadata
from comfylens.paths import catalog_path, thumbs_dir
from comfylens.version import SCHEMA_VERSION

DAY = 86_400
T0 = 1_790_000_000  # 2026-09-21

write = write_file


pytestmark = pytest.mark.usefixtures("utc")


@pytest.fixture
def library(tmp_path: Path, config: Config) -> Path:
    root = tmp_path / "library"
    write(root, "golden.png", golden_png(), T0)
    write(root, "copy/golden.png", golden_png(), T0 + 60)  # identical content
    write(root, "fox1.png", flux(1, "a red fox in the snow", 0.8), T0 + DAY)
    write(root, "fox2.png", flux(2, "a red fox at night", 0.8), T0 + DAY + 60)
    write(root, "fox3.png", flux(3, "a red fox, golden hour", 1.0), T0 + 3 * DAY)
    write(root, "owl.png", flux(4, "an owl on a branch"), T0 + 3 * DAY + 60)
    write(root, "plain.png", png_with_text({}), T0 + 4 * DAY)
    Indexer(root, config, workers=1).run()
    return root


@pytest.fixture
def client(library: Path, config: Config) -> Iterator[TestClient]:
    app = create_app(library, config, index_on_start=False, web_dir=None)
    with TestClient(app) as c:
        wait_for(lambda: c.get("/api/library").json()["prompts_ready"])
        yield c


def test_library(client: TestClient, library: Path):
    info = client.get("/api/library").json()
    assert info["root"] == str(library)
    assert info["total"] == 7
    assert info["counts_by_status"] == {"ok": 6, "no_metadata": 1}
    assert info["counts_by_family"] == {"flux": 4, "qwen-image-2.1": 2, "(no metadata)": 1}
    assert info["fts_available"] is True
    assert info["index"]["state"] == "idle"
    assert info["versions"]["schema_version"] == SCHEMA_VERSION


def test_facets(client: TestClient):
    f = client.get("/api/facets").json()
    assert f["families"][0] == {"value": "flux", "count": 4}
    assert {"value": "(no metadata)", "count": 1} in f["families"]
    assert f["loras"][0] == {"value": "fox", "count": 3}
    assert f["samplers"] == [{"value": "euler", "count": 6}]
    assert f["date_range"] == {"min": "2026-09-21", "max": "2026-09-25"}
    assert f["numeric_ranges"]["cfg"] == {"min": 2.0, "max": 3.5}


def test_images_query_sort_and_page(client: TestClient):
    page = client.post("/api/images/query", json={"limit": 2}).json()
    assert page["total"] == 7
    assert [i["rel_path"] for i in page["items"]] == ["plain.png", "owl.png"]  # newest first
    item = page["items"][1]
    assert item["family"] == "flux" and item["status"] == "ok" and not item["timestamp_suspect"]
    second = client.post("/api/images/query", json={"limit": 2, "offset": 2}).json()
    assert [i["rel_path"] for i in second["items"]] == ["fox3.png", "fox2.png"]
    by_path = client.post(
        "/api/images/query", json={"sort": {"key": "rel_path", "descending": False}}
    ).json()
    assert by_path["items"][0]["rel_path"] == "copy/golden.png"
    ids = client.post("/api/images/ids", json={}).json()["ids"]
    assert ids == [i["id"] for i in client.post("/api/images/query", json={}).json()["items"]]


def test_filters(client: TestClient):
    def total(filters: dict) -> int:
        return client.post("/api/images/query", json={"filters": filters}).json()["total"]

    assert total({"families": ["flux"]}) == 4
    assert total({"families": ["(no metadata)"]}) == 1
    assert total({"loras": {"names": ["fox"]}}) == 3
    assert total({"loras": {"names": ["fox", "qwen2.1-anime2real-sunburst"], "mode": "all"}}) == 0
    assert total({"text": "red fox"}) == 3
    assert total({"text": "golden hour"}) == 1
    assert total({"text": '"'}) == 0  # only punctuation: LIKE fallback, no error
    assert total({"numeric": {"cfg": [3.0, 4.0]}}) == 4
    assert total({"date_from": "2026-09-24", "date_to": "2026-09-24"}) == 2
    assert total({"statuses": ["no_metadata"]}) == 1
    # The goldens' only warning, UNUSED_LORA, is informational: no badge, no filter match.
    assert total({"has_warnings": True}) == 0
    assert total({"has_warnings": False}) == 7


def test_stats_scope_kinds_and_dedupe(client: TestClient):
    everything = client.post("/api/stats", json={}).json()
    assert everything["scope"] == {
        "scope_kind": "all",
        "scope_size": 7,
        "excluded_no_metadata": 1,
        "duplicates_removed": 1,
        "analyzed": 5,
    }
    assert [(g["family"], g["images"]) for g in everything["groups"]] == [
        ("flux", 4),
        ("qwen-image-2.1", 1),
    ]
    ids = ids_by_path(client)
    selected = client.post("/api/stats", json={"selection": [ids["fox1.png"], ids["plain.png"]]})
    assert selected.json()["scope"]["scope_kind"] == "selection"
    assert selected.json()["scope"]["analyzed"] == 1
    filtered = client.post("/api/stats", json={"filters": {"families": ["flux"]}}).json()
    assert filtered["scope"]["scope_kind"] == "filtered"


def test_stats_sections(client: TestClient):
    (flux, qwen) = client.post("/api/stats", json={}).json()["groups"]
    steps = flux["numeric"]["steps"]
    assert (steps["n"], steps["mode"], steps["mode_share"]) == (4, [20.0], 1.0)
    assert steps["histogram"] == {"kind": "discrete", "bars": [{"x0": 20, "x1": 20, "count": 4}]}
    assert "model_family" not in flux["categorical"]  # the group key, not a categorical field
    assert flux["categorical"]["sampler_name"]["values"] == [
        {"value": "euler", "count": 4, "share": 1.0}
    ]
    assert flux["categorical"]["vae"]["values"][0]["value"] == "ae"
    assert flux["seeds"] == {"n": 4, "n_unique": 4, "repeated": []}
    (fox,) = flux["loras"]
    # Strength statistics cover the 3 users only, not the owl at strength "zero".
    assert (fox["name"], fox["images"], fox["share"]) == ("fox", 3, 0.75)
    assert fox["strength_model"]["n"] == 3
    assert fox["strength_model"]["mean"] == pytest.approx(0.8666666)
    assert fox["positions"] == [{"value": 0, "count": 3}]
    assert flux["configs"][0]["fields"]["lora_stack_key"] == "fox@0.8"
    # The co-occurrence graph: fox alone has no links; the golden chain links its two LoRAs.
    assert {"name": "fox", "images": 3, "median": 0.8} in flux["graph"]["nodes"]
    assert flux["graph"]["links"] == []
    assert qwen["loras"][0]["name"] == "qwen2.1-anime2real-sunburst"
    assert qwen["graph"]["nodes"] == [
        {"name": "qwen2.1-anime2real-sunburst", "images": 1, "median": 1.13},
        {"name": "qwen2.1-lenovo-ultrareal", "images": 1, "median": 1.06},
    ]
    assert qwen["graph"]["links"] == [
        {
            "source": "qwen2.1-anime2real-sunburst",
            "target": "qwen2.1-lenovo-ultrareal",
            "images": 1,
        }
    ]


def test_stats_base_name(client: TestClient):
    only = client.post("/api/stats", json={"sections": ["loras"], "lora_key": "base_name"}).json()[
        "groups"
    ][0]
    assert only.get("numeric") is None
    assert all(row["steps"] is not None for row in only["loras"])


def test_timeline(client: TestClient):
    tl = client.post("/api/timeline", json={"filters": {"date_from": "2026-09-24"}}).json()
    # The date filter is ignored so the brush can widen again.
    assert tl["date_min"] == "2026-09-21" and tl["date_max"] == "2026-09-25"
    assert len(tl["buckets"]) == 5
    assert tl["series"]["flux"] == [0, 2, 0, 2, 0]
    assert tl["series"]["(no metadata)"] == [0, 0, 0, 0, 1]
    assert tl["selected"] is None and tl["suspect"] == [0] * 5
    ids = ids_by_path(client)
    picked = client.post("/api/timeline", json={"selection": [ids["owl.png"]]}).json()
    assert picked["selected"] == [0, 0, 0, 1, 0]
    weekly = client.post("/api/timeline", json={"bucket": "week"}).json()
    assert weekly["buckets"] == ["2026-09-21"]  # a Monday
    monthly = client.post("/api/timeline", json={"bucket": "month"}).json()
    assert monthly["buckets"] == ["2026-09-01"]


def test_prompts(client: TestClient):
    body = client.post("/api/prompts", json={}).json()
    flux = body["groups"][0]
    assert (flux["family"], flux["images"], flux["distinct_total"]) == ("flux", 4, 4)
    assert {"term": "red fox", "df": 3, "share": 0.75} in flux["bigrams"]
    negative = client.post("/api/prompts", json={"side": "negative"}).json()
    assert negative["side"] == "negative"
    assert negative["groups"][0]["distinct"][0]["text"] == "blurry"


def test_similar_sentence_clusters_filter_images(tmp_path: Path, config: Config):
    root = tmp_path / "library"
    write(root, "fox1.png", flux(1, "a red fox in the snow"), T0)
    write(root, "fox2.png", flux(2, "a red fox in the snow at night"), T0 + 60)
    write(root, "owl.png", flux(3, "an owl on a branch"), T0 + 120)
    Indexer(root, config, workers=1).run()
    with TestClient(create_app(root, config, index_on_start=False, web_dir=None)) as c:
        wait_for(lambda: c.get("/api/library").json()["prompts_ready"])
        body = c.post("/api/prompts", json={}).json()
        (group,) = body["groups"]
        (cluster,) = group["clusters"]
        assert cluster["text"] == "a red fox in the snow"
        assert {m["text"] for m in cluster["members"]} == {
            "a red fox in the snow",
            "a red fox in the snow at night",
        }
        assert cluster["images"] == 2

        # Clicking the cluster filters the library to exactly its images.
        filter_body = {"filters": {"sentences": [m["key"] for m in cluster["members"]]}}
        page = c.post("/api/images/query", json=filter_body).json()
        assert page["total"] == 2
        assert sorted(i["rel_path"] for i in page["items"]) == ["fox1.png", "fox2.png"]

        # While prompt frames are not ready the filter matches nothing, not everything.
        snap = server_of(c).store.current
        frames, snap.prompts = snap.prompts, None
        try:
            assert c.post("/api/images/query", json=filter_body).json()["total"] == 0
        finally:
            snap.prompts = frames


def test_prompt_frames_arrival_bumps_the_snapshot(client: TestClient):
    # The UI polls while prompts warm up and refetches when built_at moves, so a sentence
    # filter applied before the frames land resolves on its own.
    server = server_of(client)
    before = server.store.current.built_at
    server.store.rebuild()
    wait_for(lambda: server.store.current.prompts is not None)
    assert server.store.current.built_at > before


def test_prompts_warming(client: TestClient):
    snap = server_of(client).store.current
    frames, snap.prompts = snap.prompts, None
    try:
        r = client.post("/api/prompts", json={})
        assert r.status_code == 503
        assert r.json()["warming"] is True and r.json()["error"]["code"] == "warming"
    finally:
        snap.prompts = frames


def test_node_inputs(client: TestClient):
    keys = client.post("/api/node-inputs/keys", json={}).json()["keys"]
    assert {"class_type": "KSampler", "input_name": "seed", "kind": "num", "files": 5} in keys
    stats = client.post(
        "/api/node-inputs/stats", json={"class_type": "KSampler", "input_name": "cfg"}
    ).json()
    assert [(g["family"], g["kind"], g["numeric"]["mode"]) for g in stats["groups"]] == [
        ("flux", "num", [3.5]),
        ("qwen-image-2.1", "num", [2.0]),
    ]
    text = client.post(
        "/api/node-inputs/stats", json={"class_type": "VAELoader", "input_name": "vae_name"}
    ).json()
    assert text["groups"][0]["categorical"]["values"][0]["value"] == "ae.safetensors"
    long = client.post(
        "/api/node-inputs/stats",
        json={"class_type": "TextEncodeQwenImage21", "input_name": "prompt"},
    ).json()
    assert long["groups"][0]["n_unique"] == 1  # longer than 200 characters


def test_detail_of_the_reference_file(client: TestClient):
    file_id = ids_by_path(client)["golden.png"]
    d = client.get(f"/api/images/{file_id}").json()
    assert d["file"]["rel_path"] == "golden.png" and d["file"]["aspect_label"] == "1:1"
    assert d["generation"]["seed"] == "898921074692413"
    assert d["generation"]["lora_stack_key"].startswith("qwen2.1-anime2real-sunburst@1.13")
    assert [s["node_id"] for s in d["stages"]] == ["6"]
    unused = [lora for lora in d["loras"] if not lora["reachable"]]
    assert [(u["node_id"], u["name"]) for u in unused] == [("25", "qwen2.1-exampleV01_000004956")]
    assert d["warnings"] == [
        {
            "code": "UNUSED_LORA",
            "node_id": "25",
            "message": "LoRA loaded but not connected to any sampler",
        }
    ]
    nodes = {n["id"]: n for n in d["nodes"]}
    assert nodes["25"]["reachable"] is False and nodes["6"]["reachable"] is True
    assert nodes["6"]["inputs"]["model"] == ["29", 0]
    assert nodes["9"]["title"] == "Text Encode Qwen Image 2.1"


def test_raw(client: TestClient, library: Path, config: Config):
    file_id = ids_by_path(client)["golden.png"]
    raw = client.get(f"/api/images/{file_id}/raw").json()
    assert raw["sources"] == {"prompt": "png:tEXt", "workflow": "png:tEXt"}
    assert raw["prompt"]["6"]["class_type"] == "KSampler"
    assert raw["workflow"]["version"] == 0.4
    assert raw["other"] == {}
    plain = ids_by_path(client)["plain.png"]
    assert client.get(f"/api/images/{plain}/raw").json()["prompt"] is None


def test_nan_is_served_as_null(tmp_path: Path, config: Config):
    root = tmp_path / "nan"
    text = (
        '{"7": {"class_type": "KSampler", "inputs": {"cfg": NaN, "seed": 1}},'
        ' "9": {"class_type": "SaveImage", "inputs": {"images": ["7", 0]}}}'
    )
    write(root, "nan.png", png_with_text({"prompt": text}), T0)
    Indexer(root, config, workers=1).run()
    with TestClient(create_app(root, config, index_on_start=False, web_dir=None)) as c:
        raw = c.get("/api/images/1/raw").json()
        assert raw["prompt"]["7"]["inputs"]["cfg"] is None
        assert c.get("/api/images/1").json()["nodes"][0]["inputs"]["cfg"] is None


def test_non_string_node_title_is_served_as_null(tmp_path: Path, config: Config):
    root = tmp_path / "title"
    text = (
        '{"7": {"class_type": "KSampler", "inputs": {"seed": 1}, "_meta": {"title": 5}},'
        ' "9": {"class_type": "SaveImage", "inputs": {"images": ["7", 0]}}}'
    )
    write(root, "t.png", png_with_text({"prompt": text}), T0)
    Indexer(root, config, workers=1).run()
    with TestClient(create_app(root, config, index_on_start=False, web_dir=None)) as c:
        nodes = c.get("/api/images/1").json()["nodes"]
    assert [(n["id"], n["title"]) for n in nodes] == [("7", None), ("9", None)]


def test_original_file(client: TestClient, library: Path):
    file_id = ids_by_path(client)["fox1.png"]
    r = client.get(f"/api/images/{file_id}/file")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content == (library / "fox1.png").read_bytes()
    attached = client.get(f"/api/images/{file_id}/file?download=true")
    assert attached.headers["content-disposition"].startswith("attachment")


def test_stripped_copy(client: TestClient, library: Path):
    path = library / "fox1.png"
    original, mtime_ns = path.read_bytes(), path.stat().st_mtime_ns
    file_id = ids_by_path(client)["fox1.png"]
    r = client.get(f"/api/images/{file_id}/stripped")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.headers["content-disposition"] == 'attachment; filename="fox1.png"'
    assert read_metadata(r.content).texts == {}
    assert r.content == strip_metadata(original) and len(r.content) < len(original)
    # The original keeps its bytes, metadata included, and its modification time.
    assert path.read_bytes() == original and path.stat().st_mtime_ns == mtime_ns
    assert read_metadata(original).texts


def test_stripped_copy_of_an_escaped_name(tmp_path: Path, config: Config):
    root = tmp_path / "names"
    write(root, 'a "fox" é.png', golden_png(), T0)
    Indexer(root, config, workers=1).run()
    with TestClient(create_app(root, config, index_on_start=False, web_dir=None)) as c:
        r = c.get("/api/images/1/stripped")
    assert r.headers["content-disposition"] == (
        "attachment; filename*=utf-8''a%20%22fox%22%20%C3%A9.png"
    )


def test_stripped_copy_of_a_damaged_file_is_422(client: TestClient, library: Path):
    file_id = ids_by_path(client)["fox1.png"]
    (library / "fox1.png").write_bytes(golden_png()[:100])
    r = client.get(f"/api/images/{file_id}/stripped")
    assert r.status_code == 422 and r.json()["error"]["code"] == "cannot_strip"
    (library / "fox1.png").unlink()
    assert client.get(f"/api/images/{file_id}/stripped").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/api/images/999/file",
        "/api/images/999/stripped",
        "/api/images/abc/file",
        "/api/images/..%2F..%2Fetc%2Fpasswd/file",
        "/api/images/1%2F..%2F..%2Fsecret/file",
        "/api/images/-1",
        "/thumbs/..%2F..%2Fcatalog.sqlite",
        "/thumbs/ABCDEF0123456789ABCDEF0123456789.webp",
        "/thumbs/0123456789abcdef0123456789abcdef.png",
        "/thumbs/0123456789abcdef0123456789abcdef.webp",  # well-formed but absent
    ],
)
def test_traversal_and_unknown_paths_are_404(client: TestClient, path: str):
    r = client.get(path)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_original_path_comes_from_the_catalog_only(client: TestClient, library: Path):
    (library.parent / "secret.png").write_bytes(b"secret")
    file_id = ids_by_path(client)["fox1.png"]
    with sqlite3.connect(catalog_path(library)) as conn:
        conn.execute("UPDATE files SET rel_path = '../secret.png' WHERE id = ?", (file_id,))
    assert client.get(f"/api/images/{file_id}/file").status_code == 404


def test_thumbnails(client: TestClient):
    item = client.post("/api/images/query", json={"limit": 1}).json()["items"][0]
    r = client.get(f"/thumbs/{item['content_hash']}.webp")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_errors_and_no_cors(client: TestClient):
    bad = client.post("/api/stats", json={"sections": ["nope"]})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_request"
    assert client.get("/api/nope").json()["error"]["code"] == "not_found"
    assert client.get("/api/stats").status_code == 404  # a wrong method is 404, never 405
    wrong_method = client.post("/api/library")
    assert wrong_method.status_code == 404
    assert wrong_method.json()["error"]["code"] == "not_found"
    r = client.get("/api/library", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_unknown_host_header_is_rejected(client: TestClient):
    # DNS rebinding: another site's host name must not reach the library.
    assert client.get("/api/library", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/library", headers={"Host": "localhost:8765"}).status_code == 200


def test_rescan_picks_up_a_new_file(client: TestClient, library: Path):
    server = server_of(client)
    write(library, "new.png", flux(9, "a brand new fox"), T0 + 5 * DAY)
    assert client.post("/api/index/rescan").status_code == 202
    wait_for(lambda: server.last_finished_at is not None and not server.indexing)
    assert client.get("/api/library").json()["total"] == 8
    paths = ids_by_path(client)
    assert "new.png" in paths
    assert (
        client.post("/api/images/query", json={"filters": {"text": "brand new"}}).json()["total"]
        == 1
    )


def test_rescan_restores_missing_thumbnails(client: TestClient):
    server = server_of(client)
    items = client.post("/api/images/query", json={"limit": 100}).json()["items"]
    urls = {f"/thumbs/{i['content_hash']}.webp" for i in items}
    shutil.rmtree(thumbs_dir())
    assert {client.get(u).status_code for u in urls} == {404}

    assert client.post("/api/index/rescan").status_code == 202
    wait_for(lambda: server.last_finished_at is not None and not server.indexing)
    assert {client.get(u).status_code for u in urls} == {200}


def test_status_stays_busy_until_the_new_snapshot_is_served(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    server = server_of(client)
    started, release = threading.Event(), threading.Event()
    rebuild = server.store.rebuild

    def slow_rebuild(**kwargs):
        started.set()
        release.wait(5)
        return rebuild(**kwargs)

    monkeypatch.setattr(server.store, "rebuild", slow_rebuild)
    before = client.get("/api/library").json()["snapshot_built_at"]
    # The run itself is over when the rebuild starts; the client must still see it as busy.
    assert client.post("/api/index/rescan").json()["state"] != "idle"
    started.wait(5)
    assert client.get("/api/index/status").json()["state"] == "finalizing"
    release.set()
    wait_for(lambda: client.get("/api/index/status").json()["state"] == "idle")
    assert client.get("/api/library").json()["snapshot_built_at"] > before


def test_rescan_while_running_is_409(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    server = server_of(client)
    release = threading.Event()
    monkeypatch.setattr(server.indexer, "run", lambda **_: release.wait(5))
    assert client.post("/api/index/rescan").status_code == 202
    busy = client.post("/api/index/rescan")
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "index_running"
    release.set()
    wait_for(lambda: not server.indexing)


def test_index_failure_is_reported(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    server = server_of(client)

    def locked(**_kwargs):
        raise RuntimeError("another process (pid 1) is indexing this library")

    monkeypatch.setattr(server.indexer, "run", locked)
    client.post("/api/index/rescan")
    wait_for(lambda: server.last_finished_at is not None and not server.indexing)
    assert "pid 1" in client.get("/api/index/status").json()["last_error"]


def test_snapshot_rebuild_failure_is_reported(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    server = server_of(client)

    def broken(**_kwargs):
        raise RuntimeError("snapshot boom")

    monkeypatch.setattr(server.store, "rebuild", broken)
    assert client.post("/api/index/rescan").status_code == 202
    wait_for(lambda: server.last_finished_at is not None and not server.indexing)
    assert "snapshot boom" in client.get("/api/index/status").json()["last_error"]


def test_serving_never_writes_to_the_library(library: Path, config: Config):
    before = library_snapshot(library)
    with TestClient(create_app(library, config, index_on_start=True, web_dir=None)) as c:
        server = server_of(c)
        wait_for(lambda: server.last_finished_at is not None)
        for path in ("/api/library", "/api/facets"):
            c.get(path)
        c.post("/api/stats", json={})
        c.post("/api/index/rescan")
        wait_for(lambda: not server.indexing)
        c.get("/api/images/1/file")
    assert library_snapshot(library) == before


def test_unindexed_library(tmp_path: Path, config: Config):
    root = tmp_path / "empty"
    root.mkdir()
    with TestClient(create_app(root, config, index_on_start=False, web_dir=None)) as c:
        assert c.get("/api/library").json()["total"] == 0
        assert c.post("/api/stats", json={}).json()["groups"] == []
        assert c.post("/api/timeline", json={}).json()["buckets"] == []
        assert c.get("/api/images/1").status_code == 503


def test_frontend_is_served_with_fallback(tmp_path: Path, library: Path, config: Config):
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<html>app</html>")
    (web / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("secret")
    with TestClient(create_app(library, config, index_on_start=False, web_dir=web)) as c:
        assert c.get("/").text == "<html>app</html>"
        assert c.get("/some/client/route").text == "<html>app</html>"
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/..%2Fsecret.txt").text == "<html>app</html>"
        assert c.get("/api/unknown").status_code == 404
    with TestClient(create_app(library, config, index_on_start=False, web_dir=tmp_path / "x")) as c:
        assert "not built" in c.get("/").text


def test_distinctive_terms(client: TestClient):
    ids = ids_by_path(client)
    missing = client.post("/api/prompts/distinctive", json={})
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "selection_required"
    body = client.post(
        "/api/prompts/distinctive",
        json={"selection": [ids["fox1.png"], ids["fox2.png"], ids["fox3.png"]]},
    ).json()
    assert body["scope"]["scope_kind"] == "selection" and body["side"] == "positive"
    (flux,) = body["groups"]
    assert (flux["family"], flux["selection_images"], flux["rest_images"]) == ("flux", 3, 1)
    selection = [t["term"] for t in flux["unigrams"]["selection"]]
    assert set(selection[:2]) == {"fox", "red"}  # in all three selected images
    assert {t["term"] for t in flux["unigrams"]["rest"]} == {"owl", "branch"}
    # The single "rest" prompt has no bigram at all: nothing to compare, nothing listed.
    assert flux["bigrams"] == {"selection": [], "rest": []}


def test_distinctive_terms_warming(client: TestClient):
    snap = server_of(client).store.current
    frames, snap.prompts = snap.prompts, None
    try:
        r = client.post("/api/prompts/distinctive", json={"selection": [1]})
        assert r.status_code == 503 and r.json()["warming"] is True
    finally:
        snap.prompts = frames
