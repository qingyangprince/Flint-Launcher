"""进程级事件总线。

UI 层通过 ``flint.ui.bridge`` 订阅本总线，后端只负责发出事件。
处理函数在发出事件的线程上同步执行，因此需要操作 Qt 对象的订阅方
必须自行把调用转到 GUI 线程。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class EventType(StrEnum):
    """约定的事件名；也接受自定义字符串作为事件类型。"""

    PROGRESS = "progress"
    LOG = "log"
    TASK_STARTED = "task_started"
    TASK_FINISHED = "task_finished"
    INSTANCE_CHANGED = "instance_changed"
    ACCOUNT_CHANGED = "account_changed"
    CONFIG_CHANGED = "config_changed"


@dataclass(frozen=True)
class LogEvent:
    level: str
    message: str
    source: str = "launcher"
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ProgressEvent:
    task_id: str
    current: int
    total: int | None = None
    message: str = ""

    @property
    def fraction(self) -> float | None:
        if not self.total:
            return None
        return min(max(self.current / self.total, 0.0), 1.0)


@dataclass(frozen=True)
class TaskEvent:
    task_id: str
    name: str
    state: str
    error: str | None = None


@dataclass(frozen=True)
class ConfigChangedEvent:
    key: str
    value: Any
    old_value: Any = None


Callback = Callable[[Any], None]


class EventBus:
    """线程安全的发布/订阅总线，各处理函数彼此隔离且保持订阅顺序。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handlers: dict[str, list[Callback]] = {}
        self._all_handlers: list[Callback] = []

    def subscribe(self, event_type: EventType | str, callback: Callback) -> Callable[[], None]:
        key = _key(event_type)
        with self._lock:
            self._handlers.setdefault(key, []).append(callback)
        return lambda: self.unsubscribe(key, callback)

    def subscribe_all(self, callback: Callable[[str, Any], None]) -> Callable[[], None]:
        with self._lock:
            self._all_handlers.append(callback)
        return lambda: self.unsubscribe_all(callback)

    def unsubscribe(self, event_type: EventType | str, callback: Callback) -> None:
        key = _key(event_type)
        with self._lock:
            handlers = self._handlers.get(key)
            if handlers and callback in handlers:
                handlers.remove(callback)
                if not handlers:
                    del self._handlers[key]

    def unsubscribe_all(self, callback: Callable[[str, Any], None]) -> None:
        with self._lock:
            if callback in self._all_handlers:
                self._all_handlers.remove(callback)

    def emit(self, event_type: EventType | str, payload: Any = None) -> None:
        key = _key(event_type)
        with self._lock:
            handlers = list(self._handlers.get(key, ()))
            watchers = list(self._all_handlers)

        for handler in handlers:
            _safe_call(handler, payload, key)
        for watcher in watchers:
            _safe_call(lambda _payload, _watcher=watcher: _watcher(key, payload), payload, key)

    def clear(self) -> None:
        with self._lock:
            self._handlers.clear()
            self._all_handlers.clear()

    def handler_count(self, event_type: EventType | str | None = None) -> int:
        with self._lock:
            if event_type is None:
                return sum(len(v) for v in self._handlers.values()) + len(self._all_handlers)
            return len(self._handlers.get(_key(event_type), ()))


def _key(event_type: EventType | str) -> str:
    return event_type.value if isinstance(event_type, EventType) else str(event_type)


def _safe_call(handler: Callable[[Any], None], payload: Any, key: str) -> None:
    try:
        handler(payload)
    except Exception:  # pragma: no cover - 隔离异常，避免影响其他订阅者
        logger.exception("event handler %r failed for %s", handler, key)


bus = EventBus()


def emit(event_type: EventType | str, payload: Any = None) -> None:
    bus.emit(event_type, payload)


def subscribe(event_type: EventType | str, callback: Callback) -> Callable[[], None]:
    return bus.subscribe(event_type, callback)


def log(message: str, *, level: str = "info", source: str = "launcher") -> None:
    """发出结构化日志事件（同时写入常规 logger）。"""
    logger.log(logging.getLevelName(level.upper()) if level else logging.INFO, "%s", message)
    bus.emit(EventType.LOG, LogEvent(level=level, message=message, source=source))
