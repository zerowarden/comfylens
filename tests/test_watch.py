import os
import threading
import time
from pathlib import Path

import pytest
import watchfiles
from conftest import txt2img_png, wait_for
from fastapi.testclient import TestClient

from comfylens.api.app import create_app
from comfylens.config import Config
from comfylens.index.watch import LibraryWatcher


def fox(seed: int) -> bytes:
    return txt2img_png(seed, (32, 32))


def test_only_files_the_scanner_would_index_are_relevant(tmp_path: Path, config: Config):
    watcher = LibraryWatcher(tmp_path, config.index, lambda: None)
    added = watchfiles.Change.added
    assert watcher.relevant(added, str(tmp_path / "a.png"))
    assert watcher.relevant(added, str(tmp_path / "sub" / "b.JPEG"))
    assert not watcher.relevant(added, str(tmp_path / "notes.txt"))
    assert not watcher.relevant(added, str(tmp_path / ".trash" / "c.png"))
    assert not watcher.relevant(added, str(tmp_path / "x" / ".cache" / "d.png"))
    assert not watcher.relevant(added, str(tmp_path.parent / "elsewhere.png"))


def test_folder_moves_are_relevant(tmp_path: Path, config: Config):
    watcher = LibraryWatcher(tmp_path, config.index, lambda: None)
    added = watchfiles.Change.added
    assert watcher.relevant(added, str(tmp_path / "renamed"))
    assert watcher.relevant(added, str(tmp_path / "nested" / "renamed"))
    assert not watcher.relevant(added, str(tmp_path / ".trash"))
    assert not watcher.relevant(added, str(tmp_path.parent / "elsewhere"))


def test_renamed_folder_is_indexed_without_a_rescan(tmp_path: Path, config: Config):
    root = tmp_path / "library"
    (root / "before").mkdir(parents=True)
    (root / "before" / "a.png").write_bytes(fox(1))
    app = create_app(root, config, watch=True, watch_debounce_ms=100, web_dir=None)
    with TestClient(app) as c:
        server = c.app.state.server  # type: ignore[attr-defined]

        def paths() -> list[str]:
            items = c.post("/api/images/query", json={}).json()["items"]
            return [i["rel_path"] for i in items]

        wait_for(lambda: paths() == ["before/a.png"] and not server.indexing)
        (root / "before").rename(root / "after")
        wait_for(lambda: paths() == ["after/a.png"])


def test_new_and_deleted_files_are_indexed_without_a_rescan(tmp_path: Path, config: Config):
    root = tmp_path / "library"
    root.mkdir()
    (root / "first.png").write_bytes(fox(1))
    app = create_app(root, config, watch=True, watch_debounce_ms=100, web_dir=None)
    with TestClient(app) as c:
        server = c.app.state.server  # type: ignore[attr-defined]

        def total() -> int:
            return c.get("/api/library").json()["total"]

        wait_for(lambda: total() == 1 and not server.indexing)
        assert c.get("/api/library").json()["watching"] is True

        (root / "sub").mkdir()
        (root / "sub" / "second.png").write_bytes(fox(2))
        wait_for(lambda: total() == 2)
        (root / "first.png").unlink()
        wait_for(lambda: total() == 1)
        paths = [i["rel_path"] for i in c.post("/api/images/query", json={}).json()["items"]]
        assert paths == ["sub/second.png"]
        (root / "ignored.txt").write_text("not an image")
    assert not server.watching  # stopped with the app


def test_a_change_during_a_run_queues_one_more_run(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "library"
    root.mkdir()
    app = create_app(root, config, index_on_start=False, web_dir=None)
    with TestClient(app) as c:
        server = c.app.state.server  # type: ignore[attr-defined]
        runs, release = [], threading.Event()

        def slow_run(**_kwargs):
            runs.append(time.monotonic())
            release.wait(5)

        monkeypatch.setattr(server.indexer, "run", slow_run)
        server.request_index()
        wait_for(lambda: len(runs) == 1)
        server.request_index()  # while running: queued, not dropped
        server.request_index()  # and not queued twice
        release.set()
        wait_for(lambda: not server.indexing)
        assert len(runs) == 2


def test_watching_never_writes_to_the_library(tmp_path: Path, config: Config):
    root = tmp_path / "library"
    root.mkdir()
    (root / "a.png").write_bytes(fox(1))
    os.utime(root / "a.png", (1_790_000_000, 1_790_000_000))
    before = sorted((p.name, p.stat().st_mtime_ns) for p in root.iterdir())
    app = create_app(root, config, watch=True, watch_debounce_ms=100, web_dir=None)
    with TestClient(app) as c:
        server = c.app.state.server  # type: ignore[attr-defined]
        wait_for(lambda: server.last_finished_at is not None and not server.indexing)
    assert sorted((p.name, p.stat().st_mtime_ns) for p in root.iterdir()) == before
