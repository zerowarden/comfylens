import io
import json
import os
import struct
import time
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from comfylens.config import Config, build_config

GOLDEN = Path(__file__).parent / "fixtures" / "golden"


@pytest.fixture
def config() -> Config:
    return build_config({})


@pytest.fixture(autouse=True)
def _isolated_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory):
    # Tests never touch the developer's own config, catalogs or thumbnail cache.
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(var, str(tmp_path_factory.mktemp(var.lower())))


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
