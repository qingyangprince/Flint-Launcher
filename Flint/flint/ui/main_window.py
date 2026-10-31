# flint/ui/main_window.py
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QSplitter,
    QTabBar, QLabel, QApplication
)
from PySide6.QtCore import Qt, Signal, QTimer

try:
    from .hint_bar import HintBar
    from .pages.launch.left import LaunchLeftPanel
    from .views.launch_panel import LaunchPanel
except ImportError:
    from hint_bar import HintBar
    from pages.launch.left import LaunchLeftPanel
    from views.launch_panel import LaunchPanel


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
        
        # ==========================================
        # 🎨 全局样式表（未来可以抽离到 theme/dark.qss）
        # ==========================================
        self.setStyleSheet("""
            /* 全局基础 */
            QWidget {
                color: #e0e0e0;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            }

            /* 主分栏背景 */
            #MainSplitter {
                background-color: #1a1a1a;
            }

            /* 顶部标签栏 */
            #MainTabBar::tab {
                background-color: #1e1e1e;
                padding: 12px 40px;
                font-size: 14px;
                color: #888;
                border-bottom: 2px solid transparent;
            }
            #MainTabBar::tab:selected {
                color: #3b82f6;
                border-bottom: 2px solid #3b82f6;
                background-color: #252525;
            }
            #MainTabBar::tab:hover {
                color: #ccc;
            }

            /* 账户状态行 */
            #AccountRow {
                background-color: #2b2b2b;
                border-radius: 8px;
            }
            #AccountName {
                font-size: 16px;
                font-weight: bold;
                color: #ffffff;
            }
            #AccountType {
                font-size: 12px;
                color: #aaaaaa;
            }
            #AccountSwitch {
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 4px;
                color: #ccc;
            }
            #AccountSwitch:hover {
                background-color: #4a4a4a;
                color: white;
            }

            /* 大启动按钮 */
            #LaunchButton {
                background-color: #3b82f6;
                color: white;
                font-size: 18px;
                font-weight: bold;
                border-radius: 8px;
                border: none;
            }
            #LaunchButton:hover {
                background-color: #2563eb;
            }
            #LaunchButton:disabled {
                background-color: #555555;
                color: #999999;
            }

            /* Java 下拉框 */
            #JavaSelector {
                background-color: #2b2b2b;
                border: 1px solid #444;
                border-radius: 6px;
                padding: 6px 10px;
                color: white;
            }
            #JavaSelector::drop-down {
                border: none;
                width: 20px;
            }

            /* 底部日志框 */
            #LaunchLogBrief {
                background-color: #121212;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 6px;
                color: #888;
                font-family: Consolas, monospace;
                font-size: 12px;
            }

            /* 内存滑块 */
            #MemorySlider QSlider::groove:horizontal {
                height: 6px;
                background: #333;
                border-radius: 3px;
            }
            #MemorySlider QSlider::handle:horizontal {
                background: #3b82f6;
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            #MemorySlider QSlider::sub-page:horizontal {
                background: #3b82f6;
                border-radius: 3px;
            }
            #MemoryValue {
                color: #3b82f6;
                font-weight: bold;
            }
            
            /* 左侧列表 */
            #LaunchLeftPanel {
                background-color: #1a1a1a;
                border-right: 1px solid #222;
            }
            #NewInstanceButton {
                background-color: #2b2b2b;
                border: 1px solid #444;
                border-radius: 6px;
                padding: 8px;
                color: #ccc;
            }
            #NewInstanceButton:hover {
                background-color: #3a3a3a;
                color: white;
            }
        """)
        # =========================================

        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

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

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setObjectName("MainSplitter")
        self.splitter.setChildrenCollapsible(False)

        # 左栏
        self.left_widget = LaunchLeftPanel()
        self.left_widget.setStyleSheet("background-color: #1e1e1e;")
        self.left_widget.set_versions([
            ("1.20.1", "Fabric"), ("1.19.2", "Forge"),
            ("1.12.2", "原版"), ("1.7.10", "Forge")
        ])
        self.left_widget.version_selected.connect(self._on_version_selected)

        # 右栏：使用重构后的启动面板
        self.right_widget = LaunchPanel()
        self.right_widget.setStyleSheet("background-color: #1e1e1e;")
        
        # 注入测试数据
        self.right_widget.set_account("Steve", "微软账户", "👤")
        self.right_widget.set_java_candidates(["Java 17 (内置)", "Java 21 (系统)"])
        self.right_widget.append_log("加载配置文件成功...")
        self.right_widget.append_log("检查版本资源完整性...")

        # 绑定信号
        self.right_widget.launch_requested.connect(self._on_launch_clicked)
        self.right_widget.switch_account_requested.connect(self._on_switch_account)

        self.splitter.addWidget(self.left_widget)
        self.splitter.addWidget(self.right_widget)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([250, 750])
        layout.addWidget(self.splitter, 1)

        self.hint_bar = HintBar()
        layout.addWidget(self.hint_bar)

    def _on_tab_changed(self, index: int):
        self.tab_changed.emit(index)
        if self.router is not None:
            self.router.switch_tab(index)

    def _on_version_selected(self, version_name: str):
        self.show_hint(f"你选中了版本：{version_name}", "info")

    def _on_launch_clicked(self):
        self.right_widget.set_running(True)
        self.show_hint("正在尝试启动游戏...", "info")
        self.right_widget.append_log("正在启动 Java 进程...")
        
        # 模拟启动
        QTimer.singleShot(3000, lambda: self.right_widget.set_running(False))
        QTimer.singleShot(3000, lambda: self.show_hint("启动准备就绪！", "info"))
        QTimer.singleShot(3000, lambda: self.right_widget.append_log("游戏进程已启动。"))

    def _on_switch_account(self):
        self.show_hint("准备打开账户切换窗口...", "info")

    def show_hint(self, text: str, level: str = "info", duration: int = 3000):
        self.hint_bar.show_message(text, level=level, duration=duration)


if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())