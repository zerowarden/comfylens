import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
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
    def from_config(
        cls, extensions: Sequence[str], exclude_globs: Sequence[str]
    ) -> PathRules:
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
    rules = PathRules.from_config(extensions, exclude_globs)
    result = ScanResult([], 0)
    seen_dirs: set[tuple[int, int]] = set()
    if follow_symlinks:  # a symlink to the root itself must not walk the library again
        root_stat = root.stat()
        seen_dirs.add((root_stat.st_dev, root_stat.st_ino))

    def walk(directory: Path, rel: str) -> Iterator[FileStat]:
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return
        for entry in sorted(entries, key=lambda e: e.name):
            rel_path = f"{rel}{entry.name}"
            try:
                rel_path.encode("utf-8")
            except UnicodeEncodeError:
                result.skipped_names += 1
                continue
            path = PurePosixPath(rel_path)
            try:
                if entry.is_dir(follow_symlinks=follow_symlinks):
                    if rules.is_pruned(path):
                        continue
                    if follow_symlinks:  # guard against symlink loops
                        st = entry.stat()
                        if (st.st_dev, st.st_ino) in seen_dirs:
                            continue
                        seen_dirs.add((st.st_dev, st.st_ino))
                    yield from walk(Path(entry.path), f"{rel_path}/")
                elif (
                    entry.is_file(follow_symlinks=follow_symlinks)
                    and rules.is_image(entry.name)
                    and not rules.is_excluded(path)
                ):
                    st = entry.stat(follow_symlinks=follow_symlinks)
                    yield FileStat(rel_path, st.st_size, st.st_mtime_ns)
            except OSError:
                continue  # vanished or unreadable entry

    result.files = list(walk(root, ""))
    return result
