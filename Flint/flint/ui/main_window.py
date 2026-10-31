# flint/ui/main_window.py
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QSplitter,
    QTabBar, QLabel
)
from PySide6.QtCore import Qt, Signal

# 兼容单文件运行和工程化包导入
try:
    from .hint_bar import HintBar
except ImportError:
    from hint_bar import HintBar


class MainWindow(QMainWindow):
    tab_changed = Signal(int)

    def __init__(self, router=None, parent=None):
        super().__init__(parent)
        self.router = router
        self.setWindowTitle("Flint Launcher")
        self.setMinimumSize(1000, 680)
        self.init_ui()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶：四页
        self.tab_bar = QTabBar()
        self.tab_bar.setObjectName("MainTabBar")
        for name in ("启动", "下载", "设置", "更多"):
            self.tab_bar.addTab(name)
        self.tab_bar.currentChanged.connect(self._on_tab_changed)
        
        # 简单美化一下顶部标签
        self.tab_bar.setStyleSheet("""
            QTabBar::tab { padding: 10px 40px; font-size: 14px; color: #aaa; background: #2b2b2b; }
            QTabBar::tab:selected { color: white; border-bottom: 2px solid #3b82f6; }
        """)
        layout.addWidget(self.tab_bar)

        # 中：左右分栏
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setObjectName("MainSplitter")
        self.splitter.setChildrenCollapsible(False)

        self.left_widget = self._placeholder("左栏：版本列表", "LeftPane")
        self.right_widget = self._placeholder("右栏：启动面板", "RightPane")

        self.splitter.addWidget(self.left_widget)
        self.splitter.addWidget(self.right_widget)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([250, 750])
        layout.addWidget(self.splitter, 1)

        # 底：提示条
        self.hint_bar = HintBar()
        layout.addWidget(self.hint_bar)

    def _placeholder(self, text: str, object_name: str) -> QWidget:
        widget = QWidget()
        widget.setObjectName(object_name)
        widget.setMinimumWidth(250 if object_name == "LeftPane" else 0)
        
        # 简单加个背景色以便区分左右
        bg_color = "#2b2b2b" if object_name == "LeftPane" else "#1e1e1e"
        widget.setStyleSheet(f"background-color: {bg_color}; color: #888;")

        pane_layout = QVBoxLayout(widget)
        pane_layout.addWidget(QLabel(text))
        return widget

    def _on_tab_changed(self, index: int):
        self.tab_changed.emit(index)
        if self.router is not None:
            self.router.switch_tab(index)

    def show_hint(self, text: str, level: str = "info", duration: int = 3000):
        self.hint_bar.show_message(text, level=level, duration=duration)


if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication, QPushButton

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow()
    
    # 测试：在右栏加一个按钮测试 HintBar
    btn = QPushButton("点击测试 HintBar")
    btn.setFixedSize(150, 40)
    btn.setStyleSheet("background-color: #3b82f6; color: white; border-radius: 4px;")
    btn.clicked.connect(lambda: window.show_hint("这是一条测试提示消息！", "info"))
    
    window.right_widget.layout().addWidget(btn)
    window.right_widget.layout().addStretch()

    window.show()
    sys.exit(app.exec())