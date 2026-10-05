import sqlite3
import threading
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from conftest import ids_by_path, png_with_text, server_of, txt2img_png, wait_for, write_file
from fastapi.testclient import TestClient

from comfylens.analytics import snapshot
from comfylens.api import server as server_module
from comfylens.api.app import create_app
from comfylens.api.schemas import TRASH_BATCH
from comfylens.config import Config, build_config
from comfylens.index.file_ops import InvalidName, new_rel_path
from comfylens.index.indexer import Indexer
from comfylens.paths import catalog_path

T0 = 1_790_000_000


@pytest.fixture
def library(tmp_path: Path, config: Config) -> Path:
    root = tmp_path / "library"
    write_file(root, "a.png", txt2img_png(1), T0)
    write_file(root, "b.png", txt2img_png(2), T0 + 60)
    write_file(root, "sub/c.png", txt2img_png(3), T0 + 120)
    write_file(root, "plain.png", png_with_text({}), T0 + 180)
    Indexer(root, config, workers=1).run()
    return root


def make_client(root: Path, config: Config) -> TestClient:
    return TestClient(create_app(root, config, index_on_start=False, web_dir=None))


@pytest.fixture
def client(library: Path, config: Config) -> Iterator[TestClient]:
    with make_client(library, config) as c:
        yield c


def catalog_paths(root: Path) -> dict[str, int]:
    with sqlite3.connect(catalog_path(root)) as conn:
        return dict(conn.execute("SELECT rel_path, id FROM files").fetchall())


def assert_index_finds_nothing_to_do(root: Path, config: Config) -> None:
    # The edit kept disk and catalog in step: no file is re-read or dropped.
    result = Indexer(root, config, workers=1).run()
    assert (result.new, result.changed, result.deleted) == (0, 0, 0)


@pytest.mark.parametrize(
    ("old", "name", "new"),
    [
        ("a.png", "b.png", "b.png"),
        ("sub/dir/a.png", "renamed copy.png", "sub/dir/renamed copy.png"),
        ("a.PNG", "b.png", "b.png"),  # the extension's case may change
        ("a.jpeg", "ünïcode ✓.jpeg", "ünïcode ✓.jpeg"),
        ("a.png", ".hidden.png", ".hidden.png"),
    ],
)
def test_new_rel_path(config: Config, old: str, name: str, new: str):
    assert new_rel_path(old, name, config) == new


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("", "empty"),
        ("   ", "empty"),
        (" b.png", "whitespace"),
        ("b.png\n", "whitespace"),
        ("x/b.png", "slash"),
        ("b\x01.png", "control"),
        ("b.jpg", "keep the .png extension"),
        ("b", "keep the .png extension"),
        (".png", "keep the .png extension"),
        ("\udc80.png", "UTF-8"),
        ("é" * 127 + ".png", "255 bytes"),
    ],
)
def test_invalid_names(config: Config, name: str, message: str):
    with pytest.raises(InvalidName, match=message):
        new_rel_path("dir/a.png", name, config)


def test_a_name_the_indexer_would_skip_is_refused():
    config = build_config({"index": {"exclude_globs": ["**/*.skip.png"]}})
    with pytest.raises(InvalidName, match="excluded"):
        new_rel_path("a.png", "b.skip.png", config)


def test_rename(client: TestClient, library: Path, config: Config):
    file_id = ids_by_path(client)["sub/c.png"]
    before = (library / "sub/c.png").stat().st_mtime_ns
    r = client.post(f"/api/images/{file_id}/rename", json={"name": "fox in snow.png"})
    assert r.status_code == 200
    assert r.json() == {"id": file_id, "rel_path": "sub/fox in snow.png", "generated_at": T0 + 120}

    assert not (library / "sub/c.png").exists()
    assert (library / "sub/fox in snow.png").stat().st_mtime_ns == before
    assert ids_by_path(client)["sub/fox in snow.png"] == file_id
    assert client.get(f"/api/images/{file_id}").json()["file"]["rel_path"] == "sub/fox in snow.png"
    assert client.get(f"/api/images/{file_id}/file").status_code == 200
    assert catalog_paths(library)["sub/fox in snow.png"] == file_id
    assert_index_finds_nothing_to_do(library, config)


def test_rename_changes_the_snapshot_version(client: TestClient):
    # The UI refreshes its data when snapshot_built_at changes.
    before = client.get("/api/library").json()["snapshot_built_at"]
    client.post(f"/api/images/{ids_by_path(client)['a.png']}/rename", json={"name": "z.png"})
    assert client.get("/api/library").json()["snapshot_built_at"] > before


def test_rename_to_the_same_name_is_a_no_op(client: TestClient, library: Path):
    file_id = ids_by_path(client)["a.png"]
    r = client.post(f"/api/images/{file_id}/rename", json={"name": "a.png"})
    assert r.status_code == 200 and r.json()["rel_path"] == "a.png"
    assert (library / "a.png").is_file()


def test_rename_never_replaces_another_file(client: TestClient, library: Path):
    file_id = ids_by_path(client)["a.png"]
    b_bytes = (library / "b.png").read_bytes()
    r = client.post(f"/api/images/{file_id}/rename", json={"name": "b.png"})
    assert r.status_code == 409
    assert r.json()["error"] == {
        "code": "name_taken",
        "message": "a file named b.png already exists",
    }
    assert (library / "a.png").is_file() and (library / "b.png").read_bytes() == b_bytes
    # Not even something the catalog does not list.
    sub_id = ids_by_path(client)["sub/c.png"]
    (library / "sub/taken.png").mkdir()
    assert (
        client.post(f"/api/images/{sub_id}/rename", json={"name": "taken.png"}).status_code == 409
    )


@pytest.mark.parametrize(
    ("raw_id", "body", "status", "code"),
    [
        ("999", {"name": "x.png"}, 404, "not_found"),
        ("abc", {"name": "x.png"}, 404, "not_found"),
        ("1", {"name": "x.jpg"}, 400, "invalid_name"),
        ("1", {"name": "../x.png"}, 400, "invalid_name"),
        ("1", {}, 400, "invalid_request"),
    ],
)
def test_rename_errors(client: TestClient, raw_id: str, body: dict, status: int, code: str):
    r = client.post(f"/api/images/{raw_id}/rename", json=body)
    assert r.status_code == status and r.json()["error"]["code"] == code


def test_rename_of_a_file_gone_from_disk(client: TestClient, library: Path):
    file_id = ids_by_path(client)["a.png"]
    (library / "a.png").unlink()
    r = client.post(f"/api/images/{file_id}/rename", json={"name": "x.png"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "file_missing"
    server = server_of(client)
    wait_for(lambda: server.last_finished_at is not None and not server.indexing)
    assert "a.png" not in ids_by_path(client)  # the catalog caught up


def test_rename_onto_a_stale_catalog_row(client: TestClient, library: Path, config: Config):
    # b.png was deleted outside the app and no index run has noticed: its row must not block
    # the rename, and it leaves the snapshot with it.
    paths = ids_by_path(client)
    (library / "b.png").unlink()
    r = client.post(f"/api/images/{paths['a.png']}/rename", json={"name": "b.png"})
    assert r.status_code == 200
    assert ids_by_path(client) == {
        "b.png": paths["a.png"],
        "sub/c.png": paths["sub/c.png"],
        "plain.png": paths["plain.png"],
    }
    assert client.get("/api/library").json()["total"] == 3
    assert_index_finds_nothing_to_do(library, config)


@pytest.mark.usefixtures("utc")
def test_rename_updates_a_timestamp_taken_from_the_name(tmp_path: Path):
    config = build_config(
        {
            "timestamps": {
                "source": "filename",
                "filename_patterns": [{"regex": r"(?P<ts>\d{8}-\d{6})", "format": "%Y%m%d-%H%M%S"}],
            }
        }
    )
    root = tmp_path / "library"
    write_file(root, "img_20250102-030405.png", txt2img_png(1), T0)
    Indexer(root, config, workers=1).run()
    with make_client(root, config) as c:
        file_id = ids_by_path(c)["img_20250102-030405.png"]
        r = c.post(f"/api/images/{file_id}/rename", json={"name": "img_20240607-080910.png"})
        stamp = int(datetime(2024, 6, 7, 8, 9, 10).timestamp())
        assert r.json()["generated_at"] == stamp
        day = {"date_from": "2024-06-07", "date_to": "2024-06-07"}
        assert c.post("/api/images/ids", json={"filters": day}).json()["ids"] == [file_id]
        assert c.get("/api/facets").json()["date_range"] == {
            "min": "2024-06-07",
            "max": "2024-06-07",
        }
    assert_index_finds_nothing_to_do(root, config)


def test_rename_is_undone_when_the_catalog_is_busy(client: TestClient, library: Path, monkeypatch):
    monkeypatch.setattr(server_module, "_EDIT_BUSY_TIMEOUT", 0.05)
    file_id = ids_by_path(client)["a.png"]
    blocker = sqlite3.connect(catalog_path(library), autocommit=True)
    blocker.execute("BEGIN IMMEDIATE")  # another writer holds the catalog
    try:
        r = client.post(f"/api/images/{file_id}/rename", json={"name": "x.png"})
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    assert r.status_code == 503 and r.json()["error"]["code"] == "catalog_busy"
    assert (library / "a.png").is_file() and not (library / "x.png").exists()
    assert ids_by_path(client)["a.png"] == file_id


def test_trash(client: TestClient, library: Path, config: Config, trash_dir: Path):
    paths = ids_by_path(client)
    families = client.get("/api/facets").json()["families"]
    assert {"value": "flux", "count": 3} in families
    r = client.post("/api/images/trash", json={"ids": [paths["a.png"], paths["sub/c.png"]]})
    assert r.status_code == 200
    assert r.json() == {"trashed": [paths["a.png"], paths["sub/c.png"]], "failed": []}

    assert not (library / "a.png").exists() and not (library / "sub/c.png").exists()
    assert sorted(p.name.split("-", 1)[1] for p in trash_dir.iterdir()) == ["a.png", "c.png"]
    assert set(ids_by_path(client)) == {"b.png", "plain.png"}
    assert client.get("/api/library").json()["total"] == 2
    assert {"value": "flux", "count": 1} in client.get("/api/facets").json()["families"]
    assert client.get(f"/api/images/{paths['a.png']}").status_code == 404
    assert set(catalog_paths(library)) == {"b.png", "plain.png"}
    assert_index_finds_nothing_to_do(library, config)


def test_trash_reports_each_file(client: TestClient, library: Path, monkeypatch):
    paths = ids_by_path(client)
    (library / "b.png").unlink()  # already gone: only its row goes

    from comfylens.index import file_ops

    real = file_ops.send2trash

    def refuse_plain(path: str) -> None:
        if path.endswith("plain.png"):
            raise PermissionError(13, "Permission denied")
        real(path)

    monkeypatch.setattr(file_ops, "send2trash", refuse_plain)
    ids = [paths["a.png"], paths["b.png"], paths["plain.png"], 999, paths["a.png"]]
    r = client.post("/api/images/trash", json={"ids": ids})
    assert r.status_code == 200
    assert r.json() == {
        "trashed": [paths["a.png"], paths["b.png"]],
        "failed": [
            {"id": paths["plain.png"], "message": "plain.png: Permission denied"},
            {"id": 999, "message": "no image with this id"},
        ],
    }
    assert (library / "plain.png").is_file()
    assert set(ids_by_path(client)) == {"sub/c.png", "plain.png"}


@pytest.mark.parametrize("ids", [[], list(range(1, TRASH_BATCH + 2))])
def test_trash_batch_limits(client: TestClient, ids: list[int]):
    r = client.post("/api/images/trash", json={"ids": ids})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"


def test_edits_without_a_catalog(tmp_path: Path, config: Config):
    root = tmp_path / "empty"
    root.mkdir()
    with make_client(root, config) as c:
        assert c.post("/api/images/trash", json={"ids": [1]}).status_code == 503
        assert c.post("/api/images/1/rename", json={"name": "x.png"}).status_code == 503
    assert not catalog_path(root).exists()  # an edit never creates an empty catalog


@pytest.mark.parametrize(
    "origin", ["http://evil.example", "null", "https://localhost.evil.example"]
)
def test_other_sites_cannot_edit(client: TestClient, library: Path, origin: str):
    file_id = ids_by_path(client)["a.png"]
    headers = {"Origin": origin}
    r = client.post(f"/api/images/{file_id}/rename", json={"name": "x.png"}, headers=headers)
    assert r.status_code == 403 and r.json()["error"]["code"] == "cross_origin"
    r = client.post("/api/images/trash", json={"ids": [file_id]}, headers=headers)
    assert r.status_code == 403
    assert (library / "a.png").is_file()


def test_the_dev_server_origin_can_edit(client: TestClient):
    file_id = ids_by_path(client)["a.png"]
    headers = {"Origin": "http://localhost:5173"}  # Vite, proxying to the API
    r = client.post(f"/api/images/{file_id}/rename", json={"name": "x.png"}, headers=headers)
    assert r.status_code == 200


def test_a_form_post_is_not_read_as_json(client: TestClient, library: Path):
    # What a cross-site <form> can send without a preflight.
    file_id = ids_by_path(client)["a.png"]
    r = client.post(
        "/api/images/trash",
        content=f'{{"ids": [{file_id}]}}',
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 400
    assert (library / "a.png").is_file()


def test_an_edit_during_an_index_run_queues_another(client: TestClient, monkeypatch):
    server = server_of(client)
    release = threading.Event()
    runs: list[float] = []

    def slow_run(**_kwargs):
        runs.append(time.time())
        if len(runs) == 1:
            release.wait(5)

    monkeypatch.setattr(server.indexer, "run", slow_run)
    server.start_index()
    wait_for(lambda: len(runs) == 1)
    file_id = ids_by_path(client)["a.png"]
    assert client.post(f"/api/images/{file_id}/rename", json={"name": "x.png"}).status_code == 200
    release.set()
    wait_for(lambda: not server.indexing)
    assert len(runs) == 2


def test_an_edit_neither_waits_for_a_rebuild_nor_is_lost_to_it(client: TestClient, monkeypatch):
    # The rebuild reads the catalog before the edit commits and swaps in after it: the edit must
    # return at once, and survive the swap.
    server = server_of(client)
    file_id = ids_by_path(client)["a.png"]
    read, release = threading.Event(), threading.Event()
    build = snapshot.build_snapshot

    def slow_build(catalog: Path) -> snapshot.Snapshot:
        snap = build(catalog)  # still holds a.png
        read.set()
        release.wait(5)
        return snap

    monkeypatch.setattr(snapshot, "build_snapshot", slow_build)
    rebuild = threading.Thread(target=server.store.rebuild)
    rebuild.start()
    read.wait(5)
    try:
        r = client.post(f"/api/images/{file_id}/rename", json={"name": "x.png"})
        assert r.status_code == 200
        assert ids_by_path(client)["x.png"] == file_id
        r = client.post("/api/images/trash", json={"ids": [ids_by_path(client)["b.png"]]})
        assert r.json()["failed"] == []
    finally:
        release.set()
        rebuild.join(5)
    assert set(ids_by_path(client)) == {"x.png", "sub/c.png", "plain.png"}
