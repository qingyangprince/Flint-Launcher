# flint/ui/widgets/log_view.py
from PySide6.QtWidgets import QPlainTextEdit
from PySide6.QtGui import QTextCursor

class LogView(QPlainTextEdit):
    """环而不断，色以辨级。"""
    MAX_LINES = 5000

    _COLORS = {
        "INFO": "#e0e0e0", "WARN": "#f59e0b",
        "ERROR": "#ef4444", "DEBUG": "#888888",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LogText")
        self.setReadOnly(True)
        self.setMaximumBlockCount(self.MAX_LINES)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)

    def append_line(self, line: str, level: str = "INFO", source: str = "启动器"):
        color = self._COLORS.get(level, "#e0e0e0")
        self.moveCursor(QTextCursor.End)
        self.appendHtml(
            f'<span style="color:{color}">[{level}] [{source}] {line}</span>'
        )