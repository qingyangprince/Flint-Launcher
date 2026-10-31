# flint/ui/widgets/version_item.py
from PySide6.QtWidgets import QStyledItemDelegate, QStyle
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPainter, QColor, QFont


class VersionItemDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(0, 56)

    def paint(self, painter: QPainter, option, index):
        painter.save()
        rect = option.rect.adjusted(2, 2, -2, -2)

        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        bg = QColor("#3b82f6") if selected else (
            QColor("#3a3a3a") if hovered else QColor("#2b2b2b")
        )

        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 6, 6)

        # 名在上
        f = QFont(option.font)
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            rect.adjusted(12, 6, -12, -28),
            Qt.AlignLeft | Qt.AlignVCenter,
            index.data(Qt.DisplayRole) or "",
        )

        # 载于下
        f2 = QFont(option.font)
        f2.setPointSize(max(8, f2.pointSize() - 1))
        painter.setFont(f2)
        painter.setPen(QColor("#aaaaaa"))
        painter.drawText(
            rect.adjusted(12, 30, -12, -6),
            Qt.AlignLeft | Qt.AlignVCenter,
            index.data(Qt.UserRole + 1) or "",
        )

        painter.restore()