"""Flint 测试套件共用的 pytest fixture。"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flint.core import config as config_module  # noqa: E402
from flint.core import events as events_module  # noqa: E402
from flint.infra import http as http_module  # noqa: E402
from flint.infra import native_loader  # noqa: E402


@pytest.fixture(autouse=True)
def clean_event_bus() -> Iterator[None]:
    events_module.bus.clear()
    yield
    events_module.bus.clear()


@pytest.fixture
def event_bus() -> events_module.EventBus:
    return events_module.bus


@pytest.fixture
def flint_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """用临时 FLINT_HOME 隔离所有路径辅助函数。"""
    home = tmp_path / "flint-home"
    home.mkdir()
    monkeypatch.setenv("FLINT_HOME", str(home))
    monkeypatch.setenv("FLINT_CACHE_DIR", str(home / "cache"))
    config_module.set_config(None)
    native_loader.reset_cache()
    yield home
    config_module.set_config(None)
    native_loader.reset_cache()


@pytest.fixture
async def http_client() -> Iterator[http_module.HttpClient]:
    client = http_module.HttpClient(retries=0, backoff=0.0, max_backoff=0.0)
    try:
        yield client
    finally:
        await client.aclose()
        http_module.set_client(None)
