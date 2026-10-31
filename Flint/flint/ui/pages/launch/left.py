# flint/ui/pages/launch/left.py
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListView, QPushButton,
    QMenu, QAbstractItemView,
)
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtCore import Qt, Signal

try:
    from ...widgets.version_item import VersionItemDelegate
except ImportError:
    from widgets.version_item import VersionItemDelegate


class LaunchLeftPanel(QWidget):
    version_selected = Signal(str)
    new_requested = Signal()
    context_action = Signal(str, str)  # (action, version)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LaunchLeftPanel")
        self.init_ui()
        self.bind()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.view = QListView()
        self.view.setObjectName("VersionList")
        
        # 修复：必须先挂载模型，才能挂载 Delegate
        self.view.setModel(QStandardItemModel(self))
        
        self.view.setItemDelegate(VersionItemDelegate(self.view))
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setUniformItemSizes(True)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        layout.addWidget(self.view, 1)

        self.new_btn = QPushButton("+ 新建")
        self.new_btn.setObjectName("NewInstanceButton")
        layout.addWidget(self.new_btn)

    def bind(self):
        self.view.selectionModel().currentChanged.connect(self._on_current)
        self.view.customContextMenuRequested.connect(self._popup_menu)
        self.new_btn.clicked.connect(self.new_requested.emit)

    def _on_current(self, current, _previous):
        if current.isValid():
            self.version_selected.emit(current.data(Qt.UserRole))

    def _popup_menu(self, pos):
        index = self.view.indexAt(pos)
        if not index.isValid():
            return

        name = index.data(Qt.UserRole)
        menu = QMenu(self)
        for label, key in (
            ("编辑", "edit"), ("复制", "clone"),
            ("删除", "delete"), ("打开文件夹", "open_folder"),
        ):
            act = menu.addAction(label)
            act.triggered.connect(
                lambda _=False, k=key, n=name: self.context_action.emit(k, n)
            )
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def set_versions(self, versions):
        """versions: [(name, loader), ...]"""
        model = self.model()
        model.clear()
        for name, loader in versions:
            item = QStandardItem(name)
            item.setData(name, Qt.UserRole)
            item.setData(loader, Qt.UserRole + 1)
            item.setEditable(False)
            model.appendRow(item)
            
        if model.rowCount():
            self.view.setCurrentIndex(model.index(0, 0))

    def current_version(self):
        idx = self.view.currentIndex()
        return idx.data(Qt.UserRole) if idx.isValid() else None

    def model(self):
        return self.view.model()