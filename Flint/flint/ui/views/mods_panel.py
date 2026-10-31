# flint/ui/views/mods_panel.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

class ModsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ModsPanel")
        l = QVBoxLayout(self)
        label = QLabel("模组管理 · 待接入 core.mods")
        label.setAlignment(Qt.AlignCenter)
        label.setObjectName("PlaceholderLabel")
        l.addWidget(label)
    