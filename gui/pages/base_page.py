"""BasePage：统一页面框架（Header + Content + Footer）。

所有页面继承——消除"每页自己堆布局、风格漂移"。
同时提供通用卡片工具，避免 placeholder/command_deck 重复定义。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from qfluentwidgets import CardWidget, StrongBodyLabel


# ---- Fluent 设计 token（与 theme.py 对齐） ----

FONT_TITLE = 18      # 页面标题
FONT_MODULE = 14     # 卡片标题/模块标题
FONT_BODY = 13       # 正文
FONT_CAPTION = 12    # 辅助说明

COLOR_TEXT_MAIN = "#E6F1FF"
COLOR_TEXT_MUTED = "#7A90B0"
COLOR_ACCENT = "#4FD1C5"
COLOR_WARN = "#FFB454"
COLOR_DANGER = "#FF6B6B"

BG_CARD = "#16283F"
BORDER = "#24405F"


# ---- 通用卡片工具 ----

def card_layout(card):
    """给 CardWidget 初始化一个统一内边距的垂直布局。"""
    if card.layout() is None:
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
    return card.layout()


def card_title(card, text):
    """在卡片顶部插入一个模块级标题。"""
    label = StrongBodyLabel(text)
    label.setStyleSheet(
        f"font-size: {FONT_MODULE}px; font-weight: 700; letter-spacing: 1px;")
    card_layout(card).insertWidget(0, label)
    return label


# ---- 页面框架 ----

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
        self.title_label.setStyleSheet(
            f"font-size: {FONT_TITLE}px; font-weight: 700;")
        h.addWidget(self.title_label)
        h.addStretch(1)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: {FONT_CAPTION}px;")
        h.addWidget(self.status_label)
        self._layout.addWidget(self._header, 0)

        # Content 容器（占剩余全部——无 stretch 空洞）
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(10)
        self._layout.addWidget(self.content, 1)

        # Footer（默认隐藏）
        self.footer = QWidget()
        self.footer.setVisible(False)
        self._layout.addWidget(self.footer, 0)

    # ---- 子类接口 ----

    def set_status(self, text, busy=False):
        self.status_label.setText(text)
        color = COLOR_ACCENT if busy else COLOR_TEXT_MUTED
        self.status_label.setStyleSheet(
            f"color: {color}; font-size: {FONT_CAPTION}px;")

    def add_footer(self, widget):
        f = self.footer.layout()
        if f is None:
            f = QHBoxLayout(self.footer)
            f.setContentsMargins(0, 0, 0, 0)
            f.setSpacing(8)
        f.addWidget(widget)
        self.footer.setVisible(True)

    def card(self):
        """通用卡片容器（Fluent 分层）。"""
        c = CardWidget()
        card_layout(c)
        return c
