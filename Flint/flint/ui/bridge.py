"""★ 前后端唯一耦合点：事件总线 → Qt Signal，协程 → 后台事件循环。

后端（core/infra）从不 import Qt；UI 只通过本模块订阅事件、提交协程。
事件可能从任意线程发出，Qt 的信号/槽队列保证槽函数在 GUI 线程执行。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import Callable, Coroutine
from typing import Any

from PySide6.QtCore import QObject, Signal

from flint.core import events

logger = logging.getLogger(__name__)

Callback = Callable[[Any], None]
ErrorCallback = Callable[[BaseException], None]


class AsyncRunner:
    """独占一个线程运行 asyncio 事件循环，供 GUI 提交协程。"""

    def __init__(self, name: str = "flint-async") -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._started = threading.Event()
        self._lock = threading.Lock()
        self._closed = False

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.call_soon(self._started.set)
        try:
            self._loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.close()

    def ensure_started(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("async runner is closed")
            if not self._thread.is_alive():
                self._thread.start()
        self._started.wait(timeout=5)

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        self.ensure_started()
        return self._loop

    def submit(self, coroutine: Coroutine[Any, Any, Any]) -> concurrent.futures.Future:
        """把协程提交到后台循环，返回标准 ``Future``。"""
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def shutdown(self, timeout: float = 3.0) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if not self._thread.is_alive():
                return
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=timeout)


class Bridge(QObject):
    """把后端事件与协程结果安全地投递到 GUI 线程。"""

    progress = Signal(object)
    log = Signal(object)
    task_started = Signal(object)
    task_finished = Signal(object)
    instance_changed = Signal(object)
    account_changed = Signal(object)
    config_changed = Signal(object)
    event = Signal(str, object)

    _task_done = Signal(object)

    def __init__(
        self,
        bus: events.EventBus | None = None,
        runner: AsyncRunner | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._bus = bus or events.bus
        self._runner = runner or AsyncRunner()
        self._callbacks: dict[int, tuple[concurrent.futures.Future, Callback | None, ErrorCallback | None]] = {}
        self._callbacks_lock = threading.Lock()
        self._signals: dict[str, Signal] = {
            events.EventType.PROGRESS.value: self.progress,
            events.EventType.LOG.value: self.log,
            events.EventType.TASK_STARTED.value: self.task_started,
            events.EventType.TASK_FINISHED.value: self.task_finished,
            events.EventType.INSTANCE_CHANGED.value: self.instance_changed,
            events.EventType.ACCOUNT_CHANGED.value: self.account_changed,
            events.EventType.CONFIG_CHANGED.value: self.config_changed,
        }
        self._unsubscribe = self._bus.subscribe_all(self._on_event)
        self._task_done.connect(self._dispatch_result)

    # -- 事件转发 -----------------------------------------------------------
    def _on_event(self, event_type: str, payload: Any) -> None:
        self.event.emit(event_type, payload)
        signal = self._signals.get(event_type)
        if signal is not None:
            signal.emit(payload)

    # -- 协程调度 -----------------------------------------------------------
    def run_async(
        self,
        coroutine: Coroutine[Any, Any, Any],
        *,
        on_done: Callback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> concurrent.futures.Future:
        """提交协程；``on_done``/``on_error`` 保证在 GUI 线程执行。"""
        future = self._runner.submit(coroutine)
        if on_done is None and on_error is None:
            return future
        with self._callbacks_lock:
            self._callbacks[id(future)] = (future, on_done, on_error)
        future.add_done_callback(self._task_done.emit)
        return future

    def _dispatch_result(self, future: concurrent.futures.Future) -> None:
        with self._callbacks_lock:
            _future, on_done, on_error = self._callbacks.pop(id(future), (None, None, None))
        try:
            result = future.result()
        except BaseException as exc:  # noqa: BLE001 - 交给 UI 决定如何提示
            if on_error is not None:
                on_error(exc)
            else:
                logger.error("background task failed: %s", exc, exc_info=exc)
            return
        if on_done is not None:
            on_done(result)

    def close(self) -> None:
        self._unsubscribe()
        self._runner.shutdown()


_bridge: Bridge | None = None
_bridge_lock = threading.RLock()


def get_bridge() -> Bridge:
    """返回进程级 Bridge 单例（需在 GUI 线程首次创建）。"""
    global _bridge
    with _bridge_lock:
        if _bridge is None:
            _bridge = Bridge()
        return _bridge


def set_bridge(bridge: Bridge | None) -> None:
    global _bridge
    with _bridge_lock:
        _bridge = bridge
