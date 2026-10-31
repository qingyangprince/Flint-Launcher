# flint/ui/pages/download/left.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem
from PySide6.QtCore import Signal


class DownloadLeftPanel(QWidget):
    category_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DownloadLeftPanel")
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("CategoryList")
        layout.addWidget(self.list_widget)

        self.set_categories(["游戏版本", "Mod 模组", "整合包", "资源包"])

    def set_categories(self, categories):
        """分类自外入，界面不自决。"""
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for name in categories:
            self.list_widget.addItem(QListWidgetItem(name))
        self.list_widget.blockSignals(False)

        self.list_widget.currentTextChanged.connect(self.category_selected.emit)
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)