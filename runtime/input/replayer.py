"""轨迹回放（TrajectoryRecorder 的逆操作）：按轨迹 JSON 重放按键/视角/点击。

坐标归一化（分辨率/全屏自适应）：
- 点击：轨迹存客户区归一化 (nx, ny) → 回放按当前客户区 + 客户区原点换算
- 视角：轨迹存归一化位移 (view_dx, view_dy) → 按当前客户区尺寸换算像素
录制/回放分辨率不一致时：log 提示（轨迹按比例缩放，近似可用）。
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
        self.events = []
        self.meta = {}

    def load(self, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.events = data.get("events", [])
        self.meta = {k: v for k, v in data.items() if k not in ("events",)}
        return len(self.events)

    def _client_geometry(self):
        """当前客户区 (原点x, 原点y, 宽, 高)——回放坐标换算基准。"""
        if not self.game_hwnd:
            return (0, 0, 1920, 1080)
        import ctypes
        import ctypes.wintypes
        import win32gui
        ox, oy = win32gui.ClientToScreen(self.game_hwnd, (0, 0))
        rect = ctypes.wintypes.RECT()
        if not ctypes.windll.user32.GetClientRect(self.game_hwnd,
                                                  ctypes.byref(rect)):
            return (ox, oy, 1920, 1080)
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w <= 0 or h <= 0:
            w, h = 1920, 1080
        return (ox, oy, w, h)

    def replay(self, abort_check=None, progress=None):
        """按轨迹重放。abort_check 可中断；progress 回调 (i, total)。"""
        ox, oy, cw, ch = self._client_geometry()
        # 分辨率差异提示（录制时尺寸存 meta.client_w/h）
        rw = self.meta.get("client_w")
        rh = self.meta.get("client_h")
        if rw and rh and (rw != cw or rh != ch):
            import logging
            logging.getLogger("runtime.input.replayer").warning(
                "回放分辨率与录制时不同（录制 %sx%s / 当前 %sx%s）——"
                "轨迹按比例缩放，点击/视角为近似值", rw, rh, cw, ch)
        for i, ev in enumerate(self.events):
            if abort_check and abort_check():
                return False
            if progress:
                progress(i, len(self.events))
            time.sleep(max(0.0, ev.get("time_sleep", 0)) / self.speed)
            if "key" in ev:
                self._replay_key(ev["key"], ev.get("duration", 0.1))
            elif "click" in ev:
                nx = max(0.0, min(1.0, ev.get("nx", 0)))
                ny = max(0.0, min(1.0, ev.get("ny", 0)))
                self._replay_click(ox + int(nx * cw), oy + int(ny * ch))
            elif "view_dx" in ev:
                self._replay_view(ev["view_dx"] * cw, ev["view_dy"] * ch)
        return True

    def _replay_key(self, key, duration):
        """按住 duration 秒再释放（keyDown → sleep → keyUp）。"""
        try:
            self.backend.press_key(key, wait_time=duration)
        except Exception:
            pass

    def _replay_click(self, x, y):
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
