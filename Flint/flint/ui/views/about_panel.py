# flint/ui/views/about_panel.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

try:
    from ... import __version__, APP_NAME
except ImportError:
    __version__ = "0.1.0-alpha"
    APP_NAME = "Flint"

GITHUB_URL = "https://github.com/qingyangprince/Flint-Launcher"

class AboutPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AboutPanel")
        self.init_ui()

    def init_ui(self):
        l = QVBoxLayout(self)
        l.setContentsMargins(20, 20, 20, 20)
        l.setSpacing(12)
        l.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        logo = QLabel("🛠️")
        logo.setObjectName("AboutLogo")
        logo.setAlignment(Qt.AlignCenter)

        title = QLabel(f"{APP_NAME} Launcher")
        title.setObjectName("AboutTitle")
        title.setAlignment(Qt.AlignCenter)

        version = QLabel(f"版本 {__version__}")
        version.setObjectName("AboutMeta")
        version.setAlignment(Qt.AlignCenter)

        build = QLabel("构建：开发版 · 未签名")
        build.setObjectName("AboutMeta")
        build.setAlignment(Qt.AlignCenter)

        desc = QLabel("快速、原生的 Minecraft 启动器。\nPySide6 与 C++ 双核驱动。")
        desc.setObjectName("AboutDesc")
        desc.setAlignment(Qt.AlignCenter)

        license_label = QLabel("开源协议：GPLv3")
        license_label.setObjectName("AboutLicense")
        license_label.setAlignment(Qt.AlignCenter)

        credits = QLabel("致谢：PySide6 · httpx · tomlkit · miniz · sha2")
        credits.setObjectName("AboutMeta")
        credits.setAlignment(Qt.AlignCenter)

        link = QLabel(f'<a href="{GITHUB_URL}">项目主页</a>')
        link.setObjectName("AboutLink")
        link.setOpenExternalLinks(True)
        link.setAlignment(Qt.AlignCenter)

        for w in (logo, title, version, build, desc, license_label, credits, link):
            l.addWidget(w)
        l.addStretch(1)