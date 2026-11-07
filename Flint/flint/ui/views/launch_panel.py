# flint/ui/views/launch_panel.py
"""启动面板：账户状态行 + 大启动按钮 + 内存滑块 + Java 选择 + 最近日志。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:
    from ..widgets.avatar import Avatar
    from ..widgets.big_button import BigButton
    from ..widgets.memory_slider import MemorySlider
except ImportError:  # pragma: no cover - 兼容直接运行单文件
    from widgets.avatar import Avatar
    from widgets.big_button import BigButton
    from widgets.memory_slider import MemorySlider

from flint.core.account import Account
from flint.core.instance import Instance


class AccountRow(QFrame):
    switch_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AccountRow")
        self.setFixedHeight(64)
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        self.avatar = Avatar(44)
        layout.addWidget(self.avatar)

        text = QVBoxLayout()
        text.setSpacing(0)
        self.name_label = QLabel("未登录")
        self.name_label.setObjectName("AccountName")
        self.type_label = QLabel("请添加账户")
        self.type_label.setObjectName("AccountType")
        text.addWidget(self.name_label)
        text.addWidget(self.type_label)
        layout.addLayout(text)
        layout.addStretch(1)

        self.switch_btn = QPushButton("切换")
        self.switch_btn.setObjectName("AccountSwitch")
        self.switch_btn.setFixedSize(64, 28)
        self.switch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.switch_btn.clicked.connect(self.switch_clicked.emit)
        layout.addWidget(self.switch_btn)

    def set_account(self, account: Account | None) -> None:
        if account is None:
            self.avatar.set_account("?")
            self.name_label.setText("未登录")
            self.type_label.setText("请添加账户")
            return
        self.avatar.set_account(account.name)
        self.name_label.setText(account.name)
        detail = account.display_type
        if account.is_microsoft and account.expired:
            detail += " · 登录已过期"
        self.type_label.setText(detail)



class LaunchPanel(QWidget):
    launch_requested = Signal()
    switch_account_requested = Signal()
    memory_changed = Signal(int)
    memory_committed = Signal(int)
    java_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LaunchPanel")
        self._current_instance: Instance | None = None
        self._loading_javas = False
        self._updating_memory = False
        self.init_ui()
        self.bind()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 8, 20, 20)
        layout.setSpacing(16)

        self.account_row = AccountRow()
        layout.addWidget(self.account_row)

        self.big_btn = BigButton("启动游戏")
        self.big_btn.setObjectName("LaunchButton")
        layout.addWidget(self.big_btn)

        memory_row = QHBoxLayout()
        memory_row.addWidget(QLabel("内存："))
        self.memory_slider = MemorySlider()
        memory_row.addWidget(self.memory_slider, 1)
        layout.addLayout(memory_row)

        java_row = QHBoxLayout()
        java_row.addWidget(QLabel("Java："))
        self.java_combo = QComboBox()
        self.java_combo.setObjectName("JavaSelector")
        java_row.addWidget(self.java_combo, 1)
        layout.addLayout(java_row)

        log_row = QVBoxLayout()
        log_row.setSpacing(4)
        log_title = QLabel("最近日志")
        log_title.setObjectName("SectionLabel")
        log_row.addWidget(log_title)
        self.log_brief = QPlainTextEdit()
        self.log_brief.setObjectName("LaunchLogBrief")
        self.log_brief.setReadOnly(True)
        self.log_brief.setMaximumBlockCount(3)
        self.log_brief.setFixedHeight(76)
        log_row.addWidget(self.log_brief)
        layout.addLayout(log_row)

        layout.addStretch(1)

    def bind(self):
        self.big_btn.clicked.connect(self._on_launch_clicked)
        self.account_row.switch_clicked.connect(self.switch_account_requested.emit)
        self.memory_slider.value_changed.connect(self._on_memory_changed)
        self.memory_slider.value_committed.connect(self.memory_committed.emit)
        self.java_combo.currentIndexChanged.connect(self._on_java_changed)

    def _on_launch_clicked(self):
        if self._current_instance is None:
            return
        self.launch_requested.emit()

    def _on_memory_changed(self, value: int):
        if self._updating_memory:
            return
        if self._current_instance is not None:
            self._current_instance.memory_mb = value
        self.memory_changed.emit(value)

    def _on_java_changed(self, _index: int):
        if self._loading_javas:
            return
        self.java_changed.emit(self.java_combo.currentData() or "")

    # -- 对外接口 -----------------------------------------------------------
    def set_instance(self, instance: Instance | None):
        self._current_instance = instance
        enabled = instance is not None
        self.big_btn.setEnabled(enabled)
        self.big_btn.setText("启动游戏")
        if instance is not None:
            self._updating_memory = True
            try:
                self.memory_slider.set_value(instance.memory_mb)
            finally:
                self._updating_memory = False

    def set_account(self, account: Account | None):
        self.account_row.set_account(account)

    def set_java_candidates(self, candidates, current: str = ""):
        """candidates: [(label, path), ...] 或纯字符串列表。"""
        self._loading_javas = True
        try:
            self.java_combo.clear()
            selected = -1
            for index, item in enumerate(candidates):
                if isinstance(item, (tuple, list)) and len(item) >= 2:
                    label, path = str(item[0]), str(item[1])
                else:
                    label, path = str(item), str(item)
                self.java_combo.addItem(label, path)
                if current and path == current:
                    selected = index
            if self.java_combo.count() == 0:
                self.java_combo.addItem("未检测到 Java", "")
            elif selected >= 0:
                self.java_combo.setCurrentIndex(selected)
        finally:
            self._loading_javas = False

    def append_log(self, line: str):
        self.log_brief.appendPlainText(line)

    def set_running(self, running: bool):
        if running:
            self.big_btn.set_loading(True)
        else:
            self.big_btn.set_loading(False)
            self.big_btn.setText("启动游戏")
            self.big_btn.setEnabled(self._current_instance is not None)
