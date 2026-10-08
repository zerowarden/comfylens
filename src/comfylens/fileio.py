"""Atomic file writes: write beside the target, then rename into place."""

import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO


def write_atomic[T](
    path: Path, write: Callable[[BinaryIO], T], *, prefix: str = ".", keep_stat: bool = False
) -> T:
    """Write `path` through a temporary file in its directory, so a reader never sees a
    partial file and two writers cannot corrupt each other. Returns what `write` returns.

    `keep_stat` gives the new file the permissions and times of the one it replaces."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            result = write(f)
        if keep_stat:
            shutil.copystat(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return result
