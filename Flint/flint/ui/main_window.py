"""主窗口：顶部 QTabBar + 中部左右分栏 + 底部 HintBar。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from flint.core import config as config_module
from flint.core import events
from flint.core.account import Account
from flint.core.events import LogEvent
from flint.core.instance import Instance
from flint.infra.process import ManagedProcess
from flint.platform import java as java_module

from .hint_bar import HintBar
from .pages.download.left import DownloadLeftPanel
from .pages.download.right import DownloadRightPanel
from .pages.launch.left import LaunchLeftPanel
from .pages.launch.right import LaunchRightPanel
from .pages.settings.left import SettingsLeftPanel
from .pages.settings.right import SettingsRightPanel
from .pages.tools.left import ToolsLeftPanel
from .pages.tools.right import ToolsRightPanel
from .router import Router
from .state import UIState, get_state

logger = logging.getLogger(__name__)

QSS_DIR = Path(__file__).parent / "theme"
LOG_SOURCE_NAMES = {"launcher": "启动器", "game": "游戏", "download": "下载", "launch": "启动器"}


class MainWindow(QMainWindow):
    tab_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None, *, state: UIState | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Flint Launcher")
        self.setMinimumSize(1000, 680)

        self.state = state or get_state()
        self._java_runtimes: list[java_module.JavaRuntime] = []

        self.init_ui()
        self.load_theme()
        self.connect_state()
        self.reload_java_async()

    # -- 布局 ---------------------------------------------------------------
    def init_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tab_bar = QTabBar()
        self.tab_bar.setObjectName("MainTabBar")
        for name in ("启动", "下载", "设置", "更多"):
            self.tab_bar.addTab(name)
        layout.addWidget(self.tab_bar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("MainSplitter")
        self.splitter.setChildrenCollapsible(False)

        self.left_stack = QStackedWidget()
        self.right_stack = QStackedWidget()
        self.router = Router(self.left_stack, self.right_stack, self)

        self._build_launch_page()  # 0
        self._build_download_page()  # 1
        self._build_settings_page()  # 2
        self._build_tools_page()  # 3

        self.splitter.addWidget(self.left_stack)
        self.splitter.addWidget(self.right_stack)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([260, 740])
        layout.addWidget(self.splitter, 1)

        self.hint_bar = HintBar()
        layout.addWidget(self.hint_bar)

        self.tab_bar.currentChanged.connect(self._on_tab_changed)
        self.tab_bar.setCurrentIndex(0)
        self._on_tab_changed(0)

    def _build_launch_page(self) -> None:
        self.launch_left = LaunchLeftPanel(self.state.instances)
        self.launch_right = LaunchRightPanel()
        self.launch_left.instance_selected.connect(self._on_instance_selected)
        self.launch_left.new_requested.connect(lambda: self.tab_bar.setCurrentIndex(1))
        self.launch_left.instances_changed.connect(self._on_instances_changed)
        self.launch_left.error_occurred.connect(lambda msg: self.show_hint(msg, "error"))
        self.launch_left.info_message.connect(lambda msg: self.show_hint(msg, "info"))

        self.launch_right.launch_requested.connect(self._on_launch_clicked)
        self.launch_right.switch_account_requested.connect(self._show_accounts)
        self.launch_right.memory_changed.connect(self._on_memory_changed)
        self.launch_right.memory_committed.connect(self._on_memory_committed)
        self.launch_right.java_changed.connect(self._on_java_changed)

        self.router.register(0, self.launch_left, self.launch_right)
        self.launch_left.reload()

    def _build_download_page(self) -> None:
        left = DownloadLeftPanel()
        right = DownloadRightPanel()
        left.category_selected.connect(right.set_category)
        right.search_requested.connect(lambda kw: self.show_hint(f"搜索：{kw}", "info"))
        self.router.register(1, left, right)

    def _build_settings_page(self) -> None:
        left = SettingsLeftPanel()
        right = SettingsRightPanel()
        left.category_selected.connect(right.set_category)
        right.setting_changed.connect(self._on_setting_changed)
        right.reset_requested.connect(self._on_setting_reset)
        self.router.register(2, left, right)

    def _build_tools_page(self) -> None:
        self.tools_left = ToolsLeftPanel()
        self.tools_right = ToolsRightPanel()
        self.tools_left.category_selected.connect(self.tools_right.set_category)
        self.tools_right.log_cleared.connect(self.tools_right.log_view.clear)
        self.tools_right.log_export_requested.connect(
            lambda: self.show_hint("日志导出将在后续版本提供", "warn")
        )
        self.router.register(3, self.tools_left, self.tools_right)

    # -- 状态信号 -----------------------------------------------------------
    def connect_state(self) -> None:
        self.state.instance_changed.connect(self._on_state_instance_changed)
        self.state.account_changed.connect(self._on_account_changed)
        self.state.process_changed.connect(self._on_process_changed)
        self.state.launch_started.connect(self._on_launch_started)
        self.state.launch_finished.connect(self._on_launch_finished)
        self.state.launch_failed.connect(lambda msg: self._on_launch_failed(msg))
        self.state.bridge.log.connect(self._on_log_event)
        self.state.bridge.progress.connect(self._on_progress_event)

        self._on_account_changed(self.state.current_account)
        if self.state.current_instance is not None:
            self._apply_instance(self.state.current_instance)

    def _on_state_instance_changed(self, instance: Instance | None) -> None:
        if instance is None:
            self.launch_right.set_instance(None)
            if self.launch_left.current_instance() is not None:
                self.launch_left.reload()
            return
        current = self.launch_left.current_instance()
        if current is None or current.id != instance.id:
            self.launch_left.select(instance.id)
        self._apply_instance(instance)

    def _apply_instance(self, instance: Instance | None) -> None:
        self.launch_right.set_instance(instance)
        if instance is None:
            return
        directory = self.state.instances.directory_for(instance)
        self.launch_right.set_game_dir(str(directory))
        self._refresh_java_combo(instance)

    def _on_instance_selected(self, instance: Instance | None) -> None:
        selected = self.state.select_instance(instance)
        self._apply_instance(selected)

    def _on_instances_changed(self) -> None:
        self._apply_instance(self.launch_left.current_instance())

    def _on_account_changed(self, account: Account | None) -> None:
        self.launch_right.set_account(account)

    def _on_process_changed(self, process: ManagedProcess | None) -> None:
        self.launch_right.set_running(process is not None)

    def reload_java_async(self) -> None:
        self.state.bridge.run_async(
            asyncio.to_thread(java_module.discover),
            on_done=self._on_java_loaded,
            on_error=self._on_java_failed,
        )

    def _on_java_loaded(self, runtimes) -> None:
        self._java_runtimes = list(runtimes)
        instance = self.state.current_instance
        if instance is not None:
            self._refresh_java_combo(instance)
        logger.info("detected %d java runtime(s)", len(self._java_runtimes))

    def _on_java_failed(self, error: BaseException) -> None:
        logger.warning("java detection failed: %s", error)

    def _refresh_java_combo(self, instance: Instance) -> None:
        candidates = [(runtime.label, str(runtime.path)) for runtime in self._java_runtimes]
        current = instance.java_path
        if not current and self._java_runtimes:
            recommended = java_module.recommend_major(instance.version)
            best = java_module.select_runtime(self._java_runtimes, recommended)
            current = str(best.path) if best is not None else ""
        if not candidates:
            candidates = [("未检测到 Java", "")]
        self.launch_right.set_java_candidates(candidates, current)

    # -- 启动页交互 ---------------------------------------------------------
    def _on_launch_clicked(self) -> None:
        self.state.start_game()

    def _on_launch_started(self, instance: Instance) -> None:
        self.launch_right.set_running(True)
        self.show_hint(f"正在准备启动 {instance.name}…", "info")

    def _on_launch_finished(self, returncode: int) -> None:
        self.launch_right.set_running(False)
        level = "info" if returncode == 0 else "error"
        self.show_hint(f"游戏已退出（退出码 {returncode}）", level)

    def _on_launch_failed(self, message: str) -> None:
        self.launch_right.set_running(False)
        self.show_hint(message, "error", duration=0)

    def _on_memory_changed(self, value: int) -> None:
        # 面板已就地修改 Instance 对象；这里只在需要时同步状态
        instance = self.state.current_instance
        if instance is not None:
            instance.memory_mb = value

    def _on_memory_committed(self, value: int) -> None:
        instance = self.state.current_instance
        if instance is None:
            return
        try:
            updated = self.state.instances.update(instance, memory_mb=value)
        except Exception as exc:  # noqa: BLE001 - 交给提示条
            self.show_hint(str(exc), "error")
            return
        self.state.select_instance(updated)

    def _on_java_changed(self, path: str) -> None:
        instance = self.state.current_instance
        if instance is None or instance.java_path == path:
            return
        try:
            updated = self.state.instances.update(instance, java_path=path)
        except Exception as exc:  # noqa: BLE001
            self.show_hint(str(exc), "error")
            return
        self.state.select_instance(updated)

    def _show_accounts(self) -> None:
        self.tab_bar.setCurrentIndex(3)
        self.tools_left.select("账户管理")
        self.tools_right.set_category("账户管理")

    # -- 日志/进度 ----------------------------------------------------------
    def _on_log_event(self, payload) -> None:
        if not isinstance(payload, LogEvent):
            return
        line = payload.message
        self.launch_right.append_log(line)
        self.tools_right.append_log(
            line,
            level=payload.level.upper(),
            source=LOG_SOURCE_NAMES.get(payload.source, payload.source),
        )

    def _on_progress_event(self, payload) -> None:
        message = getattr(payload, "message", "")
        if message:
            logger.debug("progress: %s", message)

    # -- 其它页占位逻辑 -----------------------------------------------------
    def _on_tab_changed(self, index: int) -> None:
        self.tab_changed.emit(index)
        self.state.set_tab(index)
        if not self.router.switch_tab(index):
            self.show_hint(f"页面 {index} 尚未就绪", "warn")

    def _on_setting_changed(self, key: str, value) -> None:
        self.show_hint(f"{key} → {value}", "info")

    def _on_setting_reset(self, category: str) -> None:
        self.show_hint(f"{category} 已归元", "info")

    # -- 公共 ---------------------------------------------------------------
    def show_hint(self, text: str, level: str = "info", duration: int = 3000) -> None:
        self.hint_bar.show_message(text, level=level, duration=duration)

    def load_theme(self, name: str | None = None) -> None:
        theme = name or str(config_module.get_config().get("ui.theme") or "dark")
        path = QSS_DIR / f"{theme}.qss"
        if not path.is_file():
            path = QSS_DIR / "dark.qss"
        if path.is_file():
            self.setStyleSheet(path.read_text(encoding="utf-8"))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        try:
            self.state.shutdown()
        finally:
            super().closeEvent(event)


if __name__ == "__main__":  # pragma: no cover - 便于单独调试主窗口
    import sys

    from PySide6.QtWidgets import QApplication

    from flint.app import _setup_logging

    _setup_logging(True)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    events.log("主窗口调试模式", source="launcher")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
