"""启动页左栏：实例列表、右键菜单与新建入口。"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMenu,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from flint.core.instance import Instance, InstanceError, InstanceManager, get_instance_manager
from flint.ui.overlay import Overlay
from flint.ui.widgets.version_item import VersionItemDelegate

logger = logging.getLogger(__name__)

ID_ROLE = Qt.ItemDataRole.UserRole
LOADER_ROLE = Qt.ItemDataRole.UserRole + 1


class LaunchLeftPanel(QWidget):
    """实例列表；增删改在面板内完成，选中项以 ``Instance`` 对象外抛。"""

    instance_selected = Signal(object)
    new_requested = Signal()
    instances_changed = Signal()
    error_occurred = Signal(str)
    info_message = Signal(str)

    def __init__(
        self,
        manager: InstanceManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("LaunchLeftPanel")
        self.manager = manager or get_instance_manager()
        self._instances: dict[str, Instance] = {}
        self._overlay: Overlay | None = None
        self.init_ui()
        self.bind()
        self.reload()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.view = QListView()
        self.view.setObjectName("VersionList")
        self.view.setModel(QStandardItemModel(self))
        self.view.setItemDelegate(VersionItemDelegate(self.view))
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setUniformItemSizes(True)
        self.view.setMouseTracking(True)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.view, 1)

        self.empty_label = QLabel("还没有实例\n点击下方“+ 新建”开始")
        self.empty_label.setObjectName("EmptyHint")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.hide()
        layout.addWidget(self.empty_label)

        self.new_btn = QPushButton("+ 新建")
        self.new_btn.setObjectName("NewInstanceButton")
        layout.addWidget(self.new_btn)

    def bind(self) -> None:
        self.view.selectionModel().currentChanged.connect(self._on_current)
        self.view.customContextMenuRequested.connect(self._popup_menu)
        self.view.doubleClicked.connect(lambda _index: self._edit_current())
        self.new_btn.clicked.connect(self.new_requested.emit)

    # -- 数据 ---------------------------------------------------------------
    def reload(self, select_key: str | None = None) -> None:
        """从管理器重新读取实例，尽量保持当前选中项。"""
        current = self.current_instance()
        target = select_key if select_key is not None else (current.id if current else "")
        self.set_instances(self.manager.list(), select_key=target)

    def set_instances(self, instances, *, select_key: str | None = None) -> None:
        self._instances = {item.id: item for item in instances}
        model = self.model()
        model.clear()
        for item in instances:
            row = QStandardItem(item.name)
            row.setData(item.id, ID_ROLE)
            row.setData(item.display_loader, LOADER_ROLE)
            row.setEditable(False)
            model.appendRow(row)

        empty = model.rowCount() == 0
        self.empty_label.setVisible(empty)
        self.view.setVisible(not empty)

        if empty:
            self.instance_selected.emit(None)
            return

        target = 0
        if select_key:
            for row in range(model.rowCount()):
                if model.item(row).data(ID_ROLE) == select_key:
                    target = row
                    break
        self.view.setCurrentIndex(model.index(target, 0))

    def current_instance(self) -> Instance | None:
        index = self.view.currentIndex()
        if not index.isValid():
            return None
        return self._instances.get(index.data(ID_ROLE))

    def model(self) -> QStandardItemModel:
        model = self.view.model()
        assert isinstance(model, QStandardItemModel)
        return model

    def select(self, key: str | None) -> None:
        """按 id 选中某一行。"""
        model = self.model()
        for row in range(model.rowCount()):
            if model.item(row).data(ID_ROLE) == key:
                self.view.setCurrentIndex(model.index(row, 0))
                return

    # -- 交互 ---------------------------------------------------------------
    def _on_current(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid():
            return
        instance = self._instances.get(current.data(ID_ROLE))
        if instance is not None:
            self.instance_selected.emit(instance)

    def _popup_menu(self, pos) -> None:
        index = self.view.indexAt(pos)
        if not index.isValid():
            return
        self.view.setCurrentIndex(index)
        menu = QMenu(self)
        menu.addAction("编辑", self._edit_current)
        menu.addAction("复制", self._clone_current)
        menu.addAction("打开文件夹", self._open_current_folder)
        menu.addSeparator()
        menu.addAction("删除", self._delete_current)
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def _overlay_for(self) -> Overlay:
        if self._overlay is None:
            self._overlay = Overlay(self.window())
        return self._overlay

    def _edit_current(self) -> None:
        instance = self.current_instance()
        if instance is None:
            return
        form, name_edit, memory_spin, java_edit = self._build_edit_form(instance)

        def apply() -> bool:
            try:
                updated = self.manager.update(
                    instance,
                    name=name_edit.text(),
                    memory_mb=memory_spin.value(),
                    java_path=java_edit.text().strip(),
                )
            except InstanceError as exc:
                self.error_occurred.emit(str(exc))
                return False
            self.reload(select_key=updated.id)
            self.instances_changed.emit()
            self.info_message.emit(f"已更新实例 {updated.name}")
            return True

        self._overlay_for().show_content(
            f"编辑实例 · {instance.name}",
            form,
            message="修改后立即保存到实例元数据。",
            ok_text="保存",
            on_accept=apply,
        )

    def _build_edit_form(self, instance: Instance):
        form = QWidget()
        layout = QFormLayout(form)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        name_edit = QLineEdit(instance.name)
        name_edit.setObjectName("PathInput")
        memory_spin = QSpinBox()
        memory_spin.setObjectName("PathInput")
        memory_spin.setRange(512, 65536)
        memory_spin.setSingleStep(256)
        memory_spin.setSuffix(" MB")
        memory_spin.setValue(instance.memory_mb)
        java_edit = QLineEdit(instance.java_path)
        java_edit.setObjectName("PathInput")
        java_edit.setPlaceholderText("留空则自动探测")

        layout.addRow("名称", name_edit)
        layout.addRow("内存", memory_spin)
        layout.addRow("Java", java_edit)
        return form, name_edit, memory_spin, java_edit

    def _clone_current(self) -> None:
        instance = self.current_instance()
        if instance is None:
            return
        try:
            cloned = self.manager.clone(instance)
        except InstanceError as exc:
            self.error_occurred.emit(str(exc))
            return
        self.reload(select_key=cloned.id)
        self.instances_changed.emit()
        self.info_message.emit(f"已复制为 {cloned.name}")

    def _delete_current(self) -> None:
        instance = self.current_instance()
        if instance is None:
            return

        def remove() -> bool:
            try:
                self.manager.delete(instance)
            except InstanceError as exc:
                self.error_occurred.emit(str(exc))
                return False
            self.reload()
            self.instances_changed.emit()
            self.info_message.emit(f"已删除实例 {instance.name}")
            return True

        self._overlay_for().ask(
            "删除实例",
            f"确定删除“{instance.name}”吗？该实例目录下的存档与模组会一并移除，且无法撤销。",
            ok_text="删除",
            danger=True,
            on_accept=remove,
        )

    def _open_current_folder(self) -> None:
        instance = self.current_instance()
        if instance is None:
            return
        directory = self.manager.directory_for(instance)
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.error_occurred.emit(f"无法创建实例目录：{exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(directory))))
