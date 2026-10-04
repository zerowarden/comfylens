"""One writer per library: an flock on index.lock."""

import fcntl
import os
from pathlib import Path
from types import TracebackType


class IndexLocked(RuntimeError):
    """Another process is indexing this library."""


class IndexLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None

    def __enter__(self) -> IndexLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder = os.read(fd, 32).decode(errors="replace").strip() or "unknown"
            os.close(fd)
            raise IndexLocked(
                f"another process (pid {holder}) is indexing this library; lock: {self.path}"
            ) from None
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        self._fd = fd
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None
