# flint/ui/router.py
from PySide6.QtCore import QObject


class Router(QObject):
    """左右两栈，一索一对。"""

    def __init__(self, left_stack, right_stack, parent=None):
        super().__init__(parent)
        self.left_stack = left_stack
        self.right_stack = right_stack
        self._pairs = {}

    def register(self, index: int, left_widget, right_widget):
        self._pairs[index] = (left_widget, right_widget)
        self.left_stack.addWidget(left_widget)
        self.right_stack.addWidget(right_widget)

    def switch_tab(self, index: int) -> bool:
        pair = self._pairs.get(index)
        if pair is None:
            return False
        left, right = pair
        self.left_stack.setCurrentWidget(left)
        self.right_stack.setCurrentWidget(right)
        return True

    def get_current_pair(self):
        idx = self.left_stack.currentIndex()
        return self._pairs.get(idx)