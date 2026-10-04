import io
from pathlib import Path

import pytest
from conftest import golden_png, png_with_text, txt2img_png
from graph_builder import basic_txt2img
from PIL import Image

from comfylens.collection.drafts import (
    UnsupportedImage,
    build_draft,
    rebuild_thumbnail,
    suggest_title,
    text_draft,
)
from comfylens.collection.store import CollectionStore
from comfylens.config import Config
from comfylens.paths import thumb_path, thumbs_dir


@pytest.fixture
def store(tmp_path: Path) -> CollectionStore:
    return CollectionStore(tmp_path / "collection")


def test_comfyui_image(store: CollectionStore, config: Config):
    draft = build_draft(golden_png(), store, config)
    assert draft["metadata"] == "comfyui"
    assert draft["model_family"] == "qwen-image-2.1"
    assert draft["positive"]
    original = draft["original"]
    assert original["format"] == "png" and original["has_workflow"]
    assert thumb_path(thumbs_dir(), original["content_hash"]).is_file()
    assert store.original_metadata(original["content_hash"])[0] is not None  # type: ignore[index]


def test_settings_and_loras(store: CollectionStore, config: Config):
    g = basic_txt2img()
    g.node(
        "20", "LoraLoaderModelOnly", lora_name="styles/fox.safetensors", strength_model=0.8,
        model=("1", 0),
    )  # fmt: skip
    g.prompt["7"]["inputs"]["model"] = ["20", 0]
    draft = build_draft(png_with_text({"prompt": g.prompt}), store, config)
    assert draft["title"] == "a red fox in the snow"
    assert draft["negative"] == "blurry"
    assert draft["settings"] == {
        "base_model": "flux1-dev",
        "seed": "42",
        "steps": 20,
        "cfg": 3.5,
        "sampler_name": "euler",
        "scheduler": "simple",
        "denoise": 1.0,
        "guidance": None,
        "shift": None,
        "loras": [{"name": "fox", "strength_model": 0.8, "strength_clip": None}],
    }


def test_no_metadata_and_webp(store: CollectionStore, config: Config):
    plain = build_draft(png_with_text({}), store, config)
    assert plain["metadata"] == "none" and plain["positive"] == "" and plain["title"] == "Untitled"
    assert not plain["original"]["has_workflow"]

    buf = io.BytesIO()
    Image.new("RGB", (20, 10), (1, 2, 3)).save(buf, "WEBP")
    webp = build_draft(buf.getvalue(), store, config)
    assert webp["metadata"] == "none"
    assert (webp["original"]["format"], webp["original"]["width"]) == ("webp", 20)


def test_rejects_other_bytes(store: CollectionStore, config: Config):
    with pytest.raises(UnsupportedImage):
        build_draft(b"not an image", store, config)
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, "GIF")
    with pytest.raises(UnsupportedImage):
        build_draft(buf.getvalue(), store, config)
    assert store.summaries() == []


def test_same_bytes_one_original(store: CollectionStore, config: Config):
    a = build_draft(txt2img_png(1), store, config)
    b = build_draft(txt2img_png(1), store, config)
    assert a["original"]["content_hash"] == b["original"]["content_hash"]
    assert len(list(store.originals_dir.rglob("*.png"))) == 1


def test_rebuild_thumbnail(store: CollectionStore, config: Config):
    h = build_draft(txt2img_png(2), store, config)["original"]["content_hash"]
    target = thumb_path(thumbs_dir(), h)
    target.unlink()
    assert rebuild_thumbnail(store, h, config)
    assert target.is_file()
    assert not rebuild_thumbnail(store, "0" * 32, config)


def test_titles():
    assert suggest_title("A fox. In snow") == "A fox"
    assert suggest_title("  \n") == "Untitled"
    assert suggest_title("cfg 0.8 weights stay whole. Second") == "cfg 0.8 weights stay whole"
    assert suggest_title("<lora:x:0.5> a heron, mist") == "a heron, mist"
    assert suggest_title("first line\nsecond line") == "first line"
    long = "word " * 30
    title = suggest_title(long)
    assert title.endswith("…") and len(title) <= 61 and not title[:-1].endswith(" ")
    assert text_draft("a cat")["title"] == "a cat"
