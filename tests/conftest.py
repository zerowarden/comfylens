import io
import json
import os
import shutil
import struct
import time
import zlib
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from comfylens.api.server import Server
from comfylens.collection.store import CollectionStore
from comfylens.config import Config, build_config
from comfylens.db.connection import connect_readonly
from comfylens.index import file_ops
from comfylens.paths import catalog_path

GOLDEN = Path(__file__).parent / "fixtures" / "golden"


@pytest.fixture
def config() -> Config:
    return build_config({})


@pytest.fixture
def store(tmp_path: Path) -> CollectionStore:
    return CollectionStore(tmp_path / "collection")


@pytest.fixture(autouse=True)
def _isolated_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory):
    # Tests never touch the developer's own config, catalogs or thumbnail cache.
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(var, str(tmp_path_factory.mktemp(var.lower())))


@pytest.fixture(autouse=True)
def trash_dir(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Where trashed files go. send2trash reads XDG_DATA_HOME once, at import, so it is replaced
    outright: no test may ever move a file into the developer's own trash."""
    trash = tmp_path_factory.mktemp("trash")

    def fake_send2trash(path: str) -> None:
        shutil.move(path, trash / f"{len(os.listdir(trash))}-{os.path.basename(path)}")

    monkeypatch.setattr(file_ops, "send2trash", fake_send2trash)
    return trash


@pytest.fixture
def utc(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Day buckets and filename timestamps use the local time zone; pin it so expected dates
    hold everywhere."""
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def server_of(client: TestClient) -> Server:
    return client.app.state.server  # type: ignore[attr-defined]


def ids_by_path(client: TestClient) -> dict[str, int]:
    """Catalog ids by relative path, as the grid lists them."""
    items = client.post("/api/images/query", json={"limit": 100}).json()["items"]
    return {i["rel_path"]: i["id"] for i in items}


def png_with_text(texts: dict[str, Any], size: tuple[int, int] = (32, 32)) -> bytes:
    info = PngInfo()
    for key, value in texts.items():
        info.add_text(key, value if isinstance(value, str) else json.dumps(value))
    buf = io.BytesIO()
    Image.new("RGB", size, (40, 80, 120)).save(buf, "PNG", pnginfo=info)
    return buf.getvalue()


def chunk(ctype: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(ctype + data)
    return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)


def ihdr(width: int, height: int) -> bytes:
    return chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))


def load_golden(name: str) -> dict[str, Any]:
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))


def golden_png(size: tuple[int, int] = (32, 32)) -> bytes:
    """The golden Qwen Image 2.1 graph in a synthetic PNG."""
    texts = {
        "prompt": load_golden("sample_qwen21.prompt.json"),
        "workflow": load_golden("sample_qwen21.workflow.json"),
    }
    return png_with_text(texts, size)


def txt2img_png(seed: int, size: tuple[int, int] = (16, 16)) -> bytes:
    from graph_builder import basic_txt2img

    g = basic_txt2img()
    g.prompt["7"]["inputs"]["seed"] = seed
    return png_with_text({"prompt": g.prompt}, size)


def flux(seed: int, prompt: str = "", lora: float | None = None, *, patch: bool = False) -> bytes:
    """A txt2img graph with the given seed and prompt; an optional LoRA and TeaCache patch."""
    from graph_builder import basic_txt2img

    g = basic_txt2img()
    g.prompt["7"]["inputs"]["seed"] = seed
    if prompt:
        g.prompt["4"]["inputs"]["text"] = prompt
    if lora is not None:
        g.node(
            "20", "LoraLoaderModelOnly", lora_name="fox.safetensors", strength_model=lora,
            model=("1", 0),
        )  # fmt: skip
        g.prompt["7"]["inputs"]["model"] = ["20", 0]
    if patch:
        g.node("21", "TeaCache", rel_l1_thresh=0.4, model=g.prompt["7"]["inputs"]["model"])
        g.prompt["7"]["inputs"]["model"] = ["21", 0]
    return png_with_text({"prompt": g.prompt}, (16, 24))


# A minimal ComfyUI API prompt, as the metadata tests embed it.
API_PROMPT = {"3": {"class_type": "KSampler", "inputs": {"seed": 1}}}
API_TEXT = json.dumps(API_PROMPT)


def jpeg_segment(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + (len(payload) + 2).to_bytes(2) + payload


def library_snapshot(root: Path, *, relative: bool = False) -> dict[str, tuple[int, int]]:
    """(mtime_ns, size) per path, to prove an operation wrote nothing inside the library."""
    paths = [root, *sorted(root.rglob("*"))]
    key = (lambda p: str(p.relative_to(root))) if relative else str
    return {key(p): (p.stat().st_mtime_ns, p.stat().st_size) for p in paths}


def catalog_rows(root: Path, sql: str, *params: Any) -> list[tuple[Any, ...]]:
    conn = connect_readonly(catalog_path(root))
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def write_file(root: Path, rel: str, data: bytes, mtime_s: float | None = None) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if mtime_s is not None:
        os.utime(path, (mtime_s, mtime_s))
    return path


def wait_for(condition: Callable[[], bool], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError
        time.sleep(0.02)
