# flint/ui/views/account_panel.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

class AccountPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AccountPanel")
        l = QVBoxLayout(self)
        label = QLabel("账户管理 · 待接入 core.account")
        label.setAlignment(Qt.AlignCenter)
        label.setObjectName("PlaceholderLabel")
        l.addWidget(label)