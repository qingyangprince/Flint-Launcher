# flint/ui/widgets/memory_slider.py
from PySide6.QtWidgets import QWidget, QHBoxLayout, QSlider, QLabel
from PySide6.QtCore import Qt, Signal

class MemorySlider(QWidget):
    value_changed = Signal(int)  # MB

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MemorySlider")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(512, 16384)
        self.slider.setSingleStep(256)
        self.slider.setPageStep(256)
        self.slider.setValue(2048)

        self.label = QLabel("2048 MB")
        self.label.setObjectName("MemoryValue")

        layout.addWidget(self.slider, 1)
        layout.addWidget(self.label)

        self.slider.valueChanged.connect(self._on_change)

    def _on_change(self, value: int):
        value = value // 256 * 256 or 512
        if value != self.slider.value():
            self.slider.setValue(value)
            return
        self.label.setText(f"{value} MB")
        self.value_changed.emit(value)

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, mb: int):
        self.slider.setValue(mb)
    