# flint/ui/pages/settings/left.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem
from PySide6.QtCore import Signal

class SettingsLeftPanel(QWidget):
    category_selected = Signal(str)

    CATEGORIES = ("启动设置", "Java 设置", "界面外观",
                  "下载设置", "联机设置", "高级设置")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsLeftPanel")
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("CategoryList")
        layout.addWidget(self.list_widget)

        # 分类外置，随需而列
        for name in self.CATEGORIES:
            self.list_widget.addItem(QListWidgetItem(name))

        self.list_widget.currentTextChanged.connect(self.category_selected.emit)
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)