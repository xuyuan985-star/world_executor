"""GameHudOverlay：游戏窗口左下角日志 HUD（对齐 M7 行为）。

- 无边框置顶半透明层，跟随游戏窗口位置（左下角）
- 顶部固定提示"F10 = 紧急停止"
- 内容 = EventBus 事件流（滚动日志）
"""
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit,
                               QVBoxLayout, QWidget)


class GameHudOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # 对齐 M7 overlay：topmost + 点击穿透（不挡游戏操作）+ 不抢焦点
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint
                            | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFixedSize(420, 200)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 顶部提示条
        tip = QLabel("F10 = 紧急停止")
        tip.setStyleSheet(
            "background: rgba(230,69,69,200); color: white;"
            "font-size: 12px; font-weight: 700; padding: 3px 8px;"
            "border-top-left-radius: 6px; border-top-right-radius: 6px;")
        lay.addWidget(tip)

        # 日志区
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(200)
        self.log_view.setStyleSheet(
            "background: rgba(16,24,38,200); color: #B0C4DE;"
            "font-size: 11px; border: none;"
            "border-bottom-left-radius: 6px; border-bottom-right-radius: 6px;")
        lay.addWidget(self.log_view)

    def append(self, text):
        self.log_view.appendPlainText(text)

    def set_emergency(self):
        """紧急停止时置顶提示（红色横幅）。"""
        self.log_view.appendPlainText("⚠ 已紧急停止（F10）——全部按键已释放")
        self.show()


class GameHudController:
    """HUD 生命周期：跟随游戏窗口（位置/可见性），绑定事件流。"""

    def __init__(self, bus, game_hwnd, log_lines=100):
        self.bus = bus
        self.game_hwnd = game_hwnd
        self.log_lines = log_lines
        self.overlay = GameHudOverlay()
        self._lines = []
        self.bus.subscribe(self._on_event)

    def _on_event(self, event):
        line = f"[{event.type}] {event.detail or ''}".strip()
        if len(line) > 90:
            line = line[:90] + "…"
        self._lines.append(line)
        self._lines = self._lines[-self.log_lines:]
        if self.overlay.isVisible():
            self.overlay.append(line)

    def show(self):
        self.overlay.show()
        for line in self._lines[-20:]:
            self.overlay.log_view.appendPlainText(line)
        self.reposition()

    def reposition(self):
        """跟随游戏窗口左下角。"""
        import ctypes
        import ctypes.wintypes
        hwnd = self.game_hwnd
        if not ctypes.windll.user32.IsWindow(hwnd):
            return
        rect = ctypes.wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return
        w = self.overlay.width()
        h = self.overlay.height()
        # 左下角（窗口底部上方 8px）
        x = rect.left + 8
        y = rect.bottom - h - 8
        self.overlay.move(QPoint(x, y))

    def hide(self):
        self.overlay.hide()

    def destroy(self):
        self.bus.unsubscribe(self._on_event)
        self.overlay.deleteLater()
