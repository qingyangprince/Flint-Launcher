# flint/ui/widgets/memory_slider.py
"""内存分配滑块：数值联动、系统内存上限与推荐值标记。"""

from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QWidget

MIN_MEMORY_MB = 512
MAX_MEMORY_MB = 65536
STEP_MB = 256


def system_memory_mb() -> int:
    """返回物理内存大小（MB）；无法探测时回退 8 GB。"""
    try:
        if os.name == "nt":
            return _windows_memory_mb()
        if sys.platform == "darwin":
            output = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5
            ).stdout.strip()
            return max(int(output) // (1024 * 1024), 1024)
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return 8192


def _windows_memory_mb() -> int:
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("memory_load", ctypes.c_ulong),
            ("total_phys", ctypes.c_ulonglong),
            ("avail_phys", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("avail_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("avail_virtual", ctypes.c_ulonglong),
            ("avail_extended_virtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return 8192
    return max(int(status.total_phys // (1024 * 1024)), 1024)


def recommended_memory_mb(total_mb: int | None = None) -> int:
    total = total_mb if total_mb is not None else system_memory_mb()
    return _snap(min(max(total // 2, 2048), 8192))


def _snap(value: int) -> int:
    return max(MIN_MEMORY_MB, value // STEP_MB * STEP_MB)


class MemorySlider(QWidget):
    value_changed = Signal(int)  # MB，拖动过程中持续发出
    value_committed = Signal(int)  # MB，松开滑块后发出，适合落盘

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MemorySlider")
        self._total_mb = system_memory_mb()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setSingleStep(STEP_MB)
        self.slider.setPageStep(STEP_MB)
        self.slider.setRange(MIN_MEMORY_MB, self._max_for(self._total_mb))
        self.slider.setValue(2048)

        self.value_label = QLabel("2048 MB")
        self.value_label.setObjectName("MemoryValue")
        self.recommend_label = QLabel("")
        self.recommend_label.setObjectName("MemoryRecommend")

        layout.addWidget(self.slider, 1)
        layout.addWidget(self.value_label)
        layout.addWidget(self.recommend_label)

        self.slider.valueChanged.connect(self._on_change)
        self.slider.sliderReleased.connect(
            lambda: self.value_committed.emit(self.slider.value())
        )
        self.set_recommended(recommended_memory_mb(self._total_mb))

    @staticmethod
    def _max_for(total_mb: int) -> int:
        upper = min(max(total_mb - 1024, 2048), MAX_MEMORY_MB)
        return _snap(upper)

    def _on_change(self, value: int) -> None:
        snapped = _snap(value)
        if snapped != value:
            self.slider.setValue(snapped)
            return
        self.value_label.setText(f"{value} MB")
        self.value_changed.emit(value)

    def set_recommended(self, mb: int) -> None:
        self.recommend_label.setText(f"推荐 {mb} MB")

    def set_max(self, total_mb: int) -> None:
        self._total_mb = max(total_mb, 1024)
        self.slider.setMaximum(self._max_for(self._total_mb))
        self.set_recommended(recommended_memory_mb(self._total_mb))

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, mb: int) -> None:
        self.slider.setValue(_snap(min(max(mb, MIN_MEMORY_MB), self.slider.maximum())))

