"""轨迹回放（TrajectoryRecorder 的逆操作）：按轨迹 JSON 重放按键/视角/点击。

按键：按住 duration 秒再释放（Win32Backend.press_key 组合）
视角：鼠标相对移动（pynput Controller.move）
点击：绝对坐标点击（游戏窗口相对坐标 + 窗口位置）
"""
import json
import time
from pathlib import Path

from runtime.input.win32_backend import Win32Backend


class TrajectoryReplayer:
    def __init__(self, game_hwnd=None, backend=None, speed=1.0):
        self.game_hwnd = game_hwnd
        self.backend = backend or Win32Backend()
        self.speed = speed
        self._view_x = None
        self._view_y = None

    def load(self, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.events = data.get("events", [])
        return len(self.events)

    def replay(self, abort_check=None, progress=None):
        """按轨迹重放。abort_check 可中断；progress 回调 (i, total)。"""
        for i, ev in enumerate(self.events):
            if abort_check and abort_check():
                return False
            if progress:
                progress(i, len(self.events))
            time.sleep(max(0.0, ev.get("time_sleep", 0)) / self.speed)
            if "key" in ev:
                self._replay_key(ev["key"], ev.get("duration", 0.1))
            elif "click" in ev:
                self._replay_click(ev.get("x", 0), ev.get("y", 0))
            elif "mouse_dx" in ev:
                self._replay_view(ev["mouse_dx"], ev["mouse_dy"])
        return True

    def _replay_key(self, key, duration):
        """按住 duration 秒再释放（keyDown → sleep → keyUp）。"""
        try:
            self.backend.press_key(key, wait_time=duration)
        except Exception:
            pass

    def _replay_click(self, rx, ry):
        """游戏窗口相对坐标 → 绝对坐标点击。"""
        x, y = rx, ry
        if self.game_hwnd:
            import ctypes
            import ctypes.wintypes
            rect = ctypes.wintypes.RECT()
            if ctypes.windll.user32.GetWindowRect(self.game_hwnd,
                                                  ctypes.byref(rect)):
                x = rect.left + rx
                y = rect.top + ry
        try:
            self.backend.click(int(x), int(y))
        except Exception:
            pass

    def _replay_view(self, dx, dy):
        """鼠标视角相对移动（pynput Controller.move——不触发点击）。"""
        try:
            from pynput.mouse import Controller
            Controller().move(int(dx), int(dy))
        except Exception:
            pass
