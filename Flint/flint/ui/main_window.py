# flint/ui/main_window.py
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QSplitter,
    QTabBar, QLabel, QApplication, QStackedWidget,
)
from PySide6.QtCore import Qt, Signal, QTimer

from .hint_bar import HintBar
from .router import Router
from .pages.launch.left import LaunchLeftPanel
from .pages.download.left import DownloadLeftPanel
from .pages.download.right import DownloadRightPanel
from .pages.settings.left import SettingsLeftPanel
from .pages.settings.right import SettingsRightPanel
from .views.launch_panel import LaunchPanel

QSS_PATH = Path(__file__).parent / "theme" / "dark.qss"

class MainWindow(QMainWindow):
    tab_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Flint Launcher")
        self.setMinimumSize(1000, 680)
        self.init_ui()
        self._load_qss()

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
        layout.addWidget(self.tab_bar)

        # 中：左右二栈，路由统揽
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setObjectName("MainSplitter")
        self.splitter.setChildrenCollapsible(False)

        self.left_stack = QStackedWidget()
        self.right_stack = QStackedWidget()
        self.router = Router(self.left_stack, self.right_stack, self)

        # 页面注册顺序必须和 tab_bar 的索引一致
        self._build_launch_page()       # 0
        self._build_download_page()     # 1
        self._build_settings_page()     # 2
        self._build_placeholder_page("更多") # 3

        self.splitter.addWidget(self.left_stack)
        self.splitter.addWidget(self.right_stack)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([250, 750])
        layout.addWidget(self.splitter, 1)

        # 底：一条提示
        self.hint_bar = HintBar()
        layout.addWidget(self.hint_bar)

        self.tab_bar.currentChanged.connect(self._on_tab_changed)
        self.tab_bar.setCurrentIndex(0)
        self._on_tab_changed(0)

    def _build_launch_page(self):
        left = LaunchLeftPanel()
        left.set_versions([("1.20.1", "Fabric"), ("1.12.2", "原版")])
        left.version_selected.connect(self._on_version_selected)
        left.new_requested.connect(lambda: self.tab_bar.setCurrentIndex(1))

        right = LaunchPanel()
        right.set_account("Steve", "微软账户", "👤")
        right.set_java_candidates(["Java 17 (内置)", "Java 21 (系统)"])
        right.launch_requested.connect(self._on_launch_clicked)
        right.switch_account_requested.connect(
            lambda: self.show_hint("切换账户", "info")
        )

        self.router.register(0, left, right)

    def _build_download_page(self):
        left = DownloadLeftPanel()
        right = DownloadRightPanel()
        left.category_selected.connect(right.set_category)
        right.search_requested.connect(
            lambda kw: self.show_hint(f"搜索：{kw}", "info")
        )
        self.router.register(1, left, right)

    def _build_settings_page(self):
        left = SettingsLeftPanel()
        right = SettingsRightPanel()
        
        left.category_selected.connect(right.set_category)
        right.setting_changed.connect(self._on_setting_changed)
        right.reset_requested.connect(self._on_setting_reset)

        idx = self.left_stack.count()  # 索引由栈自长，不假人手
        self.router.register(idx, left, right)

    def _build_placeholder_page(self, name: str):
        idx = self.left_stack.count()
        self.router.register(idx, self._placeholder(f"{name} · 左"), self._placeholder(f"{name} · 右"))

    def _placeholder(self, text: str) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        label = QLabel(text)
        label.setObjectName("PlaceholderLabel")
        label.setAlignment(Qt.AlignCenter)
        l.addWidget(label)
        return w

    def _on_tab_changed(self, index: int):
        self.tab_changed.emit(index)
        if not self.router.switch_tab(index):
            self.show_hint(f"页面 {index} 尚未就绪", "warn")

    def _on_version_selected(self, version_name: str):
        self.show_hint(f"选中版本：{version_name}", "info")

    def _on_launch_clicked(self):
        self.show_hint("正在启动…", "info")
        # 暂为演示，后续换 core.launcher
        QTimer.singleShot(1500, lambda: self.show_hint("准备就绪", "info"))

    def _on_setting_changed(self, key: str, value):
        # 未来直连 core.config；此刻先透传一条提示
        self.show_hint(f"{key} → {value}", "info")

    def _on_setting_reset(self, category: str):
        self.show_hint(f"{category} 已归元", "info")

    def show_hint(self, text: str, level: str = "info", duration: int = 3000):
        self.hint_bar.show_message(text, level=level, duration=duration)

    def _load_qss(self):
        if QSS_PATH.exists():
            self.setStyleSheet(QSS_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())