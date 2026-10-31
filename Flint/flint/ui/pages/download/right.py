# flint/ui/pages/download/right.py
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
)
from PySide6.QtCore import Qt, Signal


class DownloadRightPanel(QWidget):
    search_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DownloadRightPanel")
        self.init_ui()
        self.bind()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # 寻：一框一键
        search_row = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("搜索版本或模组…")
        self.search_box.returnPressed.connect(self._emit_search)

        self.search_btn = QPushButton("搜索")
        self.search_btn.setObjectName("SearchButton")
        self.search_btn.clicked.connect(self._emit_search)

        search_row.addWidget(self.search_box, 1)
        search_row.addWidget(self.search_btn, 0)
        layout.addLayout(search_row)

        self.content_label = QLabel("请在左侧选择分类")
        self.content_label.setObjectName("DownloadHint")
        self.content_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.content_label, 1)

    def bind(self):
        pass  # 后续接任务面板时扩展

    def _emit_search(self):
        self.search_requested.emit(self.search_box.text().strip())

    def set_category(self, category: str):
        self.content_label.setText(f"当前分类：{category}")