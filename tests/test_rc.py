import tomllib
from pathlib import Path

import pytest

from comfylens.rc import RcError, rc_path, scan_directory


def write_rc(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_scan_directory_reads_the_file(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    rc = write_rc(tmp_path / ".comfylensrc", f'[scan]\ndirectory = "{library}"\n')
    assert scan_directory(rc) == library


def test_scan_directory_expands_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "Pictures").mkdir()
    write_rc(tmp_path / ".comfylensrc", '[scan]\ndirectory = "~/Pictures"\n')
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("COMFYLENS_RC", raising=False)
    assert rc_path() == tmp_path / ".comfylensrc"
    assert scan_directory() == tmp_path / "Pictures"


def test_comfylens_rc_env_overrides_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    library = tmp_path / "library"
    library.mkdir()
    rc = write_rc(tmp_path / "elsewhere" / "rc.toml", f'[scan]\ndirectory = "{library}"\n')
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("COMFYLENS_RC", str(rc))
    assert rc_path() == rc
    assert scan_directory() == library


def test_missing_file_names_the_path(tmp_path: Path):
    with pytest.raises(RcError, match="no configuration file"):
        scan_directory(tmp_path / ".comfylensrc")


@pytest.mark.parametrize(
    "text",
    [
        "[scan]\n",  # no directory
        "[scan]\ndirectory = 3\n",  # not a string
        "[scan]\ndirectory = ''\n",  # empty
        "[scan]\ndirectory = '/definitely/not/here'\n",  # not a directory
        "[scna]\ndirectory = '/tmp'\n",  # a typo
        "not toml =",  # not TOML
    ],
)
def test_invalid_files_are_rejected(tmp_path: Path, text: str):
    rc = write_rc(tmp_path / ".comfylensrc", text)
    with pytest.raises(RcError):
        scan_directory(rc)


def test_example_file_is_valid():
    """The committed example parses and can be pointed at a real directory."""
    example = Path(__file__).resolve().parents[1] / ".comfylensrc.example"
    document = tomllib.loads(example.read_text(encoding="utf-8"))
    assert set(document) == {"scan"}
    assert document["scan"]["directory"] == "~/Pictures"
