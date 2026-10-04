from pathlib import Path

import pytest

from comfylens.config import ConfigError, build_config, load_config


def test_defaults_load(config):
    assert config.server.port == 8765
    assert config.index.extensions == (".png", ".jpg", ".jpeg")
    assert "PreviewImage" in config.graph.output_classes
    assert [f.name for f in config.families] == [
        "qwen-image-2.1",
        "qwen-image",
        "krea-2",
        "krea-2-api",
        "flux1-krea",
        "flux",
        "ideogram",
    ]
    assert config.prompts.distinctive_alpha0 == 500.0
    assert config.lora.step_suffix_regex.pattern.startswith("^(?P<base>")


def test_user_file_merges_key_by_key(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        "[server]\nport = 9000\n"
        "[timestamps]\nburst_window_seconds = 3\n"
        '[[families]]\nname = "mine"\nany = [{ unet_regex = "x" }]\n'
    )
    config = load_config(path)
    assert (config.server.port, config.server.host) == (9000, "127.0.0.1")
    assert config.timestamps.burst_window_seconds == 3.0
    assert [f.name for f in config.families] == ["mine"]  # arrays replace


def test_missing_file_means_defaults(tmp_path: Path):
    assert load_config(tmp_path / "absent.toml") == build_config({})


def test_xdg_config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "comfylens").mkdir()
    (tmp_path / "comfylens" / "config.toml").write_text("[thumbs]\nquality = 50\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert load_config().thumbs.quality == 50


@pytest.mark.parametrize(
    "user,message",
    [
        ({"server": {"prot": 1}}, "unknown config key: server.prot"),
        ({"nope": {}}, "unknown config key: nope"),
        ({"server": {"port": "80"}}, "server.port must be of type int"),
        ({"server": {"open_browser": 1}}, "server.open_browser must be of type bool"),
        ({"server": 5}, "server must be a table"),
        ({"server": {"port": 0}}, "server.port"),
        ({"graph": {"output_name_regex": "("}}, "graph.output_name_regex: invalid regex"),
        ({"lora": {"step_suffix_regex": "(.+)"}}, "named groups 'base' and 'step'"),
        ({"timestamps": {"source": "exif"}}, "timestamps.source"),
        ({"timestamps": {"filename_patterns": [{"regex": "x", "format": "%Y"}]}}, "group 'ts'"),
        ({"families": [{"name": "a", "any": []}]}, "families[0].any"),
        ({"families": [{"name": "a", "any": [{"unet": "x"}]}]}, "unknown keys ['unet']"),
    ],
)
def test_invalid_config(user, message):
    with pytest.raises(ConfigError) as error:
        build_config(user)
    assert message in str(error.value)


def test_config_hash_tracks_extraction_settings_only():
    base = build_config({}).config_hash
    assert build_config({"server": {"port": 9000}}).config_hash == base
    assert build_config({"graph": {"output_classes": ["SaveImage"]}}).config_hash != base
    lora = {"step_suffix_regex": "^(?P<base>.+)_(?P<step>\\d+)$"}
    assert build_config({"lora": lora}).config_hash != base
    assert build_config({"analysis": {"config_round_decimals": 3}}).config_hash != base
