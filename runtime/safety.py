"""Emergency Pause：人工安全刹车（v0.12.1，M1 阶段强制开启）。

任何"人接手了电脑"的信号 → 立即 human_intervention + pause，绝不继续执行。

权限边界（Errata）：本层只回答"还能不能安全继续"，
**不监控**：键盘输入 / 行为分析 / 用户意图识别（禁止演化为输入监控系统）。
触发源仅限：光标移动、前台窗口切换。
"""
import ctypes
import threading
import time
from ctypes import wintypes


class EmergencyMonitor(threading.Thread):
    def __init__(self, bus, execution_id, game_hwnd, poll_interval=0.5, cursor_radius=30):
        super().__init__(daemon=True)
        self.bus = bus
        self.execution_id = execution_id
        self.game_hwnd = game_hwnd
        self.poll_interval = poll_interval
        self.cursor_radius = cursor_radius
        self._stop = threading.Event()
        self._last_cursor = None
        self._paused = False
        self.user32 = ctypes.windll.user32

    def _get_cursor(self):
        pt = wintypes.POINT()
        self.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def _emit(self, event_type, **kw):
        if self.bus is None:
            return
        from runtime.events.schema import make_event
        self.bus.publish(make_event(event_type, self.execution_id, **kw))

    def run(self):
        self._last_cursor = self._get_cursor()
        while not self._stop.is_set():
            time.sleep(self.poll_interval)
            if self._paused:
                continue
            cx, cy = self._get_cursor()
            lx, ly = self._last_cursor
            if abs(cx - lx) > self.cursor_radius or abs(cy - ly) > self.cursor_radius:
                self._trigger("cursor_moved", f"光标移动 ({lx},{ly})→({cx},{cy})")
                continue
            fg = self.user32.GetForegroundWindow()
            if self.game_hwnd and fg != self.game_hwnd:
                self._trigger("window_switch", f"前台窗口已切换 (0x{fg:x} != 0x{self.game_hwnd:x})")

    def _trigger(self, reason, detail):
        self._paused = True
        self._emit("human_intervention", context={"reason": reason, "detail": detail})
        self._emit("pause_requested", context={"reason": "human_intervention",
                                               "detail": f"{reason}: {detail}"})

    def resume(self):
        self._paused = False
        self._last_cursor = self._get_cursor()

    def stop(self):
        self._stop.set()
