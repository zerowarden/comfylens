import io
import json
import zipfile
from pathlib import Path

import pytest
from conftest import golden_png, png_with_text, txt2img_png

from comfylens.collection.archive import (
    MANIFEST,
    InvalidArchive,
    export_zip,
    import_zip,
)
from comfylens.collection.drafts import build_draft
from comfylens.collection.models import PromptSettings, SavedLora
from comfylens.collection.store import CollectionStore, PromptData
from comfylens.config import Config

ATTEMPT = "a" * 32


def filled(directory: Path, config: Config) -> CollectionStore:
    store = CollectionStore(directory)
    golden = build_draft(golden_png(), store, config)["original"]["content_hash"]
    plain = build_draft(png_with_text({}), store, config)["original"]["content_hash"]
    store.create(
        PromptData(
            title="Golden",
            positive="a golden hour portrait",
            negative="blurry",
            notes="try at 1.5 MP",
            source_url="https://example.com/x",
            model_family="qwen-image-2.1",
            tags=["portrait", "warm"],
            settings=PromptSettings(
                steps=20, loras=[SavedLora(name="fox", strength_model=0.8)]
            ).model_dump(),
            references=[golden, plain],
            attempts=[ATTEMPT],
        )
    )
    store.create(
        PromptData(title="Text only", positive="a cat", settings=PromptSettings().model_dump())
    )
    build_draft(txt2img_png(3), store, config)  # a draft never saved: not exported
    return store


def exported(store: CollectionStore) -> bytes:
    buf = io.BytesIO()
    export_zip(store, buf)
    return buf.getvalue()


def comparable(store: CollectionStore) -> list[dict]:
    prompts, _ = store.export_rows()
    return prompts


def test_round_trip(tmp_path: Path, config: Config):
    source = filled(tmp_path / "a", config)
    archive = exported(source)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        names = sorted(z.namelist())
        assert names[0] == MANIFEST and len(names) == 3  # two referenced images only
        assert all(z.getinfo(n).compress_type == zipfile.ZIP_STORED for n in names[1:])

    target = CollectionStore(tmp_path / "b")
    stats = import_zip(target, io.BytesIO(archive))
    assert (stats.added, stats.skipped, stats.images) == (2, 0, 2)
    assert comparable(target) == comparable(source)

    # Reviewed absolute values, independent of export_rows: a systematic marshalling bug must
    # not round-trip cleanly.
    by_title = {p["title"]: p for p in target.summaries()}
    assert set(by_title) == {"Golden", "Text only"}
    golden = target.get(by_title["Golden"]["id"])
    assert golden is not None
    assert (golden["positive"], golden["negative"], golden["model_family"]) == (
        "a golden hour portrait",
        "blurry",
        "qwen-image-2.1",
    )
    assert golden["tags"] == ["portrait", "warm"]
    assert golden["settings"]["steps"] == 20
    assert golden["settings"]["loras"] == [
        {"name": "fox", "strength_model": 0.8, "strength_clip": None}
    ]
    assert target.prompts_for_hash(ATTEMPT) == [(by_title["Golden"]["id"], "Golden", "attempt")]

    restored = target.get(target.summaries(q="Golden")[0]["id"])
    assert restored is not None
    for image in restored["images"]:
        if image["role"] == "reference":
            found = target.original(image["content_hash"])
            assert found is not None
            original = source.original(image["content_hash"])
            assert original is not None
            assert found["path"].read_bytes() == original["path"].read_bytes()
    assert restored["images"][0]["has_workflow"]
    assert target.saved_hashes() == source.saved_hashes()

    again = import_zip(target, io.BytesIO(archive))
    assert (again.added, again.skipped) == (0, 2)
    assert len(target.summaries()) == 2


def test_import_merges_into_an_existing_collection(tmp_path: Path, config: Config):
    archive = exported(filled(tmp_path / "a", config))
    target = CollectionStore(tmp_path / "b")
    target.create(PromptData(title="Mine", positive="already here"))
    assert import_zip(target, io.BytesIO(archive)).added == 2
    assert {p["title"] for p in target.summaries()} == {"Mine", "Golden", "Text only"}


def rewrite(archive: bytes, change) -> bytes:
    """The archive with its manifest passed through `change`, other members copied."""
    src = zipfile.ZipFile(io.BytesIO(archive))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == MANIFEST:
                data = json.dumps(change(json.loads(data))).encode()
            z.writestr(info, data)
    return out.getvalue()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda m: {**m, "format": "something-else"}, "not a comfylens collection"),
        (lambda m: {**m, "version": 99}, "version 99"),
        (lambda m: {**m, "prompts": [{"title": "no uid"}]}, "manifest is invalid"),
        (
            lambda m: {**m, "originals": [{**m["originals"][0], "content_hash": "f" * 32}]},
            "is missing",
        ),
        (
            lambda m: {**m, "originals": [{**m["originals"][0], "format": "webp"}]},
            "is missing",  # looked up under the wrong extension
        ),
    ],
)
def test_rejects_bad_manifests(tmp_path: Path, config: Config, change, message):
    archive = rewrite(exported(filled(tmp_path / "a", config)), change)
    target = CollectionStore(tmp_path / "b")
    with pytest.raises(InvalidArchive, match=message):
        import_zip(target, io.BytesIO(archive))
    assert target.summaries() == []


def test_rejects_tampered_images_and_non_zips(tmp_path: Path, config: Config):
    archive = exported(filled(tmp_path / "a", config))
    src = zipfile.ZipFile(io.BytesIO(archive))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for info in src.infolist():
            data = src.read(info)
            z.writestr(info, data if info.filename == MANIFEST else data + b"x")
    target = CollectionStore(tmp_path / "b")
    with pytest.raises(InvalidArchive, match="does not match its hash"):
        import_zip(target, io.BytesIO(out.getvalue()))
    with pytest.raises(InvalidArchive, match="not a zip"):
        import_zip(target, io.BytesIO(b"plain text"))
    assert target.summaries() == []


def test_bad_prompt_imports_nothing(tmp_path: Path, config: Config):
    def bad_second(m: dict) -> dict:
        m["prompts"][1]["tags"] = ["a,b"]  # passes the schema, fails the store
        return m

    archive = rewrite(exported(filled(tmp_path / "a", config)), bad_second)
    target = CollectionStore(tmp_path / "b")
    with pytest.raises(InvalidArchive, match="prompt in the archive is invalid"):
        import_zip(target, io.BytesIO(archive))
    assert target.summaries() == []
