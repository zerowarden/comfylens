import sqlite3
import time
from pathlib import Path

import pytest

from comfylens.collection.store import (
    GC_GRACE_SECONDS,
    MIGRATIONS,
    CollectionStore,
    CollectionUnavailable,
    InvalidInput,
    PromptData,
    UnknownOriginal,
    normalize_tags,
)

H1, H2, H3 = "1" * 32, "2" * 32, "3" * 32


@pytest.fixture
def store(tmp_path: Path) -> CollectionStore:
    return CollectionStore(tmp_path / "collection")


def original(store: CollectionStore, data: bytes = b"png bytes") -> str:
    return store.put_original(data, "png", 16, 16, '{"1": {}}', None)


def user_version(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def test_migrates_once_and_reopens(tmp_path: Path):
    store = CollectionStore(tmp_path / "c")
    assert user_version(store.path) == len(MIGRATIONS) == 1
    prompt_id = store.create(PromptData(title="kept", positive="a fox"))
    again = CollectionStore(tmp_path / "c")
    assert (again.get(prompt_id) or {})["title"] == "kept"


def test_newer_store_is_refused_and_left_alone(tmp_path: Path):
    store = CollectionStore(tmp_path / "c")
    store.create(PromptData(title="mine", positive="a fox"))
    conn = sqlite3.connect(store.path)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    before = store.path.read_bytes()
    with pytest.raises(CollectionUnavailable, match="schema 99"):
        CollectionStore(tmp_path / "c")
    assert store.path.read_bytes() == before


def test_unreadable_store_is_refused(tmp_path: Path):
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "collection.sqlite").write_bytes(b"not a database" * 100)
    with pytest.raises(CollectionUnavailable):
        CollectionStore(tmp_path / "c")


def test_create_get_update_delete(store: CollectionStore):
    ref = original(store)
    prompt_id = store.create(
        PromptData(
            title="  Fox  ",
            positive="a red fox",
            negative="blurry",
            tags=[" Moody ", "moody", "Snow"],
            settings={"steps": 20},
            references=[ref],
            attempts=[H1, ref],  # a reference is never also an attempt
        )
    )
    got = store.get(prompt_id)
    assert got is not None
    assert got["title"] == "Fox"
    assert got["tags"] == ["moody", "snow"]
    assert got["settings"] == {"steps": 20}
    assert [(i["content_hash"], i["role"]) for i in got["images"]] == [
        (ref, "reference"),
        (H1, "attempt"),
    ]
    assert got["images"][0]["has_workflow"] and got["images"][0]["format"] == "png"
    assert got["images"][1]["format"] is None

    assert store.update(prompt_id, PromptData(title="Fox 2", positive="a red fox", tags=["x"]))
    got = store.get(prompt_id)
    assert got is not None
    assert got["title"] == "Fox 2" and got["tags"] == ["x"]
    # References are replaced; attempts stay.
    assert [i["role"] for i in got["images"]] == ["attempt"]
    assert not store.update(999, PromptData(title="t", positive=""))

    assert store.delete(prompt_id)
    assert store.get(prompt_id) is None
    assert not store.delete(prompt_id)


def test_validation(store: CollectionStore):
    with pytest.raises(InvalidInput, match="title"):
        store.create(PromptData(title="   ", positive="x"))
    with pytest.raises(InvalidInput, match="not a content hash"):
        store.create(PromptData(title="t", positive="x", attempts=["../etc"]))
    with pytest.raises(UnknownOriginal):
        store.create(PromptData(title="t", positive="x", references=[H2]))
    with pytest.raises(InvalidInput):
        normalize_tags(["a,b"])
    assert store.summaries() == []  # nothing half-written


def test_links_and_saved_hashes(store: CollectionStore):
    ref = original(store)
    a = store.create(PromptData(title="a", positive="a  red fox", references=[ref]))
    b = store.create(PromptData(title="b", positive="a red fox"))
    assert store.saved_hashes() == {ref}
    assert store.link_attempts(b, [H1, H2, H1]) == 2
    assert store.link_attempts(b, [H1]) == 0
    assert store.link_attempts(999, [H1]) is None
    assert store.saved_hashes() == {ref, H1, H2}
    assert store.unlink_attempts(b, [H2, ref])
    assert store.saved_hashes() == {ref, H1}

    links = store.links(a)
    assert links is not None and links.hashes == {ref}
    # Whitespace variants of a prompt share a key.
    assert links.key is not None and links.key == store.links(b).key  # type: ignore[union-attr]
    assert store.prompts_for_key(links.key) == [(b, "b"), (a, "a")]
    assert store.prompts_for_hash(ref) == [(a, "a", "reference")]
    assert set(store.all_links()) == {a, b}


def test_revision_moves_on_every_write(store: CollectionStore):
    r0 = store.revision()
    prompt_id = store.create(PromptData(title="a", positive="x"))
    r1 = store.revision()
    store.link_attempts(prompt_id, [H3])
    assert r0 < r1 < store.revision()


def test_summaries_filters(store: CollectionStore):
    ref = original(store)
    store.create(PromptData(title="Fox", positive="a fox", tags=["snow"], model_family="flux"))
    store.create(PromptData(title="Owl", positive="an owl", notes="100% night", references=[ref]))
    assert [r["title"] for r in store.summaries()] == ["Owl", "Fox"]
    assert [r["title"] for r in store.summaries(q="snow")] == ["Fox"]  # tags match q
    assert [r["title"] for r in store.summaries(q="100%")] == ["Owl"]
    assert store.summaries(q="_") == []  # LIKE wildcards are literal
    assert [r["title"] for r in store.summaries(tag="snow")] == ["Fox"]
    assert [r["title"] for r in store.summaries(family="flux")] == ["Fox"]
    owl = store.summaries(q="owl")[0]
    assert owl["cover_hash"] == ref and owl["reference_count"] == 1 and owl["tags"] == []
    assert store.facets() == ([("snow", 1)], [("flux", 1)])


def test_put_original_is_idempotent(store: CollectionStore):
    h = original(store)
    assert original(store) == h
    found = store.original(h)
    assert found is not None and found["path"].read_bytes() == b"png bytes"
    assert store.original("f" * 32) is None
    assert store.original("../x") is None


def test_garbage_collection(store: CollectionStore):
    used = original(store, b"used")
    orphan = original(store, b"orphan")
    store.create(PromptData(title="t", positive="x", references=[used]))
    assert store.collect_garbage() == 0  # still within the grace period
    later = time.time() + GC_GRACE_SECONDS + 10
    assert store.collect_garbage(now=later) == 1
    assert store.original(orphan) is None
    assert store.original(used) is not None
    assert not any(store.originals_dir.rglob(f"{orphan}.*"))
