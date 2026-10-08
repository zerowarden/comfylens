import contextlib
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class FileStat:
    rel_path: str  # POSIX, relative to the library root
    size: int
    mtime_ns: int


@dataclass(slots=True)
class ScanResult:
    files: list[FileStat]
    skipped_names: int  # names that are not valid UTF-8 and cannot be stored


@dataclass(frozen=True, slots=True)
class PathRules:
    """Which paths the scanner indexes. The watcher decides the same way, so it shares this."""

    extensions: tuple[str, ...]
    exclude_globs: tuple[str, ...]
    # A glob ending in "/**" excludes a whole directory when its prefix matches the directory.
    prune_globs: tuple[str, ...]

    @classmethod
    def from_config(cls, extensions: Sequence[str], exclude_globs: Sequence[str]) -> PathRules:
        return cls(
            tuple(e.lower() for e in extensions),
            tuple(exclude_globs),
            tuple(g[:-3] for g in exclude_globs if g.endswith("/**")),
        )

    def is_image(self, name: str) -> bool:
        return name.lower().endswith(self.extensions)

    def is_excluded(self, path: PurePosixPath) -> bool:
        return any(path.full_match(g) for g in self.exclude_globs)

    def is_pruned(self, path: PurePosixPath) -> bool:
        return any(path.full_match(g) for g in self.prune_globs)

    def is_ignored(self, path: PurePosixPath) -> bool:
        return self.is_excluded(path) or self.is_pruned(path)


def scan(
    root: Path, extensions: Sequence[str], exclude_globs: Sequence[str], follow_symlinks: bool
) -> ScanResult:
    walker = _Walker(PathRules.from_config(extensions, exclude_globs), follow_symlinks)
    if follow_symlinks:  # a symlink to the root itself must not walk the library again
        walker.first_visit(root.stat())
    files = list(walker.walk(root, ""))
    return ScanResult(files, walker.skipped_names)


@dataclass(slots=True)
class _Walker:
    rules: PathRules
    follow_symlinks: bool
    seen_dirs: set[tuple[int, int]] = field(default_factory=set)  # (device, inode)
    skipped_names: int = 0

    def walk(self, directory: Path, rel: str) -> Iterator[FileStat]:
        """Every indexed image below `directory`, in name order."""
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            return
        for entry in entries:
            rel_path = f"{rel}{entry.name}"
            if not _is_utf8(rel_path):
                self.skipped_names += 1
                continue
            with contextlib.suppress(OSError):  # a vanished or unreadable entry
                yield from self._visit(entry, rel_path)

    def _visit(self, entry: os.DirEntry[str], rel_path: str) -> Iterator[FileStat]:
        path = PurePosixPath(rel_path)
        if entry.is_dir(follow_symlinks=self.follow_symlinks):
            if not self.rules.is_pruned(path) and self._first_visit_of(entry):
                yield from self.walk(Path(entry.path), f"{rel_path}/")
        elif (
            entry.is_file(follow_symlinks=self.follow_symlinks)
            and self.rules.is_image(entry.name)
            and not self.rules.is_excluded(path)
        ):
            st = entry.stat(follow_symlinks=self.follow_symlinks)
            yield FileStat(rel_path, st.st_size, st.st_mtime_ns)

    def _first_visit_of(self, entry: os.DirEntry[str]) -> bool:
        """Always, unless symlinks are followed: then a directory is walked once, so a symlink
        loop ends."""
        return not self.follow_symlinks or self.first_visit(entry.stat())

    def first_visit(self, st: os.stat_result) -> bool:
        """Records the directory as seen; whether it was new."""
        key = (st.st_dev, st.st_ino)
        new = key not in self.seen_dirs
        self.seen_dirs.add(key)
        return new


def _is_utf8(name: str) -> bool:
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True
