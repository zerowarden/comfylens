"""Atomic file writes: write beside the target, then rename into place."""

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO


def write_atomic[T](path: Path, write: Callable[[BinaryIO], T], *, prefix: str = ".") -> T:
    """Write `path` through a temporary file in its directory, so a reader never sees a
    partial file and two writers cannot corrupt each other. Returns what `write` returns."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            result = write(f)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return result
