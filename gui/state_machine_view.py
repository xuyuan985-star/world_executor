from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QScrollArea, QWidget

from gui.theme import STATE_COLORS, TEXT_MUTED

MAIN_STATES = [
    "INIT",
    "CHECK_WORLD_STATE",
    "NAVIGATING",
    "PORTAL_TRANSITION",
    "INTERACTING",
    "VERIFYING",
    "RECOVERING",
    "DONE",
]

# 非状态机事件 → overlay 展示（v0.12.1 Emergency Pause 链路）
OVERLAY_EVENTS = {
    "combat",
    "dialogue",
    "portal_failed",
    "event_interrupt",
    "human_intervention",
    "pause_requested",
}


class _Canvas(QWidget):
    def __init__(self, view):
        super().__init__()
        self._view = view

    def paintEvent(self, event):
        # Bug 85：QPainter 异常保护——_render 抛错也保证 end()（防资源泄漏）
        # Bug 107：绘制异常捕获 + 日志（Qt 绘制异常不崩但不静默）
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            self._view._render(painter)
        except Exception:
            import logging
            logging.getLogger("gui.state_view").exception("paint failed")
        finally:
            painter.end()


class StateMachineView(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._canvas = _Canvas(self)
        self.setWidget(self._canvas)
        self.setWidgetResizable(True)
        self._current = None
        self._pulse = 0.0
        self._overlays = []
        self._transition_flash = None
        self._flash_alpha = 0.0
        # Bug 35：布局缓存显式初始化（首次绘制前不依赖 getattr 兜底）
        self._cached_nodes = []
        self._canvas.setFixedHeight(160)
        self._timer = self.startTimer(50)

    def on_state(self, prev, new, detail):
        # 11 态已在映射表全覆盖：EVENT_INTERRUPT/PORTAL_TRANSITION_FAILED/ABORT 走 overlay，
        # 其余均在 MAIN_STATES。
        mapped = new
        if new in ("EVENT_INTERRUPT", "PORTAL_TRANSITION_FAILED", "ABORT"):
            self._overlays.append((new, detail))
            self._overlays = self._overlays[-20:]  # Bug 36：overlay 限长
            mapped = "RECOVERING" if new != "ABORT" else "DONE"
            self._transition_flash = (prev, mapped)
            self._flash_alpha = 1.0
            self.viewport().update()
            self._canvas.update()
            return
        if new not in MAIN_STATES:
            # Bug 38：未知状态不伪装 NAVIGATING——暴露并降级 RECOVERING
            mapped = "RECOVERING"
            import logging
            logging.getLogger("gui.state_view").warning(
                "未知状态 %s（应加入 MAIN_STATES）", new)
            STATE_COLORS.setdefault(new, TEXT_MUTED)
        self._current = mapped
        self._transition_flash = (prev, mapped)
        self._flash_alpha = 1.0
        self.viewport().update()
        self._canvas.update()

    def add_overlay(self, name, detail):
        """非状态机事件（human_intervention / pause_requested）进入 overlay，避免被误读为 NAVIGATING。"""
        self._overlays.append((name, detail))
        self._overlays = self._overlays[-20:]  # Bug 36：overlay 限长
        self.viewport().update()
        self._canvas.update()

    def reset(self):
        self._current = None
        self._overlays.clear()
        self._transition_flash = None
        self._flash_alpha = 0.0
        self._canvas.update()

    def timerEvent(self, event):
        if self._current is not None:
            self._pulse += 0.08
        if self._flash_alpha > 0:
            self._flash_alpha = max(0.0, self._flash_alpha - 0.06)
        # Bug 39：无动画状态不 20FPS 空转重绘
        if self._current is not None or self._flash_alpha > 0:
            self._canvas.update()

    def resizeEvent(self, event):
        self._canvas.setFixedWidth(max(self.viewport().width(), len(MAIN_STATES) * 130))
        self._rebuild_layout()  # Bug 57：resize 重算布局（paint 不再每次算）
        super().resizeEvent(event)

    def _rebuild_layout(self):
        """Bug 57：节点布局缓存——paintEvent 只绘制，不在绘制内重算。"""
        w = self._canvas.width()
        n = len(MAIN_STATES)
        margin = 40
        span = (w - margin * 2) / (n - 1) if w > margin * 2 and n > 1 \
            else (w / max(n, 1))
        centers = []
        for i, name in enumerate(MAIN_STATES):
            cx = (margin + i * span) if w > margin * 2 else (i * span)
            centers.append((cx, 60, name))
        self._cached_nodes = centers

    def _render(self, painter):
        if not getattr(self, "_cached_nodes", None):
            self._rebuild_layout()
        centers = self._cached_nodes
        for cx, cy, name in centers:
            self._draw_node(painter, cx, cy, name)
        for i in range(len(centers) - 1):
            self._draw_edge(painter, centers[i], centers[i + 1])
        if self._current:
            # AI 审计 B3：_current 不在 MAIN_STATES 时用 next(default) 防 StopIteration
            node = next((c for c in centers if c[2] == self._current), None)
            if node:
                cx, cy, _ = node
                self._draw_pulse(painter, cx, cy)
        if self._overlays:
            self._draw_overlays(painter)

    def _draw_edge(self, painter, a, b):
        flash = False
        if self._transition_flash and self._transition_flash[1] == b[2]:
            flash = True
        color = QColor("#4FD1C5" if flash else "#24405F")
        if flash:
            color.setAlphaF(min(1.0, self._flash_alpha + 0.3))
        pen = QPen(color, 2 if flash else 1)
        painter.setPen(pen)
        painter.drawLine(a[0], a[1], b[0], b[1])

    def _draw_node(self, painter, cx, cy, name):
        rect_w, rect_h = 96, 36
        x, y = cx - rect_w / 2, cy - rect_h / 2
        color = QColor(STATE_COLORS.get(name, TEXT_MUTED))
        if self._current == name:
            color = QColor("#4FD1C5")
        painter.setBrush(QColor("#16283F"))
        painter.setPen(QPen(color, 2))
        painter.drawRoundedRect(x, y, rect_w, rect_h, 8, 8)
        painter.setPen(color)
        font = QFont("Microsoft YaHei UI", 8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(int(x), int(y), int(rect_w), int(rect_h),
                         Qt.AlignCenter, name.replace("CHECK_WORLD_STATE", "CHECK_CTX"))

    def _draw_pulse(self, painter, cx, cy):
        r = 26 + 10 * (0.5 + 0.5 * self._pulse % 1.0)
        color = QColor("#4FD1C5")
        color.setAlphaF(0.35)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(color, 2))
        painter.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

    def _draw_overlays(self, painter):
        y = 112
        for name, detail in self._overlays:
            painter.setBrush(QColor("#2A1A1A"))
            painter.setPen(QPen(QColor("#FF6B6B"), 1))
            painter.drawRoundedRect(40, y - 14, 760, 22, 6, 6)
            painter.setPen(QColor("#FF6B6B"))
            font = QFont("Microsoft YaHei UI", 8)
            painter.setFont(font)
            # Bug 37：detail 可能几千字符（VLM 错误）——截断防绘制溢出
            text = f"{name}: {str(detail)[:120]}"
            painter.drawText(48, y, 740, 20, Qt.AlignLeft, text)
            y += 26
