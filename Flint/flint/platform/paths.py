"""Flint 使用的各操作系统标准目录。

数据目录的解析顺序：

1. ``FLINT_HOME`` 环境变量（绝对路径或相对 ``~`` 的路径）
2. 平台默认位置（``%APPDATA%/Flint``、``~/Library/Application Support/Flint``、
   ``$XDG_CONFIG_HOME/flint``）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "Flint"
APP_DIR_NAME_LOWER = "flint"

_WINDOWS = sys.platform.startswith("win")
_MACOS = sys.platform == "darwin"


def _home() -> Path:
    return Path.home()


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else None


def data_dir() -> Path:
    """存放配置、实例与公共游戏数据的根目录。"""
    override = _env_path("FLINT_HOME")
    if override is not None:
        return override
    if _WINDOWS:
        base = _env_path("APPDATA") or _home() / "AppData" / "Roaming"
        return base / APP_DIR_NAME
    if _MACOS:
        return _home() / "Library" / "Application Support" / APP_DIR_NAME
    return (_env_path("XDG_CONFIG_HOME") or _home() / ".config") / APP_DIR_NAME_LOWER


def cache_dir() -> Path:
    """可下载缓存（libraries、assets、HTTP 缓存）的根目录。"""
    override = _env_path("FLINT_CACHE_DIR")
    if override is not None:
        return override
    if _WINDOWS:
        base = _env_path("LOCALAPPDATA") or _home() / "AppData" / "Local"
        return base / APP_DIR_NAME / "Cache"
    if _MACOS:
        return _home() / "Library" / "Caches" / APP_DIR_NAME
    return (_env_path("XDG_CACHE_HOME") or _home() / ".cache") / APP_DIR_NAME_LOWER


def log_dir() -> Path:
    """存放轮转启动器日志的目录。"""
    if _WINDOWS:
        return data_dir() / "logs"
    if _MACOS:
        return _home() / "Library" / "Logs" / APP_DIR_NAME
    state = _env_path("XDG_STATE_HOME") or _home() / ".local" / "state"
    return state / APP_DIR_NAME_LOWER / "logs"


def config_file() -> Path:
    return data_dir() / "config.toml"


def instances_dir() -> Path:
    return data_dir() / "instances"


def versions_dir() -> Path:
    return data_dir() / "versions"


def libraries_dir() -> Path:
    return data_dir() / "libraries"


def assets_dir() -> Path:
    return data_dir() / "assets"


def natives_dir() -> Path:
    return cache_dir() / "natives"


def java_dir() -> Path:
    return data_dir() / "java"


def http_cache_dir() -> Path:
    return cache_dir() / "http"


def natives_lib_dir() -> Path:
    """包内随发行版一起分发的 C++ 动态库所在目录。"""
    return Path(__file__).resolve().parent.parent / "lib"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
