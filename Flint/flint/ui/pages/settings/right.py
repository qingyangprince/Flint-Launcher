# flint/ui/pages/settings/right.py
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QLineEdit, QPushButton, QStackedWidget, QComboBox,
)
from PySide6.QtCore import Signal, Qt

class SettingsRightPanel(QWidget):
    """一栏数页，名至即显；一改即存，一键归元。"""

    setting_changed = Signal(str, object)   # (key, value)
    reset_requested = Signal(str)           # category

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsRightPanel")
        self._pages = {}
        self._current = None
        self.init_ui()
        self.bind()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self._add_page("启动设置", self._build_launch_page())
        self._add_page("Java 设置", self._build_java_page())
        self._add_page("界面外观", self._build_theme_page())
        for name in ("下载设置", "联机设置", "高级设置"):
            self._add_page(name, self._build_placeholder(name))

        # 一键归元
        footer = QHBoxLayout()
        footer.addStretch(1)
        self.reset_btn = QPushButton("恢复默认")
        self.reset_btn.setObjectName("ResetButton")
        footer.addWidget(self.reset_btn)
        layout.addLayout(footer)

    def bind(self):
        self.reset_btn.clicked.connect(self._on_reset)

    # -- 页构造 --

    def _build_launch_page(self) -> QWidget:
        page = QWidget()
        l = QVBoxLayout(page)
        l.addWidget(QLabel("<h2>启动设置</h2>"))

        self.cb_hide = QCheckBox("游戏启动后隐藏启动器")
        self.cb_hide.setChecked(True)
        self.cb_hide.toggled.connect(
            lambda v: self.setting_changed.emit("launch.hide_after_start", v)
        )

        l.addWidget(self.cb_hide)
        l.addStretch(1)
        return page

    def _build_java_page(self) -> QWidget:
        page = QWidget()
        l = QVBoxLayout(page)
        l.addWidget(QLabel("<h2>Java 设置</h2>"))
        l.addWidget(QLabel("自定义 Java 路径："))

        row = QHBoxLayout()
        self.java_path = QLineEdit()
        self.java_path.setObjectName("PathInput")
        self.java_path.setPlaceholderText("自动检测…")
        self.java_path.editingFinished.connect(
            lambda: self.setting_changed.emit("java.path", self.java_path.text().strip())
        )

        self.java_browse = QPushButton("浏览…")
        self.java_browse.setObjectName("BrowseButton")

        row.addWidget(self.java_path, 1)
        row.addWidget(self.java_browse, 0)
        l.addLayout(row)
        l.addStretch(1)
        return page

    def _build_theme_page(self) -> QWidget:
        page = QWidget()
        l = QVBoxLayout(page)
        l.addWidget(QLabel("<h2>界面外观</h2>"))

        row = QHBoxLayout()
        row.addWidget(QLabel("主题："))
        self.theme_combo = QComboBox()
        self.theme_combo.setObjectName("ThemeCombo")
        self.theme_combo.addItems(["深色", "浅色"])
        self.theme_combo.currentTextChanged.connect(
            lambda t: self.setting_changed.emit("ui.theme", t)
        )
        row.addWidget(self.theme_combo, 1)
        l.addLayout(row)
        l.addStretch(1)
        return page

    def _build_placeholder(self, name: str) -> QWidget:
        page = QWidget()
        l = QVBoxLayout(page)
        label = QLabel(f"<h2>{name}</h2><p>未至。</p>")
        label.setAlignment(Qt.AlignCenter)
        l.addWidget(label)
        return page

    def _add_page(self, key: str, widget: QWidget):
        self._pages[key] = widget
        self.stack.addWidget(widget)

    # -- 外部接口 --

    def set_category(self, category: str):
        widget = self._pages.get(category)
        if widget is None:
            return
        self._current = category
        self.stack.setCurrentWidget(widget)

    def reset_current(self):
        self._on_reset()

    def _on_reset(self):
        if self._current:
            self.reset_requested.emit(self._current)