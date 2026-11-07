"""账户头像：圆形占位图，支持加载皮肤头像文件。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QWidget

_PALETTE = (
    "#3b82f6",
    "#8b5cf6",
    "#ec4899",
    "#f59e0b",
    "#10b981",
    "#06b6d4",
    "#ef4444",
    "#6366f1",
)


def color_for(name: str) -> QColor:
    digest = hashlib.sha1(name.encode("utf-8")).digest()
    return QColor(_PALETTE[digest[0] % len(_PALETTE)])


class Avatar(QWidget):
    """圆形头像；没有图片时用名字首字符与稳定配色兜底。"""

    def __init__(self, size: int = 40, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        self._name = ""
        self._pixmap: QPixmap | None = None
        self.setFixedSize(size, size)

    def set_account(self, name: str, skin_path: str | Path | None = None) -> None:
        self._name = name or ""
        self._pixmap = None
        if skin_path:
            pixmap = QPixmap(str(skin_path))
            if not pixmap.isNull():
                self._pixmap = pixmap
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0.5, 0.5, self._size - 1, self._size - 1)

        path = QPainterPath()
        path.addEllipse(rect)
        painter.setClipPath(path)

        if self._pixmap is not None:
            scaled = self._pixmap.scaled(
                self._size,
                self._size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(0, 0, scaled)
            painter.end()
            return

        painter.fillPath(path, color_for(self._name or "?"))
        if self._name:
            font = QFont(self.font())
            font.setBold(True)
            font.setPixelSize(max(12, self._size // 2))
            painter.setFont(font)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._name[0].upper())
        painter.end()
