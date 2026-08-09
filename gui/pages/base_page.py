"""BasePage：统一页面框架（Header + Content + Footer）。

所有页面继承——消除"每页自己堆布局、风格漂移"。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from qfluentwidgets import CardWidget, StrongBodyLabel


class BasePage(QWidget):
    """页面骨架：
        ┌─────────────────────────┐
        │ Header（标题 + 状态/操作）│
        ├─────────────────────────┤
        │ Content（占剩余全部）     │
        ├─────────────────────────┤
        │ Footer（可选，固定高度）  │
        └─────────────────────────┘
    """

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(10)

        # Header：标题 + 右侧状态槽
        self._header = QWidget()
        h = QHBoxLayout(self._header)
        h.setContentsMargins(4, 0, 4, 0)
        self.title_label = StrongBodyLabel(title)
        self.title_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        h.addWidget(self.title_label)
        h.addStretch(1)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #7A90B0;")
        h.addWidget(self.status_label)
        self._layout.addWidget(self._header, 0)

        # Content 容器（占剩余全部——无 stretch 空洞）
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(8)
        self._layout.addWidget(self.content, 1)

        # Footer（默认隐藏）
        self.footer = QWidget()
        self.footer.setVisible(False)
        self._layout.addWidget(self.footer, 0)

    # ---- 子类接口 ----

    def set_status(self, text, busy=False):
        self.status_label.setText(text)
        color = "#4FD1C5" if busy else "#7A90B0"
        self.status_label.setStyleSheet(f"color: {color};")

    def add_footer(self, widget):
        f = self.footer.layout()
        if f is None:
            from PySide6.QtWidgets import QHBoxLayout
            f = QHBoxLayout(self.footer)
            f.setContentsMargins(0, 0, 0, 0)
        f.addWidget(widget)
        self.footer.setVisible(True)

    def card(self):
        """通用卡片容器（Fluent 分层）。"""
        c = CardWidget()
        from gui.pages.placeholder import card_layout
        card_layout(c)
        return c
