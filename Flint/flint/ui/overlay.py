"""内容区遮罩 + 内嵌消息框，替代独立的 ``QMessageBox``。"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

AcceptCallback = Callable[[], bool | None]


class Overlay(QWidget):
    """覆盖父窗口内容区，居中显示卡片；支持确认/取消与自定义内容。"""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._on_accept: AcceptCallback | None = None
        self._build()
        parent.installEventFilter(self)
        self.hide()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)

        row = QHBoxLayout()
        row.addStretch(1)

        self.card = QFrame()
        self.card.setObjectName("OverlayCard")
        self.card.setMinimumWidth(360)
        self.card.setMaximumWidth(520)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(24, 20, 24, 18)
        card_layout.setSpacing(12)

        self.title_label = QLabel("")
        self.title_label.setObjectName("OverlayTitle")
        card_layout.addWidget(self.title_label)

        self.message_label = QLabel("")
        self.message_label.setObjectName("OverlayMessage")
        self.message_label.setWordWrap(True)
        card_layout.addWidget(self.message_label)

        self.content_host = QWidget()
        self.content_layout = QVBoxLayout(self.content_host)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(8)
        card_layout.addWidget(self.content_host)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("GhostButton")
        self.cancel_btn.clicked.connect(self.close_overlay)
        self.ok_btn = QPushButton("确定")
        self.ok_btn.setObjectName("OverlayOkButton")
        self.ok_btn.clicked.connect(self._accept)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.ok_btn)
        card_layout.addLayout(buttons)

        row.addWidget(self.card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

    # -- 对外接口 -----------------------------------------------------------
    def ask(
        self,
        title: str,
        message: str,
        *,
        ok_text: str = "确定",
        cancel_text: str = "取消",
        danger: bool = False,
        on_accept: AcceptCallback | None = None,
    ) -> None:
        self._reset_content()
        self.message_label.setText(message)
        self.message_label.show()
        self._show(title, ok_text, cancel_text, on_accept, danger)

    def show_content(
        self,
        title: str,
        content: QWidget,
        *,
        message: str = "",
        ok_text: str = "确定",
        cancel_text: str = "取消",
        on_accept: AcceptCallback | None = None,
    ) -> None:
        self._reset_content()
        self.message_label.setText(message)
        self.message_label.setVisible(bool(message))
        self.content_layout.addWidget(content)
        self._show(title, ok_text, cancel_text, on_accept, False)

    def close_overlay(self) -> None:
        self._on_accept = None
        self.hide()

    # -- 内部 ---------------------------------------------------------------
    def _show(
        self,
        title: str,
        ok_text: str,
        cancel_text: str,
        on_accept: AcceptCallback | None,
        danger: bool,
    ) -> None:
        self.title_label.setText(title)
        self.ok_btn.setText(ok_text)
        self.cancel_btn.setText(cancel_text)
        self.ok_btn.setProperty("danger", danger)
        self.ok_btn.style().unpolish(self.ok_btn)
        self.ok_btn.style().polish(self.ok_btn)
        self._on_accept = on_accept
        self._fit_parent()
        self.show()
        self.raise_()
        self.ok_btn.setFocus()

    def _accept(self) -> None:
        callback = self._on_accept
        if callback is not None and callback() is False:
            return
        self.close_overlay()

    def _reset_content(self) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _fit_parent(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Resize and self.isVisible():
            self._fit_parent()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # 吞掉点击，避免误触遮罩下的控件
        event.accept()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
        painter.end()
