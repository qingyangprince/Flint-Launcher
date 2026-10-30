"""配置：默认值、TOML 往返、校验与变更事件。"""

from __future__ import annotations

from pathlib import Path

import pytest
import tomlkit
from flint.core.config import DEFAULT_CONFIG, Config, ConfigError
from flint.core.events import ConfigChangedEvent, EventBus, EventType


def make_config(path: Path, bus: EventBus | None = None) -> Config:
    return Config(path, bus=bus)


def test_defaults_when_file_is_missing(tmp_path: Path):
    config = make_config(tmp_path / "config.toml")

    assert config.get("launcher.memory_mb") == DEFAULT_CONFIG["launcher.memory_mb"]
    assert config.get("download.mirror") == "official"
    assert config.get("unknown.key", "fallback") == "fallback"
    assert "launcher.memory_mb" in config


def test_round_trip_preserves_values_and_structure(tmp_path: Path):
    path = tmp_path / "nested" / "config.toml"
    config = make_config(path)

    config.set("launcher.memory_mb", 4096)
    config.set("ui.theme", "light")
    config.set("network.proxy", "http://127.0.0.1:7890")

    assert path.is_file()
    document = tomlkit.parse(path.read_text(encoding="utf-8"))
    assert document["launcher"]["memory_mb"] == 4096
    assert document["ui"]["theme"] == "light"

    reloaded = make_config(path)
    assert reloaded.get("launcher.memory_mb") == 4096
    assert reloaded.get("ui.theme") == "light"
    assert reloaded.get("network.proxy") == "http://127.0.0.1:7890"


def test_validation_rejects_out_of_range_and_unknown_choices(tmp_path: Path):
    config = make_config(tmp_path / "config.toml")

    with pytest.raises(ValueError):
        config.set("launcher.memory_mb", 128)
    with pytest.raises(ValueError):
        config.set("launcher.memory_mb", 999999)
    with pytest.raises(ValueError):
        config.set("download.max_concurrency", 0)
    with pytest.raises(ValueError):
        config.set("ui.theme", "solarized")
    with pytest.raises(ValueError):
        config.set("launcher.fullscreen", "yes")

    assert config.get("launcher.memory_mb") == DEFAULT_CONFIG["launcher.memory_mb"]


def test_numeric_strings_are_coerced(tmp_path: Path):
    config = make_config(tmp_path / "config.toml")
    config.set("launcher.memory_mb", "4096")
    assert config.get("launcher.memory_mb") == 4096


def test_corrupt_file_falls_back_to_defaults(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("this is = = not toml", encoding="utf-8")

    config = make_config(path)
    assert config.get("launcher.memory_mb") == DEFAULT_CONFIG["launcher.memory_mb"]


def test_invalid_value_in_file_keeps_default(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("[launcher]\nmemory_mb = 10\nfullscreen = true\n", encoding="utf-8")

    config = make_config(path)
    assert config.get("launcher.memory_mb") == DEFAULT_CONFIG["launcher.memory_mb"]
    assert config.get("launcher.fullscreen") is True


def test_change_events(tmp_path: Path):
    bus = EventBus()
    seen: list[ConfigChangedEvent] = []
    bus.subscribe(EventType.CONFIG_CHANGED, seen.append)

    config = make_config(tmp_path / "config.toml", bus=bus)
    config.set("launcher.memory_mb", 4096)

    assert len(seen) == 1
    assert seen[0].key == "launcher.memory_mb"
    assert seen[0].value == 4096
    assert seen[0].old_value == DEFAULT_CONFIG["launcher.memory_mb"]

    config.set("launcher.memory_mb", 4096)
    assert len(seen) == 1


def test_reset_single_key_and_everything(tmp_path: Path):
    config = make_config(tmp_path / "config.toml")
    config.set("launcher.memory_mb", 4096)
    config.set("ui.theme", "light")

    config.reset("launcher.memory_mb")
    assert config.get("launcher.memory_mb") == DEFAULT_CONFIG["launcher.memory_mb"]
    assert config.get("ui.theme") == "light"

    config.reset()
    assert config.get("ui.theme") == DEFAULT_CONFIG["ui.theme"]

    with pytest.raises(KeyError):
        config.reset("nope.nothing")


def test_update_batch(tmp_path: Path):
    config = make_config(tmp_path / "config.toml")
    config.update({"launcher.game_width": 1280, "launcher.game_height": 720})
    assert config.get("launcher.game_width") == 1280
    assert config.as_dict()["launcher"]["game_height"] == 720


def test_save_failure_raises_config_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = make_config(tmp_path / "config.toml")

    def explode(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("flint.infra.fs.write_atomic", explode)
    with pytest.raises(ConfigError):
        config.save()
