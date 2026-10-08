"""The `.comfylensrc` file: which directory to scan.

Read from `$COMFYLENS_RC` when set, else `$HOME/.comfylensrc`. The same file is
used by the host CLI and by the container launcher (scripts/docker.py), so the
scan directory lives in one place:

    [scan]
    directory = "~/Pictures"

The directory is scanned recursively: point it at a parent to pick up several
ComfyUI output folders at once.
"""

import os
import tomllib
from pathlib import Path

_WRONG_SHAPE = 'set [scan] directory = "~/..." (see .comfylensrc.example)'


class RcError(ValueError):
    """`.comfylensrc` is missing or invalid; the message says how to fix it."""


def rc_path() -> Path:
    """The rc file to read: `$COMFYLENS_RC`, else `$HOME/.comfylensrc`."""
    override = os.environ.get("COMFYLENS_RC", "")
    return Path(override).expanduser() if override else Path.home() / ".comfylensrc"


def scan_directory(path: Path | None = None) -> Path:
    """The validated `scan.directory` from the rc file (`path` overrides the lookup)."""
    path = path or rc_path()
    if not path.is_file():
        raise RcError(f"no configuration file at {path}; {_WRONG_SHAPE}")
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise RcError(f"{path}: {e}") from e
    unknown = set(document) - {"scan"}
    if unknown:
        raise RcError(f"{path}: unknown key {sorted(unknown)[0]}; {_WRONG_SHAPE}")
    scan = document.get("scan")
    directory = scan.get("directory") if isinstance(scan, dict) else None
    if not isinstance(directory, str) or not directory:
        raise RcError(f"{path}: {_WRONG_SHAPE}")
    resolved = Path(directory).expanduser()
    if not resolved.is_dir():
        raise RcError(f"{path}: scan.directory {directory} is not a directory")
    return resolved
