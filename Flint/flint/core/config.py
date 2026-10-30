"""全局配置：默认值、TOML 持久化与变更事件。"""

from __future__ import annotations

import copy
import logging
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit

from flint.core import events
from flint.infra import fs
from flint.platform import paths

logger = logging.getLogger(__name__)

MIN_MEMORY_MB = 512
MAX_MEMORY_MB = 65536
MAX_CONCURRENCY = 64

DEFAULT_CONFIG: dict[str, Any] = {
    "launcher.memory_mb": 2048,
    "launcher.java_path": "",
    "launcher.jvm_args": "",
    "launcher.game_width": 854,
    "launcher.game_height": 480,
    "launcher.fullscreen": False,
    "launcher.close_on_launch": False,
    "download.mirror": "official",
    "download.max_concurrency": 8,
    "download.timeout_seconds": 20,
    "download.retries": 3,
    "network.proxy": "",
    "ui.theme": "dark",
    "ui.language": "zh_CN",
    "ui.show_log_on_launch": True,
}

MIRRORS = ("official", "bmclapi")
THEMES = ("dark", "light")
LANGUAGES = ("zh_CN", "en_US")


class ConfigError(Exception):
    """配置文件无法读取或取值非法时抛出。"""


@dataclass(frozen=True)
class _Spec:
    kind: type
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] = ()


_SPECS: dict[str, _Spec] = {
    "launcher.memory_mb": _Spec(int, MIN_MEMORY_MB, MAX_MEMORY_MB),
    "launcher.java_path": _Spec(str),
    "launcher.jvm_args": _Spec(str),
    "launcher.game_width": _Spec(int, 320, 16384),
    "launcher.game_height": _Spec(int, 240, 16384),
    "launcher.fullscreen": _Spec(bool),
    "launcher.close_on_launch": _Spec(bool),
    "download.mirror": _Spec(str, choices=MIRRORS),
    "download.max_concurrency": _Spec(int, 1, MAX_CONCURRENCY),
    "download.timeout_seconds": _Spec(int, 1, 300),
    "download.retries": _Spec(int, 0, 10),
    "network.proxy": _Spec(str),
    "ui.theme": _Spec(str, choices=THEMES),
    "ui.language": _Spec(str, choices=LANGUAGES),
    "ui.show_log_on_launch": _Spec(bool),
}


def validate_value(key: str, value: Any) -> Any:
    """校验并规范化配置值，非法时抛出 ``ValueError``。"""
    spec = _SPECS.get(key)
    if spec is None:
        return value
    if spec.kind is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean, got {type(value).__name__}")
        return value
    if spec.kind is int:
        if isinstance(value, bool) or not isinstance(value, int):
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be an integer, got {value!r}") from None
        if spec.minimum is not None and value < spec.minimum:
            raise ValueError(f"{key} must be >= {spec.minimum}, got {value}")
        if spec.maximum is not None and value > spec.maximum:
            raise ValueError(f"{key} must be <= {spec.maximum}, got {value}")
        return value
    if spec.kind is str:
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string, got {type(value).__name__}")
        if spec.choices and value not in spec.choices:
            raise ValueError(f"{key} must be one of {spec.choices}, got {value!r}")
        return value
    return value


def _flatten(data: Mapping[str, Any], prefix: str = "") -> Iterator[tuple[str, Any]]:
    for key, value in data.items():
        full_key = f"{prefix}{key}"
        if isinstance(value, Mapping):
            yield from _flatten(value, prefix=f"{full_key}.")
        else:
            yield full_key, value


def _unflatten(values: Mapping[str, Any]) -> dict[str, Any]:
    root: dict[str, Any] = {}
    for key, value in values.items():
        parts = key.split(".")
        node = root
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[parts[-1]] = value
    return root


class Config:
    """以 TOML 文件为后端的点号键配置。

    取值会依据 :data:`DEFAULT_CONFIG` 校验；未知键原样保留，
    这样新版本写入的设置在高版本降级运行时也不会丢失。
    """

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        autoload: bool = True,
        bus: events.EventBus | None = None,
    ) -> None:
        self._path = Path(path) if path is not None else paths.config_file()
        self._bus = bus or events.bus
        self._lock = threading.RLock()
        self._values: dict[str, Any] = dict(DEFAULT_CONFIG)
        if autoload:
            self.load()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> None:
        """读取 TOML 文件，缺失或非法的项沿用默认值。"""
        with self._lock:
            values = dict(DEFAULT_CONFIG)
            if not self._path.is_file():
                self._values = values
                return
            try:
                document = tomlkit.parse(self._path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                logger.warning("cannot read config %s, using defaults: %s", self._path, exc)
                self._values = values
                return

            for key, value in _flatten(document):
                try:
                    values[key] = validate_value(key, value)
                except ValueError as exc:
                    logger.warning("invalid config value for %s, keeping default: %s", key, exc)
            self._values = values

    def reload(self) -> None:
        self.load()

    def save(self) -> None:
        with self._lock:
            document = tomlkit.dumps(_unflatten(self._values))
            try:
                fs.write_atomic(self._path, document)
            except OSError as exc:
                raise ConfigError(f"cannot write config {self._path}: {exc}") from exc

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self._values:
                return self._values[key]
        return DEFAULT_CONFIG.get(key, default)

    def set(self, key: str, value: Any, *, save: bool = True) -> Any:
        value = validate_value(key, value)
        with self._lock:
            old_value = self._values.get(key, DEFAULT_CONFIG.get(key))
            changed = old_value != value
            self._values[key] = value
            if changed and save:
                self.save()
        if changed:
            self._bus.emit(
                events.EventType.CONFIG_CHANGED,
                events.ConfigChangedEvent(key=key, value=value, old_value=old_value),
            )
        return value

    def update(self, values: Mapping[str, Any], *, save: bool = True) -> None:
        validated = {key: validate_value(key, value) for key, value in values.items()}
        with self._lock:
            self._values.update(validated)
            if save:
                self.save()
        for key, value in validated.items():
            self._bus.emit(
                events.EventType.CONFIG_CHANGED,
                events.ConfigChangedEvent(key=key, value=value, old_value=DEFAULT_CONFIG.get(key)),
            )

    def reset(self, key: str | None = None, *, save: bool = True) -> None:
        """把一个键（或整个文件）恢复为默认值。"""
        if key is None:
            self.update(DEFAULT_CONFIG, save=save)
            return
        if key not in DEFAULT_CONFIG:
            raise KeyError(key)
        self.set(key, DEFAULT_CONFIG[key], save=save)

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return _unflatten(copy.deepcopy(self._values))

    def items(self) -> list[tuple[str, Any]]:
        with self._lock:
            return sorted(self._values.items())

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __contains__(self, key: object) -> bool:
        return key in self._values

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"Config(path={self._path!r}, keys={len(self._values)})"


_config: Config | None = None
_config_lock = threading.RLock()


def get_config() -> Config:
    """返回进程级配置单例（首次调用时创建）。"""
    global _config
    with _config_lock:
        if _config is None:
            _config = Config()
        return _config


def set_config(config: Config | None) -> None:
    global _config
    with _config_lock:
        _config = config
