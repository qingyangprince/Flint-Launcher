# flint/ui/main_window.py
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QSplitter,
    QTabBar, QLabel, QApplication, QPushButton
)
from PySide6.QtCore import Qt, Signal, QTimer

# 兼容单文件运行和工程化包导入
try:
    from .hint_bar import HintBar
    from .pages.launch.left import LaunchLeftPanel
    from .widgets.big_button import BigButton
except ImportError:
    from hint_bar import HintBar
    from pages.launch.left import LaunchLeftPanel
    from widgets.big_button import BigButton


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

        # 1. 顶：四页标签
        self.tab_bar = QTabBar()
        self.tab_bar.setObjectName("MainTabBar")
        for name in ("启动", "下载", "设置", "更多"):
            self.tab_bar.addTab(name)
        self.tab_bar.currentChanged.connect(self._on_tab_changed)
        
        self.tab_bar.setStyleSheet("""
            QTabBar::tab { padding: 10px 40px; font-size: 14px; color: #aaa; background: #2b2b2b; }
            QTabBar::tab:selected { color: white; border-bottom: 2px solid #3b82f6; }
        """)
        layout.addWidget(self.tab_bar)

        # 2. 中：左右分栏
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setObjectName("MainSplitter")
        self.splitter.setChildrenCollapsible(False)

        # 左侧：引入刚才写的版本列表
        self.left_widget = LaunchLeftPanel()
        self.left_widget.setStyleSheet("background-color: #1e1e1e;")
        # 注入测试数据
        self.left_widget.set_versions([
            ("1.20.1", "Fabric"),
            ("1.19.2", "Forge"),
            ("1.12.2", "原版"),
            ("1.7.10", "Forge")
        ])
        # 监听左栏选中信号
        self.left_widget.version_selected.connect(self._on_version_selected)

        # 右侧：占位符（稍后在测试代码里塞入 BigButton）
        self.right_widget = self._placeholder("右栏：启动面板", "RightPane")

        self.splitter.addWidget(self.left_widget)
        self.splitter.addWidget(self.right_widget)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([250, 750])
        layout.addWidget(self.splitter, 1)

        # 3. 底：提示条
        self.hint_bar = HintBar()
        layout.addWidget(self.hint_bar)

    def _placeholder(self, text: str, object_name: str) -> QWidget:
        widget = QWidget()
        widget.setObjectName(object_name)
        bg_color = "#2b2b2b" if object_name == "LeftPane" else "#1e1e1e"
        widget.setStyleSheet(f"background-color: {bg_color}; color: #888;")
        pane_layout = QVBoxLayout(widget)
        pane_layout.addWidget(QLabel(text))
        return widget

    def _on_tab_changed(self, index: int):
        self.tab_changed.emit(index)
        if self.router is not None:
            self.router.switch_tab(index)

    def _on_version_selected(self, version_name: str):
        """处理左栏传来的选中事件"""
        self.show_hint(f"你选中了版本：{version_name}", "info")

    def show_hint(self, text: str, level: str = "info", duration: int = 3000):
        self.hint_bar.show_message(text, level=level, duration=duration)


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow()
    
    # 把刚才写的 BigButton 添加到右栏进行测试
    big_btn = BigButton("启动游戏")
    
    def on_click():
        big_btn.set_loading(True)
        window.show_hint("正在尝试启动游戏...", "info")
        # 模拟 3 秒后启动完成
        QTimer.singleShot(3000, lambda: big_btn.set_loading(False))
        QTimer.singleShot(3000, lambda: window.show_hint("启动准备就绪！", "info"))

    big_btn.clicked.connect(on_click)
    
    window.right_widget.layout().addWidget(big_btn)
    window.right_widget.layout().addStretch()

    window.show()
    sys.exit(app.exec())