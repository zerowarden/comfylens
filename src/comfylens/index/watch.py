"""Watch mode: index the library whenever image files appear, change or disappear.

Reads change notifications only; like the indexer, it never writes inside the library.
"""

import threading
from collections.abc import Callable
from pathlib import Path, PurePosixPath

import watchfiles

from comfylens.config import IndexConfig

# Wait until the library has been quiet this long: ComfyUI may write several files of a batch.
DEBOUNCE_MS = 2000


class LibraryWatcher:
    def __init__(
        self,
        root: Path,
        config: IndexConfig,
        on_change: Callable[[], None],
        *,
        debounce_ms: int = DEBOUNCE_MS,
    ) -> None:
        self.root = root.resolve()
        self.on_change = on_change
        self.debounce_ms = debounce_ms
        self._extensions = tuple(e.lower() for e in config.extensions)
        self._globs = config.exclude_globs
        self._prune = [g[:-3] for g in config.exclude_globs if g.endswith("/**")]
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="library-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def relevant(self, _change: watchfiles.Change, path: str) -> bool:
        """A path whose change the scanner could reflect: an image file it would index, or a
        directory that holds one. A moved or renamed folder changes the relative path of
        every image below it, so directory events must count even without an extension."""
        try:
            rel = PurePosixPath(Path(path).relative_to(self.root).as_posix())
        except ValueError:
            return False
        parents = [rel.parents[i] for i in range(len(rel.parents) - 1)]
        if any(p.full_match(g) for p in parents for g in self._prune):
            return False
        if any(rel.full_match(g) for g in (*self._globs, *self._prune)):
            return False
        if path.lower().endswith(self._extensions):
            return True
        return Path(path).is_dir() or not Path(path).suffix

    def _run(self) -> None:
        for _changes in watchfiles.watch(
            self.root,
            watch_filter=self.relevant,
            debounce=self.debounce_ms,
            stop_event=self._stop,
            raise_interrupt=False,
        ):
            self.on_change()
