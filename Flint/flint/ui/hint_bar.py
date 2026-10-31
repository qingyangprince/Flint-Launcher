# flint/ui/hint_bar.py
from PySide6.QtWidgets import (
    QFrame, QLabel, QHBoxLayout, QVBoxLayout, QWidget,
    QPushButton, QGraphicsOpacityEffect,
)
from PySide6.QtCore import QTimer, QPropertyAnimation, QEasingCurve


class HintBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HintBar")
        self._hiding = False
        self.init_ui()
        self.init_anim()
        self.hide()  # 初隐

    def init_ui(self):
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(10, 5, 10, 5)

        self.label = QLabel("提示信息")
        self.main_layout.addWidget(self.label, 1)

        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(20, 20)
        self.close_btn.setStyleSheet(
            "border: none; color: white; font-weight: bold; background: transparent;"
        )
        self.close_btn.clicked.connect(self.hide_bar)
        self.main_layout.addWidget(self.close_btn, 0)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide_bar)

    def init_anim(self):
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)

        self.fade = QPropertyAnimation(self.effect, b"opacity", self)
        self.fade.setDuration(180)
        self.fade.setEasingCurve(QEasingCurve.OutCubic)
        self.fade.finished.connect(self._on_fade_finished)

    def set_style(self, level: str):
        # 色随级转
        if level == "info":
            self.setStyleSheet(
                "QFrame#HintBar { background-color: #3b82f6; border-radius: 4px; }"
                "QLabel { color: white; }"
            )
            self.close_btn.hide()
        elif level == "warn":
            self.setStyleSheet(
                "QFrame#HintBar { background-color: #f59e0b; border-radius: 4px; }"
                "QLabel { color: white; }"
            )
            self.close_btn.hide()
        elif level == "error":
            self.setStyleSheet(
                "QFrame#HintBar { background-color: #ef4444; border-radius: 4px; }"
                "QLabel { color: white; }"
            )
            self.close_btn.show()

    def show_message(self, text: str, level: str = "info", duration: int = 3000):
        self.timer.stop()
        self.label.setText(text)
        self.set_style(level)
        self._fade_in()

        # 三秒即散；错，待手
        if level in ("info", "warn"):
            self.timer.start(duration)

    def hide_bar(self):
        self.timer.stop()
        if not self.isVisible():
            return

        self._hiding = True
        self.fade.stop()
        self.fade.setStartValue(self.effect.opacity())
        self.fade.setEndValue(0.0)
        self.fade.start()

    def _fade_in(self):
        self._hiding = False
        self.effect.setOpacity(0.0)
        self.show()

        self.fade.stop()
        self.fade.setStartValue(0.0)
        self.fade.setEndValue(1.0)
        self.fade.start()

    def _on_fade_finished(self):
        if self._hiding:
            self.hide()


# 测试：观其变
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    window = QWidget()
    window.setWindowTitle("HintBar 测试窗口")
    window.resize(500, 300)

    layout = QVBoxLayout(window)
    layout.addStretch(1)

    hint = HintBar(window)
    layout.addWidget(hint)

    hint.show_message("欢迎使用 Flint 启动器！", level="info")
    QTimer.singleShot(3000, lambda: hint.show_message("网络有点慢，正在重试...", level="warn"))
    QTimer.singleShot(6000, lambda: hint.show_message("启动失败：找不到 Java！", level="error"))

    window.show()
    sys.exit(app.exec())