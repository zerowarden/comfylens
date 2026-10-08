import os
import shutil
from pathlib import Path

import pytest
from conftest import catalog_rows as rows
from conftest import golden_png, library_snapshot, png_with_text, txt2img_png, write_file

from comfylens import version
from comfylens.config import Config, build_config
from comfylens.index import indexer as indexer_module
from comfylens.index import worker as worker_module
from comfylens.index.indexer import Indexer, IndexResult, IndexStatus, UnsafeLocation
from comfylens.index.lock import IndexLock, IndexLocked
from comfylens.paths import catalog_path, lock_path, thumb_path, thumbs_dir

write = write_file


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    write(root, "golden.png", golden_png(), 1_790_000_000)
    write(root, "sub/fox.png", txt2img_png(1), 1_790_000_600)
    write(root, "plain.png", png_with_text({}), 1_790_001_200)
    return root


def run(root: Path, config: Config, **kwargs) -> IndexResult:
    workers = kwargs.pop("workers", 1)
    return Indexer(root, config, workers=workers).run(**kwargs)


def test_first_index(library: Path, config: Config):
    result = run(library, config)
    assert (result.scanned, result.new, result.errors, result.thumbnails_written) == (3, 3, 0, 3)
    files = rows(library, "SELECT rel_path, status, format, width, height, generated_at FROM files")
    assert sorted(files) == [
        ("golden.png", "ok", "png", 32, 32, 1_790_000_000),
        ("plain.png", "no_metadata", "png", 32, 32, 1_790_001_200),
        ("sub/fox.png", "ok", "png", 16, 16, 1_790_000_600),
    ]
    for (content_hash,) in rows(library, "SELECT content_hash FROM files"):
        assert thumb_path(thumbs_dir(), content_hash).is_file()
    assert rows(library, "SELECT model_family FROM generations ORDER BY 1") == [
        ("flux",),
        ("qwen-image-2.1",),
    ]


def test_modified_deleted_and_renamed_files(library: Path, config: Config):
    run(library, config)
    write(library, "sub/fox.png", txt2img_png(2), 1_790_009_999)
    (library / "plain.png").unlink()
    (library / "golden.png").rename(library / "renamed.png")

    result = run(library, config)
    assert (result.new, result.changed, result.deleted, result.unchanged) == (1, 1, 2, 0)
    assert result.thumbnails_written == 1  # the renamed file reuses its thumbnail
    assert rows(library, "SELECT rel_path FROM files ORDER BY 1") == [
        ("renamed.png",),
        ("sub/fox.png",),
    ]
    assert rows(library, "SELECT seed FROM generations g JOIN files f ON f.id = g.file_id"
                " WHERE rel_path = 'sub/fox.png'") == [("2",)]  # fmt: skip
    # Child rows of deleted files go with them.
    assert rows(library, "SELECT COUNT(*) FROM raw_metadata") == [(2,)]
    assert rows(library, "SELECT COUNT(DISTINCT file_id) FROM nodes") == [(2,)]


def test_unchanged_files_are_skipped(
    library: Path, config: Config, monkeypatch: pytest.MonkeyPatch
):
    run(library, config)

    def fail(*_args):
        raise AssertionError("an unchanged file was read")

    monkeypatch.setattr(indexer_module, "process_file", fail)
    result = run(library, config)
    assert (result.unchanged, result.new, result.changed, result.reextracted) == (3, 0, 0, 0)


def test_full_rereads_everything(library: Path, config: Config):
    run(library, config)
    result = run(library, config, full=True)
    assert (result.changed, result.unchanged, result.thumbnails_written) == (3, 0, 0)


def test_extractor_bump_reextracts_without_opening_images(
    library: Path, config: Config, monkeypatch: pytest.MonkeyPatch
):
    truncated = golden_png()[:-12]  # no IEND: a TRUNCATED warning from the reading stage
    write(library, "truncated.png", truncated)
    run(library, config)
    before = rows(library, "SELECT file_id, code FROM warnings ORDER BY 1, 2")

    def fail(*_args, **_kwargs):
        raise AssertionError("an image was opened")

    for module, name in (
        (indexer_module, "process_file"),
        (worker_module, "read_metadata"),
        (worker_module, "make_thumbnail"),
    ):
        monkeypatch.setattr(module, name, fail)
    monkeypatch.setattr(version, "EXTRACTOR_VERSION", version.EXTRACTOR_VERSION + 1)

    result = run(library, config)
    assert (result.reextracted, result.unchanged, result.errors) == (3, 4, 0)  # plain has no prompt
    assert rows(library, "SELECT value FROM meta WHERE key = 'extractor_version'") == [
        (str(version.EXTRACTOR_VERSION),)
    ]
    # Read-stage warnings stay; extraction warnings are replaced, not duplicated.
    assert rows(library, "SELECT file_id, code FROM warnings ORDER BY 1, 2") == before
    assert ("TRUNCATED",) in rows(library, "SELECT code FROM warnings")
    assert run(library, config).reextracted == 0


def test_config_change_reextracts(library: Path, config: Config):
    run(library, config)
    renamed = build_config(
        {"families": [{"name": "everything", "any": [{"class_regex": "KSampler"}]}]}
    )
    assert run(library, renamed).reextracted == 2
    assert rows(library, "SELECT DISTINCT model_family FROM generations") == [("everything",)]


def test_schema_change_rebuilds_and_keeps_thumbnails(
    library: Path, config: Config, monkeypatch: pytest.MonkeyPatch
):
    run(library, config)
    monkeypatch.setattr(version, "SCHEMA_VERSION", version.SCHEMA_VERSION + 1)
    result = run(library, config)
    assert (result.new, result.thumbnails_written) == (3, 0)


@pytest.mark.parametrize("workers", [1, 2])
def test_missing_thumbnails_of_unchanged_files_are_restored(
    library: Path, config: Config, workers: int
):
    run(library, config)
    catalog_before = rows(library, "SELECT * FROM files ORDER BY id")
    shutil.rmtree(thumbs_dir())  # the cache was cleared, or is new to this library

    result = run(library, config, workers=workers)
    assert (result.unchanged, result.changed, result.thumbnails_written) == (3, 0, 3)
    for (content_hash,) in rows(library, "SELECT content_hash FROM files"):
        assert thumb_path(thumbs_dir(), content_hash).is_file()
    assert rows(library, "SELECT * FROM files ORDER BY id") == catalog_before
    assert run(library, config).thumbnails_written == 0


def test_restoring_thumbnails_reads_no_metadata(
    library: Path, config: Config, monkeypatch: pytest.MonkeyPatch
):
    run(library, config)
    shutil.rmtree(thumbs_dir())

    def fail(*_args, **_kwargs):
        raise AssertionError("metadata was read again")

    monkeypatch.setattr(indexer_module, "process_file", fail)
    monkeypatch.setattr(worker_module, "read_metadata", fail)
    assert run(library, config).thumbnails_written == 3


def test_a_thumbnail_that_failed_when_read_is_not_retried(
    library: Path, config: Config, monkeypatch: pytest.MonkeyPatch
):
    write(library, "broken.png", b"\x89PNG\r\n\x1a\n garbage")  # THUMBNAIL_FAILED
    run(library, config)

    def fail(*_args):
        raise AssertionError("a known-bad image was decoded again")

    monkeypatch.setattr(worker_module, "make_thumbnail", fail)
    result = run(library, config)
    assert (result.thumbnails_written, result.thumbnails_failed) == (0, 0)


def test_a_failed_restore_is_counted_and_retried(
    library: Path, config: Config, monkeypatch: pytest.MonkeyPatch
):
    run(library, config)
    shutil.rmtree(thumbs_dir())

    def disk_full(*_args):
        raise OSError(28, "No space left on device")

    with monkeypatch.context() as m:
        m.setattr(worker_module, "make_thumbnail", disk_full)
        result = run(library, config)
    assert (result.thumbnails_written, result.thumbnails_failed) == (0, 3)
    assert rows(library, "SELECT COUNT(*) FROM warnings WHERE code = 'THUMBNAIL_FAILED'") == [(0,)]
    assert run(library, config).thumbnails_written == 3


def test_no_thumbnail_is_restored_from_content_that_changed_in_place(library: Path, config: Config):
    run(library, config)
    shutil.rmtree(thumbs_dir())
    (old_hash,) = rows(library, "SELECT content_hash FROM files WHERE rel_path = 'sub/fox.png'")[0]
    fox = library / "sub/fox.png"
    stat = fox.stat()
    other = txt2img_png(2)
    assert len(other) == stat.st_size  # same size and mtime: the index sees it as unchanged
    write(library, "sub/fox.png", other)
    os.utime(fox, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    result = run(library, config)
    assert (result.unchanged, result.thumbnails_written, result.thumbnails_failed) == (3, 2, 1)
    assert not thumb_path(thumbs_dir(), old_hash).exists()


def test_one_bad_file_does_not_stop_the_run(library: Path, config: Config):
    write(library, "broken.png", b"\x89PNG\r\n\x1a\n garbage")
    write(library, "fake.jpg", b"not a jpeg at all")
    result = run(library, config)
    assert (result.new, result.errors) == (5, 2)
    failed = rows(library, "SELECT rel_path, status, error FROM files WHERE status = 'error'")
    assert sorted(failed) == [
        ("broken.png", "error", "ValueError: PNG has no IHDR chunk"),
        ("fake.jpg", "error", "UnsupportedFormat: not a PNG or JPEG file"),
    ]
    codes = rows(library, "SELECT DISTINCT code FROM warnings w JOIN files f ON f.id = w.file_id"
                 " WHERE f.status = 'error'")  # fmt: skip
    assert codes == [("THUMBNAIL_FAILED",)]


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read any file")
def test_unreadable_file(library: Path, config: Config):
    path = write(library, "locked.png", golden_png())
    path.chmod(0)
    try:
        result = run(library, config)
    finally:
        path.chmod(0o644)
    assert result.errors == 1
    ((content_hash, error),) = rows(
        library, "SELECT content_hash, error FROM files WHERE rel_path = 'locked.png'"
    )
    assert content_hash == "" and error.startswith("PermissionError")


def test_seed_2_64_minus_1_round_trips(tmp_path: Path, config: Config):
    write(tmp_path / "lib", "big.png", txt2img_png(2**64 - 1))
    run(tmp_path / "lib", config)
    assert rows(tmp_path / "lib", "SELECT seed FROM generations") == [("18446744073709551615",)]
    assert rows(tmp_path / "lib", "SELECT seed FROM sampler_stages") == [("18446744073709551615",)]


def test_golden_rows(library: Path, config: Config):
    run(library, config)
    (file_id,) = rows(library, "SELECT id FROM files WHERE rel_path = 'golden.png'")[0]
    (gen,) = rows(
        library,
        "SELECT model_family, base_model, text_encoder, clip_type, vae, seed, steps, cfg,"
        " sampler_name, scheduler, denoise, guidance, shift, stage_count, latent_source,"
        " lora_stack_key FROM generations WHERE file_id = ?",
        file_id,
    )
    assert gen == (
        "qwen-image-2.1",
        "qwen_image_2.1_int8_convrot",
        "qwen3vl_8b_int8_convrot",
        "qwen_image",
        "qwen_image_2.1_vae_bf16",
        "898921074692413",
        25,
        2.0,
        "euler",
        "simple",
        0.97,
        None,
        None,
        1,
        "TextEncodeQwenImage21",
        "qwen2.1-anime2real-sunburst@1.13 + qwen2.1-lenovo-ultrareal@1.06",
    )
    loras = rows(
        library,
        "SELECT position, name, base_name, step, strength_model, reachable FROM loras"
        " WHERE file_id = ? ORDER BY reachable DESC, position",
        file_id,
    )
    assert loras == [
        (0, "qwen2.1-anime2real-sunburst", "qwen2.1-anime2real-sunburst", None, 1.13, 1),
        (1, "qwen2.1-lenovo-ultrareal", "qwen2.1-lenovo-ultrareal", None, 1.06, 1),
        (None, "qwen2.1-exampleV01_000004956", "qwen2.1-exampleV01", 4956, 0.97, 0),
    ]
    unreachable = rows(
        library, "SELECT node_id FROM nodes WHERE file_id = ? AND reachable = 0", file_id
    )
    assert sorted(unreachable) == [("25",), ("28",)]
    assert rows(library, "SELECT code, node_id FROM warnings WHERE file_id = ?", file_id) == [
        ("UNUSED_LORA", "25")
    ]
    (raw,) = rows(library, "SELECT sources, prompt_json IS NOT NULL, workflow_json IS NOT NULL,"
                  " other_json FROM raw_metadata WHERE file_id = ?", file_id)  # fmt: skip
    assert raw == ('{"prompt": "png:tEXt", "workflow": "png:tEXt"}', 1, 1, None)


def test_prompt_search_index(library: Path, config: Config):
    run(library, config)
    found = rows(
        library,
        "SELECT f.rel_path FROM prompts_fts JOIN files f ON f.id = prompts_fts.rowid"
        " WHERE prompts_fts MATCH 'fox'",
    )
    assert found == [("sub/fox.png",)]


def test_bulk_copy_is_flagged_then_cleared(tmp_path: Path, config: Config):
    root = tmp_path / "lib"
    for i in range(12):  # 12 distinct generations stamped within 1.2 s
        write(root, f"copy{i:02}.png", txt2img_png(100 + i), 1_790_000_000 + i * 0.1)
    result = run(root, config)
    assert [c.distinct_generations for c in result.clusters] == [12]
    assert rows(root, "SELECT COUNT(*) FROM files WHERE timestamp_suspect = 1") == [(12,)]
    assert rows(root, "SELECT COUNT(*) FROM warnings WHERE code = 'TIMESTAMP_SUSPECT'") == [(12,)]

    # Delete all but one: copy00 stays unchanged and unflagged by the reader, so only the
    # timestamp pass can clear it.
    for i in range(1, 12):
        (root / f"copy{i:02}.png").unlink()
    result = run(root, config)
    assert result.clusters == []
    assert rows(root, "SELECT COUNT(*) FROM files WHERE timestamp_suspect = 1") == [(0,)]
    assert rows(root, "SELECT COUNT(*) FROM warnings WHERE code = 'TIMESTAMP_SUSPECT'") == [(0,)]


def test_corrupt_catalog_is_rebuilt(library: Path, config: Config):
    run(library, config)
    catalog_path(library).write_bytes(b"not a database at all")
    result = run(library, config)
    assert (result.new, result.errors) == (3, 0)
    assert rows(library, "SELECT COUNT(*) FROM files") == [(3,)]


def test_suspect_message_follows_a_growing_cluster(tmp_path: Path, config: Config):
    root = tmp_path / "lib"
    for i in range(12):  # 12 distinct generations stamped within 1.2 s
        write(root, f"copy{i:02}.png", txt2img_png(100 + i), 1_790_000_000 + i * 0.1)
    run(root, config)
    file_id = rows(root, "SELECT id FROM files WHERE rel_path = 'copy00.png'")[0][0]
    (message,) = rows(
        root,
        "SELECT message FROM warnings WHERE file_id = ? AND code = 'TIMESTAMP_SUSPECT'",
        file_id,
    )[0]
    assert "of 12 distinct generations" in message

    write(root, "copy12.png", txt2img_png(200), 1_790_000_001.15)  # grows the same burst
    run(root, config)
    (message,) = rows(
        root,
        "SELECT message FROM warnings WHERE file_id = ? AND code = 'TIMESTAMP_SUSPECT'",
        file_id,
    )[0]
    assert "of 13 distinct generations" in message


def test_status_reports_progress(library: Path, config: Config):
    seen: list[IndexStatus] = []
    Indexer(library, config, workers=1, on_status=seen.append).run()
    states = [s.state for s in seen]
    assert states[0] == "scanning" and states[-1] == "idle"
    assert "processing" in states and "finalizing" in states
    finished = [s for s in seen if s.state == "finalizing"][-1]
    assert (finished.done, finished.total, finished.errors) == (3, 3, 0)


def test_process_pool_matches_inline(
    library: Path, config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    dumps = []
    for workers, data_home in ((1, "inline"), (2, "pool")):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / data_home))
        run(library, config, workers=workers)
        dumps.append(
            [
                rows(library, f"SELECT * FROM {table} ORDER BY 1, 2")
                for table in ("generations", "loras", "nodes", "warnings")
            ]
        )
    assert dumps[0] == dumps[1]


def test_reextraction_through_the_pool_matches_inline(
    library: Path, config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    dumps = []
    for workers, data_home in ((1, "inline"), (2, "pool")):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / data_home))
        run(library, config, workers=workers)
        original = version.EXTRACTOR_VERSION
        monkeypatch.setattr(version, "EXTRACTOR_VERSION", original + 1)
        result = run(library, config, workers=workers)
        monkeypatch.setattr(version, "EXTRACTOR_VERSION", original)
        assert (result.reextracted, result.changed, result.errors) == (2, 0, 0)
        dumps.append(
            [
                rows(library, f"SELECT * FROM {table} ORDER BY 1, 2")
                for table in ("generations", "loras", "nodes", "warnings")
            ]
        )
    assert dumps[0] == dumps[1]


def test_library_is_never_written(library: Path, config: Config):
    # Directory mtimes change when anything is created, renamed or deleted inside them.
    before = library_snapshot(library, relative=True)
    for kwargs in ({}, {"full": True}, {"reextract_all": True}, {"workers": 2, "full": True}):
        run(library, config, **kwargs)
    assert library_snapshot(library, relative=True) == before


def test_state_inside_the_library_is_refused(
    library: Path, config: Config, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(library / ".state"))
    with pytest.raises(UnsafeLocation):
        run(library, config)
    assert not (library / ".state").exists()


def test_second_writer_is_refused(library: Path, config: Config):
    with IndexLock(lock_path(library)), pytest.raises(IndexLocked, match=f"pid {os.getpid()}"):
        run(library, config)
    assert run(library, config).new == 3  # released


def test_every_warning_code_belongs_to_exactly_one_stage():
    from comfylens.warn import EXTRACTION_CODES, READ_CODES, Code

    assert EXTRACTION_CODES.isdisjoint(READ_CODES)
    # An unclassified code would be silently kept (or lost) across re-extraction.
    assert set(Code) == EXTRACTION_CODES | READ_CODES
