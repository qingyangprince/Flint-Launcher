"""UI 级全局状态：当前实例 / 账户 / 运行中的进程 / 标签页。

同时承担启动编排：把 ``core.launcher`` 的协程通过 :mod:`flint.ui.bridge`
提交到后台线程，再把结果投递回 GUI 线程。页面只与本模块和信号打交道。
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, Signal

from flint.core import account as account_module
from flint.core import events
from flint.core import instance as instance_module
from flint.core import launcher as launcher_module
from flint.core.account import Account
from flint.core.events import AccountChangedEvent, InstanceChangedEvent, ProgressEvent
from flint.core.instance import Instance
from flint.infra.process import ManagedProcess

from .bridge import Bridge, get_bridge

logger = logging.getLogger(__name__)

GAME_ERROR_HINTS = ("error", "exception", "severe", "fatal", "caused by")


def classify_game_line(line: str) -> str:
    """粗粒度判定游戏日志级别，供日志视图着色。"""
    lowered = line.lower()
    if any(hint in lowered for hint in GAME_ERROR_HINTS):
        return "error"
    if "warn" in lowered:
        return "warn"
    return "info"


class UIState(QObject):
    instance_changed = Signal(object)  # Instance | None
    account_changed = Signal(object)  # Account | None
    process_changed = Signal(object)  # ManagedProcess | None
    tab_changed = Signal(int)
    launch_started = Signal(object)  # Instance
    launch_finished = Signal(object)  # 退出码
    launch_failed = Signal(str)

    def __init__(
        self,
        *,
        bridge: Bridge | None = None,
        instances: instance_module.InstanceManager | None = None,
        accounts: account_module.AccountManager | None = None,
        launcher: launcher_module.Launcher | None = None,
        download: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.bridge = bridge or get_bridge()
        self.instances = instances or instance_module.get_instance_manager()
        self.accounts = accounts or account_module.get_account_manager()
        self._launcher = launcher
        self.download = download
        self._instance: Instance | None = self.instances.selected
        self._account: Account | None = self.accounts.active
        self._process: ManagedProcess | None = None
        self._launching = False
        self._tab_index = 0

        if self._account is None and self.accounts.accounts:
            self._account = self.accounts.set_active(self.accounts.accounts[0].id)

        self.bridge.instance_changed.connect(self._on_instance_event)
        self.bridge.account_changed.connect(self._on_account_event)

    # -- 只读属性 -----------------------------------------------------------
    @property
    def launcher(self) -> launcher_module.Launcher:
        if self._launcher is None:
            self._launcher = launcher_module.Launcher(instances_root=self.instances.root)
        return self._launcher

    @property
    def current_instance(self) -> Instance | None:
        return self._instance

    @property
    def current_account(self) -> Account | None:
        return self._account

    @property
    def running_process(self) -> ManagedProcess | None:
        return self._process

    @property
    def tab_index(self) -> int:
        return self._tab_index

    @property
    def is_game_running(self) -> bool:
        return self._process is not None and self._process.running

    @property
    def is_launching(self) -> bool:
        return self._launching

    # -- 选择项 -------------------------------------------------------------
    def select_instance(self, key: str | Instance | None) -> Instance | None:
        instance = self.instances.select(key)
        self._apply_instance(instance)
        return instance

    def select_account(self, account_id: str | None) -> Account | None:
        account = self.accounts.set_active(account_id)
        self._apply_account(account)
        return account

    def refresh_accounts(self) -> None:
        self._account = self.accounts.active
        self.account_changed.emit(self._account)

    def set_tab(self, index: int) -> None:
        if index == self._tab_index:
            return
        self._tab_index = index
        self.tab_changed.emit(index)

    # -- 启动/停止 ----------------------------------------------------------
    def start_game(self) -> bool:
        """拉起当前实例；返回是否成功提交了启动任务。"""
        if self._launching:
            self.launch_failed.emit("正在启动中，请稍候")
            return False
        if self.is_game_running:
            self.launch_failed.emit("游戏已经在运行")
            return False
        instance = self._instance
        if instance is None:
            self.launch_failed.emit("请先在左侧选择一个实例")
            return False
        account = self._account
        if account is None:
            self.launch_failed.emit("请先添加并选择一个账户")
            return False

        self.launch_started.emit(instance)
        self._launching = True
        self.bridge.run_async(
            self._launch(instance, account),
            on_done=self._on_launch_done,
            on_error=self._on_launch_error,
        )
        return True

    def stop_game(self) -> bool:
        process = self._process
        if process is None or not process.running:
            return False
        events.log("正在结束游戏进程…", level="warn", source="game")
        self.bridge.run_async(process.terminate(), on_error=self._on_stop_error)
        return True

    async def _launch(
        self, instance: Instance, account: Account
    ) -> tuple[launcher_module.LaunchPlan, ManagedProcess]:
        return await self.launcher.launch(
            instance,
            account,
            download=self.download,
            on_progress=_emit_progress,
            on_stdout=_emit_game_line("game"),
            on_stderr=_emit_game_line("game"),
        )

    def _on_launch_done(self, result: Any) -> None:
        self._launching = False
        plan, process = result
        logger.info("launched %s with %d classpath entries", plan.main_class, len(plan.classpath))
        self._set_process(process)
        self.bridge.run_async(_wait_process(process), on_done=self._on_process_exit)

    def _on_launch_error(self, error: BaseException) -> None:
        self._launching = False
        message = str(error) or error.__class__.__name__
        events.log(message, level="error", source="game")
        self.launch_failed.emit(message)

    def _on_stop_error(self, error: BaseException) -> None:
        events.log(f"结束游戏进程失败：{error}", level="error", source="game")

    def _on_process_exit(self, returncode: int) -> None:
        self._set_process(None)
        level = "info" if returncode == 0 else "error"
        events.log(f"游戏进程已退出（退出码 {returncode}）", level=level, source="game")
        self.launch_finished.emit(returncode)

    def _set_process(self, process: ManagedProcess | None) -> None:
        if process is self._process:
            return
        self._process = process
        self.process_changed.emit(process)

    # -- 事件回写 -----------------------------------------------------------
    def _apply_instance(self, instance: Instance | None) -> None:
        if instance == self._instance:
            return
        self._instance = instance
        self.instance_changed.emit(instance)

    def _apply_account(self, account: Account | None) -> None:
        if account == self._account:
            return
        self._account = account
        self.account_changed.emit(account)

    def _on_instance_event(self, payload: Any) -> None:
        if not isinstance(payload, InstanceChangedEvent):
            return
        current = self._instance
        if payload.action == "selected":
            self._apply_instance(payload.instance)
        elif payload.action in {"updated", "cloned"} and current and payload.instance:
            if payload.instance.id == current.id:
                self._apply_instance(payload.instance)
        elif payload.action == "deleted" and current and payload.key == current.id:
            self._apply_instance(None)

    def _on_account_event(self, payload: Any) -> None:
        if not isinstance(payload, AccountChangedEvent):
            return
        if payload.action == "selected":
            self._apply_account(payload.account)
        elif payload.action in {"updated", "added"} and payload.account:
            if self._account and payload.account.id == self._account.id:
                self._apply_account(payload.account)
        elif (
            payload.action == "removed"
            and self._account
            and payload.account_id == self._account.id
        ):
            self._apply_account(self.accounts.active)

    def shutdown(self) -> None:
        """窗口关闭时的收尾：尽量终止游戏并停掉后台事件循环。"""
        process = self._process
        if process is not None and process.running:
            try:
                future = self.bridge.run_async(_terminate_and_wait(process))
                future.result(timeout=10)
            except Exception:  # noqa: BLE001 - 关闭阶段只记录
                logger.exception("cannot terminate game process during shutdown")
        self._set_process(None)
        self.bridge.close()


def _emit_progress(fraction: float, message: str) -> None:
    events.emit(
        events.EventType.PROGRESS,
        ProgressEvent(
            task_id="launch",
            current=int(max(0.0, min(fraction, 1.0)) * 1000),
            total=1000,
            message=message,
        ),
    )
    if message:
        events.log(message, level="debug", source="launch")


def _emit_game_line(source: str):
    def emit(line: str) -> None:
        if not line.strip():
            return
        events.log(line, level=classify_game_line(line), source=source)

    return emit


async def _wait_process(process: ManagedProcess) -> int:
    return await process.wait()


async def _terminate_and_wait(process: ManagedProcess) -> int:
    return await process.terminate()


_state: UIState | None = None


def get_state() -> UIState:
    global _state
    if _state is None:
        _state = UIState()
    return _state


def set_state(state: UIState | None) -> None:
    global _state
    _state = state
