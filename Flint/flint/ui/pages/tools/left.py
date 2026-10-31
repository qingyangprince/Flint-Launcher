# flint/ui/pages/tools/left.py
try:
    from ...widgets.category_panel import CategoryPanel
except ImportError:
    from widgets.category_panel import CategoryPanel

class ToolsLeftPanel(CategoryPanel):
    CATEGORIES = ("日志查看", "模组管理", "账户管理", "关于 Flint")

    def __init__(self, parent=None):
        super().__init__(self.CATEGORIES, "ToolsLeftPanel", parent)