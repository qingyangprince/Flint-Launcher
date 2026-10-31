# flint/ui/widgets/category_panel.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem
from PySide6.QtCore import Signal

class CategoryPanel(QWidget):
    """一名一列；名出则事至。"""
    category_selected = Signal(str)

    def __init__(self, categories, object_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName(object_name)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("CategoryList")
        layout.addWidget(self.list_widget)

        self.set_categories(categories)
        self.list_widget.currentTextChanged.connect(self.category_selected.emit)

    def set_categories(self, categories):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for name in categories:
            self.list_widget.addItem(QListWidgetItem(name))
        self.list_widget.blockSignals(False)

        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)