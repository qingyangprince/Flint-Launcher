"""启动页右栏：版本标题 + 启动面板（``views/launch_panel``）。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget

from flint.core.account import Account
from flint.core.instance import Instance
from flint.ui.views.launch_panel import LaunchPanel


class LaunchRightPanel(QWidget):
    launch_requested = Signal()
    switch_account_requested = Signal()
    memory_changed = Signal(int)
    memory_committed = Signal(int)
    java_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("RightPane")
        self._instance: Instance | None = None
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(12)

        header = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title_label = QLabel("未选择实例")
        self.title_label.setObjectName("LaunchTitle")
        self.subtitle_label = QLabel("在左侧选择一个实例，或点击“+ 新建”创建")
        self.subtitle_label.setObjectName("LaunchSubtitle")
        text.addWidget(self.title_label)
        text.addWidget(self.subtitle_label)
        header.addLayout(text)
        header.addStretch(1)
        self.loader_label = QLabel("")
        self.loader_label.setObjectName("LoaderBadge")
        self.loader_label.hide()
        header.addWidget(self.loader_label)
        layout.addLayout(header)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_label = QLabel("选择一个实例开始游戏")
        empty_label.setObjectName("EmptyHint")
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_label)
        self.stack.addWidget(empty)

        self.panel = LaunchPanel()
        self.stack.addWidget(self.panel)

        self.panel.launch_requested.connect(self.launch_requested.emit)
        self.panel.switch_account_requested.connect(self.switch_account_requested.emit)
        self.panel.memory_changed.connect(self.memory_changed.emit)
        self.panel.memory_committed.connect(self.memory_committed.emit)
        self.panel.java_changed.connect(self.java_changed.emit)

    # -- 对外接口 -----------------------------------------------------------
    def set_instance(self, instance: Instance | None) -> None:
        self._instance = instance
        self.panel.set_instance(instance)
        if instance is None:
            self.title_label.setText("未选择实例")
            self.subtitle_label.setText("在左侧选择一个实例，或点击“+ 新建”创建")
            self.loader_label.hide()
            self.stack.setCurrentIndex(0)
            return

        self.title_label.setText(f"{instance.name} · {instance.version}")
        directory = self.panel.property("game_dir")
        self.subtitle_label.setText(f"游戏目录：{directory}" if directory else "游戏目录：（待创建）")
        self.loader_label.setText(instance.display_loader)
        self.loader_label.show()
        self.stack.setCurrentIndex(1)

    def set_game_dir(self, directory: str) -> None:
        self.panel.setProperty("game_dir", directory)
        if self._instance is not None:
            self.subtitle_label.setText(f"游戏目录：{directory}")

    def set_account(self, account: Account | None) -> None:
        self.panel.set_account(account)

    def set_java_candidates(self, candidates, current: str = "") -> None:
        self.panel.set_java_candidates(candidates, current)

    def append_log(self, line: str) -> None:
        self.panel.append_log(line)

    def set_running(self, running: bool) -> None:
        self.panel.set_running(running)

    def current_instance(self) -> Instance | None:
        return self._instance
