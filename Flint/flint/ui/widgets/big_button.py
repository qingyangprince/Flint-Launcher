# flint/ui/widgets/big_button.py
from PySide6.QtWidgets import QPushButton
from PySide6.QtCore import QTimer, Qt

class BigButton(QPushButton):
    def __init__(self, text="启动游戏", parent=None):
        super().__init__(text, parent)
        self.setObjectName("BigButton") # 供 QSS 定制
        self.setMinimumHeight(48)
        self.setMaximumHeight(56)
        self.setCursor(Qt.PointingHandCursor) # 鼠标悬停变小手
        
        # 简单的默认样式（以后会抽离到 QSS 里）
        self.setStyleSheet("""
            QPushButton#BigButton {
                background-color: #3b82f6;
                color: white;
                font-size: 18px;
                font-weight: bold;
                border-radius: 8px;
            }
            QPushButton#BigButton:hover {
                background-color: #2563eb;
            }
            QPushButton#BigButton:disabled {
                background-color: #555555;
                color: #999999;
            }
        """)

        # 加载动画相关
        self._loading_text = "启动中"
        self._dot_count = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_loading_text)
        self._original_text = text

    def set_loading(self, is_loading: bool):
        """切换加载状态"""
        if is_loading:
            self.setEnabled(False) # 加载时禁用按钮
            self._dot_count = 0
            self.setText(f"{self._loading_text}.")
            self._timer.start(500) # 每 500 毫秒更新一次省略号
        else:
            self._timer.stop()
            self.setEnabled(True) # 恢复按钮
            self.setText(self._original_text)

    def _update_loading_text(self):
        """内部方法：更新点点点的动画"""
        self._dot_count = (self._dot_count + 1) % 3
        dots = "." * (self._dot_count + 1)
        self.setText(f"{self._loading_text}{dots}")