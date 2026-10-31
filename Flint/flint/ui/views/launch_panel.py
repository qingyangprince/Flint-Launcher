# flint/ui/views/launch_panel.py
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QComboBox, QPlainTextEdit,
)
from PySide6.QtCore import Signal, Qt

try:
    from ..widgets.big_button import BigButton
    from ..widgets.memory_slider import MemorySlider
except ImportError:
    from widgets.big_button import BigButton
    from widgets.memory_slider import MemorySlider

class AccountRow(QFrame):
    switch_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AccountRow")
        self.setFixedHeight(60)
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)

        self.avatar_label = QLabel("👤")
        self.avatar_label.setObjectName("AccountAvatar")
        layout.addWidget(self.avatar_label)

        text = QVBoxLayout()
        text.setSpacing(0)

        self.name_label = QLabel("—")
        self.name_label.setObjectName("AccountName")
        self.type_label = QLabel("未登录")
        self.type_label.setObjectName("AccountType")

        text.addWidget(self.name_label)
        text.addWidget(self.type_label)
        layout.addLayout(text)
        layout.addStretch(1)

        self.switch_btn = QPushButton("切换")
        self.switch_btn.setObjectName("AccountSwitch")
        self.switch_btn.setFixedSize(60, 28)
        self.switch_btn.setCursor(Qt.PointingHandCursor)
        self.switch_btn.clicked.connect(self.switch_clicked.emit)
        layout.addWidget(self.switch_btn)

    def set_account(self, name: str, account_type: str, avatar_text: str = "👤"):
        self.name_label.setText(name or "—")
        self.type_label.setText(account_type or "未登录")
        self.avatar_label.setText(avatar_text or "👤")


class LaunchPanel(QWidget):
    launch_requested = Signal()
    switch_account_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LaunchPanel")
        self.init_ui()
        self.bind()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        self.account_row = AccountRow()
        layout.addWidget(self.account_row)

        self.big_btn = BigButton("启动游戏")
        self.big_btn.setObjectName("LaunchButton")
        layout.addWidget(self.big_btn)

        self.memory_slider = MemorySlider()
        layout.addWidget(self.memory_slider)

        java_row = QHBoxLayout()
        java_row.addWidget(QLabel("Java："))
        self.java_combo = QComboBox()
        self.java_combo.setObjectName("JavaSelector")
        java_row.addWidget(self.java_combo, 1)
        layout.addLayout(java_row)

        self.log_brief = QPlainTextEdit()
        self.log_brief.setObjectName("LaunchLogBrief")
        self.log_brief.setReadOnly(True)
        self.log_brief.setMaximumBlockCount(3)
        self.log_brief.setFixedHeight(72)
        layout.addWidget(self.log_brief)

        layout.addStretch(1)

    def bind(self):
        self.big_btn.clicked.connect(self.launch_requested.emit)
        self.account_row.switch_clicked.connect(self.switch_account_requested.emit)

    def set_account(self, name: str, account_type: str, avatar_text: str = "👤"):
        self.account_row.set_account(name, account_type, avatar_text)

    def set_java_candidates(self, paths):
        self.java_combo.clear()
        self.java_combo.addItems(paths)

    def append_log(self, line: str):
        self.log_brief.appendPlainText(line)

    def set_running(self, running: bool):
        self.big_btn.setEnabled(not running)
        self.big_btn.setText("启动中…" if running else "启动游戏")