import os
from pathlib import Path

from comfylens.index.scanner import scan

EXTS = (".png", ".jpg", ".jpeg")
HIDDEN = ("**/.*/**",)


def touch(root: Path, rel: str, data: bytes = b"x") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def rels(root: Path, **kwargs) -> list[str]:
    options = {"extensions": EXTS, "exclude_globs": HIDDEN, "follow_symlinks": False} | kwargs
    return [f.rel_path for f in scan(root, **options).files]


def test_recursive_case_insensitive_extensions(tmp_path: Path):
    for rel in ("a.png", "b.JPG", "c.Jpeg", "d.webp", "notes.txt", "sub/deeper/e.png"):
        touch(tmp_path, rel)
    assert rels(tmp_path) == ["a.png", "b.JPG", "c.Jpeg", "sub/deeper/e.png"]


def test_size_and_mtime(tmp_path: Path):
    path = touch(tmp_path, "a.png", b"12345")
    os.utime(path, ns=(1, 1_790_649_651_329_171_267))
    (stat,) = scan(tmp_path, EXTS, HIDDEN, False).files
    assert (stat.size, stat.mtime_ns) == (5, 1_790_649_651_329_171_267)


def test_hidden_directories_are_excluded(tmp_path: Path):
    for rel in (".trash/a.png", "x/.cache/b.png", "x/c.png", ".hidden-file.png"):
        touch(tmp_path, rel)
    assert rels(tmp_path) == [".hidden-file.png", "x/c.png"]


def test_file_globs(tmp_path: Path):
    for rel in ("keep.png", "skip_preview.png", "sub/skip_preview.png"):
        touch(tmp_path, rel)
    assert rels(tmp_path, exclude_globs=("**/*_preview.png",)) == ["keep.png"]


def test_symlinks_not_followed_by_default(tmp_path: Path):
    outside = tmp_path / "outside"
    touch(outside, "o.png")
    library = tmp_path / "library"
    touch(library, "real.png")
    (library / "linked_dir").symlink_to(outside)
    (library / "linked_file.png").symlink_to(outside / "o.png")
    assert rels(library) == ["real.png"]
    assert rels(library, follow_symlinks=True) == [
        "linked_dir/o.png",
        "linked_file.png",
        "real.png",
    ]


def test_symlink_loop_is_cut(tmp_path: Path):
    touch(tmp_path, "a/x.png")
    (tmp_path / "a" / "loop").symlink_to(tmp_path / "a")
    assert rels(tmp_path, follow_symlinks=True) == ["a/x.png"]


def test_symlink_to_the_library_root_is_cut(tmp_path: Path):
    touch(tmp_path, "a.png")
    (tmp_path / "again").symlink_to(tmp_path)
    assert rels(tmp_path, follow_symlinks=True) == ["a.png"]


def test_non_utf8_names_are_skipped(tmp_path: Path):
    touch(tmp_path, "ok.png")
    with open(os.path.join(os.fsencode(tmp_path), b"bad\xff.png"), "wb") as f:
        f.write(b"x")
    result = scan(tmp_path, EXTS, HIDDEN, False)
    assert [f.rel_path for f in result.files] == ["ok.png"]
    assert result.skipped_names == 1
