import json
import os
from pathlib import Path

from conftest import load_golden, png_with_text
from typer.testing import CliRunner

from comfylens.cli import app

runner = CliRunner()


def golden_file(tmp_path: Path) -> Path:
    path = tmp_path / "library" / "golden.png"
    path.parent.mkdir()
    prompt = load_golden("sample_qwen21.prompt.json")
    workflow = load_golden("sample_qwen21.workflow.json")
    path.write_bytes(png_with_text({"prompt": prompt, "workflow": workflow}))
    return path


def snapshot(root: Path) -> dict[str, int]:
    return {str(p): p.stat().st_mtime_ns for p in sorted(root.rglob("*"))}


def test_inspect_prints_chain_and_unused_lora(tmp_path: Path):
    path = golden_file(tmp_path)
    result = runner.invoke(app, ["inspect", str(path)], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert (
        "Model chain: qwen_image_2.1_int8_convrot + qwen2.1-anime2real-sunburst (1.13) + "
        "qwen2.1-lenovo-ultrareal (1.06) + KSampler #6"
    ) in result.output
    unused_rows = [line for line in result.output.splitlines() if "unused" in line]
    assert len(unused_rows) == 1 and "qwen2.1-exampleV01_000004956" in unused_rows[0]
    assert "UNUSED_LORA" in result.output


def test_inspect_json(tmp_path: Path):
    path = golden_file(tmp_path)
    result = runner.invoke(app, ["inspect", "--json", str(path)])
    assert result.exit_code == 0, result.output
    doc = json.loads(result.stdout)
    assert doc["status"] == "ok"
    assert doc["path"] == str(path)
    assert doc["extraction"]["model_family"] == "qwen-image-2.1"
    assert doc["unregistered"] == []


def test_inspect_unreadable_file_reports_error(tmp_path: Path):
    path = tmp_path / "notes.png"
    path.write_text("not an image")
    result = runner.invoke(app, ["inspect", "--json", str(path)])
    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert (doc["status"], doc["error"]) == ("error", "UnsupportedFormat: not a PNG or JPEG file")


def test_inspect_rejects_invalid_config(tmp_path: Path):
    config_dir = tmp_path / "xdg" / "comfylens"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("[server]\nport = 'x'\n")
    path = golden_file(tmp_path)
    result = runner.invoke(
        app, ["inspect", str(path)], env={"XDG_CONFIG_HOME": str(tmp_path / "xdg")}
    )
    assert result.exit_code == 2
    assert "server.port" in result.output


def test_inspect_never_writes_to_the_library(tmp_path: Path):
    path = golden_file(tmp_path)
    os.utime(path, ns=(1_000_000_000, 1_790_649_651_329_171_267))
    before = snapshot(path.parent)
    for args in (["inspect", str(path)], ["inspect", "--json", str(path)]):
        assert runner.invoke(app, args).exit_code == 0
    assert snapshot(path.parent) == before


def test_index_reports_a_rate_after_a_reextract_only_run(tmp_path: Path, monkeypatch):
    from comfylens import version

    root = golden_file(tmp_path).parent
    assert runner.invoke(app, ["index", str(root)]).exit_code == 0
    monkeypatch.setattr(version, "EXTRACTOR_VERSION", version.EXTRACTOR_VERSION + 1)
    result = runner.invoke(app, ["index", str(root)])
    assert result.exit_code == 0
    assert "1 re-extracted" in result.output
    assert "files/s" in result.output


def test_serve_warns_off_loopback(tmp_path: Path, monkeypatch):
    import uvicorn

    from comfylens import cli

    calls = []

    class FakeServer:
        started = False
        should_exit = True  # the announce thread exits at once

        def __init__(self, config):
            calls.append(config.host)

        def run(self, sockets):
            sockets[0].close()

    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    library = tmp_path / "lib"
    library.mkdir()
    local = runner.invoke(app, ["serve", str(library), "--no-open", "--no-index"])
    assert local.exit_code == 0 and "Warning" not in local.output
    exposed = runner.invoke(app, ["serve", str(library), "--host", "0.0.0.0", "--no-open"])
    assert exposed.exit_code == 0 and "no authentication" in exposed.output
    assert calls == ["127.0.0.1", "0.0.0.0"]
    assert cli._is_loopback("::1") and cli._is_loopback("localhost")
    assert not cli._is_loopback("192.168.1.5") and not cli._is_loopback("myhost")


def _collection_with_a_prompt() -> None:
    from comfylens.collection.store import CollectionStore, PromptData
    from comfylens.paths import collection_dir

    store = CollectionStore(collection_dir())
    ref = store.put_original(png_with_text({}), "png", 32, 32, None, None)
    store.create(PromptData(title="Fox", positive="a fox", references=[ref]))


def test_serve_takes_the_next_free_port(tmp_path: Path, monkeypatch):
    import socket

    import uvicorn

    bound = []

    class FakeServer:
        started = False
        should_exit = True

        def __init__(self, config):
            pass

        def run(self, sockets):
            bound.append(sockets[0].getsockname()[1])
            sockets[0].close()

    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    library = tmp_path / "lib"
    library.mkdir()
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        result = runner.invoke(app, ["serve", str(library), "--no-open", "--port", str(port)])
        free = runner.invoke(app, ["free-port", "--port", str(port)])
    assert result.exit_code == 0, result.output
    assert f"Port {port} is in use" in result.output
    assert bound[0] != port and int(free.output) != port


def test_collection_export_and_import(tmp_path: Path):
    from datetime import date

    from comfylens.paths import collection_dir

    _collection_with_a_prompt()
    result = runner.invoke(app, ["collection", "export", str(tmp_path)])
    assert result.exit_code == 0, result.output
    archive = tmp_path / f"comfylens-collection-{date.today().isoformat()}.zip"
    assert archive.is_file()
    assert "Exported 1 prompt and 1 image" in result.output
    assert not list(tmp_path.glob(".comfylens-export-*"))  # no temporary file left behind

    again = runner.invoke(app, ["collection", "export", str(archive)])
    assert again.exit_code == 1 and "--force" in again.output
    forced = runner.invoke(app, ["collection", "export", str(archive), "--force"])
    assert forced.exit_code == 0, forced.output

    # A fresh collection takes the archive; a second import adds nothing.
    for path in collection_dir().iterdir():
        if path.is_file():
            path.unlink()
    imported = runner.invoke(app, ["collection", "import", str(archive)])
    assert imported.exit_code == 0, imported.output
    assert "Imported 1 prompt from" in imported.output
    repeat = runner.invoke(app, ["collection", "import", str(archive)])
    assert "Imported 0 prompts (1 already here)" in repeat.output


def test_collection_import_rejects_other_files(tmp_path: Path):
    bogus = tmp_path / "notes.zip"
    bogus.write_text("not a zip")
    result = runner.invoke(app, ["collection", "import", str(bogus)])
    assert result.exit_code == 1
    assert "not a zip file" in result.output


def test_collection_export_to_a_missing_directory(tmp_path: Path):
    result = runner.invoke(app, ["collection", "export", str(tmp_path / "nope" / "x.zip")])
    assert result.exit_code == 1 and "is not a directory" in result.output
