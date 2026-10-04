"""XDG locations for app state: the app never writes inside the library directory."""

import hashlib
import os
from pathlib import Path


def _xdg(var: str, fallback: str) -> Path:
    # The XDG spec says relative paths in these variables are invalid and must be ignored.
    value = os.environ.get(var, "")
    return Path(value) if os.path.isabs(value) else Path.home() / fallback


def config_path() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "comfylens" / "config.toml"


def library_id(root: Path) -> str:
    return hashlib.sha1(str(root.resolve()).encode()).hexdigest()[:16]


def library_dir(root: Path) -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / "comfylens" / library_id(root)


def catalog_path(root: Path) -> Path:
    return library_dir(root) / "catalog.sqlite"


def lock_path(root: Path) -> Path:
    return library_dir(root) / "index.lock"


def thumbs_dir() -> Path:
    """Shared across libraries: thumbnails are keyed by content hash."""
    return _xdg("XDG_CACHE_HOME", ".cache") / "comfylens" / "thumbs"


def thumb_path(thumbs: Path, content_hash: str) -> Path:
    return thumbs / content_hash[:2] / f"{content_hash}.webp"
