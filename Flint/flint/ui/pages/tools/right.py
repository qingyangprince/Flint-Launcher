# flint/ui/pages/tools/right.py
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox, QStackedWidget,
)
from PySide6.QtCore import Signal

try:
    from ...widgets.log_view import LogView
    from ...views.about_panel import AboutPanel
    from ...views.mods_panel import ModsPanel
    from ...views.account_panel import AccountPanel
except ImportError:
    from widgets.log_view import LogView
    from views.about_panel import AboutPanel
    from views.mods_panel import ModsPanel
    from views.account_panel import AccountPanel

class ToolsRightPanel(QWidget):
    """四器一栈：日志、模组、账户、关于。"""

    log_cleared = Signal()
    log_export_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ToolsRightPanel")
        self._pages = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self._add_page("日志查看", self._build_log_page())
        self._add_page("模组管理", ModsPanel())
        self._add_page("账户管理", AccountPanel())
        self._add_page("关于 Flint", AboutPanel())

    def _add_page(self, key: str, widget: QWidget):
        self._pages[key] = widget
        self.stack.addWidget(widget)

    def set_category(self, category: str):
        widget = self._pages.get(category)
        if widget is not None:
            self.stack.setCurrentWidget(widget)

    def _build_log_page(self) -> QWidget:
        page = QWidget()
        l = QVBoxLayout(page)
        l.setSpacing(10)

        bar = QHBoxLayout()
        self.level_filter = QComboBox()
        self.level_filter.setObjectName("LogFilter")
        self.level_filter.addItems(["全部", "INFO", "WARN", "ERROR", "DEBUG"])

        self.source_filter = QComboBox()
        self.source_filter.setObjectName("LogFilter")
        self.source_filter.addItems(["全部", "启动器", "游戏", "下载"])

        self.clear_btn = QPushButton("清空")
        self.clear_btn.setObjectName("GhostButton")
        self.clear_btn.clicked.connect(self.log_cleared.emit)

        self.export_btn = QPushButton("导出")
        self.export_btn.setObjectName("GhostButton")
        self.export_btn.clicked.connect(self.log_export_requested.emit)

        bar.addWidget(self.level_filter)
        bar.addWidget(self.source_filter)
        bar.addStretch(1)
        bar.addWidget(self.clear_btn)
        bar.addWidget(self.export_btn)
        l.addLayout(bar)

        self.log_view = LogView()
        l.addWidget(self.log_view, 1)

        return page

    def append_log(self, line: str, level: str = "INFO", source: str = "启动器"):
        self.log_view.append_line(line, level=level, source=source)