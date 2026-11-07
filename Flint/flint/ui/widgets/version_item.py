"""实例列表项 delegate：图标块 + 版本名 + 加载器标签 + 选中/悬停态。"""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

_LOADER_COLORS = {
    "原版": QColor("#4b5563"),
    "Fabric": QColor("#d97706"),
    "Forge": QColor("#2563eb"),
    "Quilt": QColor("#7c3aed"),
    "Neoforge": QColor("#059669"),
}


def _loader_color(label: str) -> QColor:
    for key, color in _LOADER_COLORS.items():
        if label.startswith(key):
            return color
    return QColor("#4b5563")


class VersionItemDelegate(QStyledItemDelegate):
    ICON_SIZE = 32

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt 命名
        return QSize(0, 60)

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: N802
        painter.save()
        rect = option.rect.adjusted(2, 3, -2, -3)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        background = QColor("#3b82f6") if selected else QColor("#2b2b2b")
        if hovered and not selected:
            background = QColor("#363636")

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 8, 8)

        name = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        loader = str(index.data(Qt.ItemDataRole.UserRole + 1) or "")

        icon_rect = QRectF(rect.left() + 10, rect.top() + (rect.height() - 32) / 2, 32, 32)
        painter.setBrush(_loader_color(loader))
        painter.drawRoundedRect(icon_rect, 8, 8)
        painter.setPen(QColor("#ffffff"))
        icon_font = QFont(option.font)
        icon_font.setBold(True)
        painter.setFont(icon_font)
        painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, name[:1].upper() if name else "?")

        text_left = int(icon_rect.right()) + 10
        name_font = QFont(option.font)
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            QRect(text_left, rect.top() + 7, rect.width() - text_left - 8, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            name,
        )

        loader_font = QFont(option.font)
        loader_font.setPointSize(max(8, loader_font.pointSize() - 1))
        painter.setFont(loader_font)
        painter.setPen(QColor("#d1d5db") if not selected else QColor("#e5edff"))
        painter.drawText(
            QRect(text_left, rect.top() + 28, rect.width() - text_left - 8, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            loader,
        )

        painter.restore()
