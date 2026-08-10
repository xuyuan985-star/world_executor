"""轨迹录制（借鉴 Fhoe-Rail record.py：按键按下/释放 + 时间戳 → JSON）。

录制内容：
- 键盘按键（WASD/交互键）：按下→释放，记录 {key, time_sleep, duration}
- 鼠标视角移动：增量事件 {mouse_dx, mouse_dy, time_sleep}
- 鼠标左键点击：{click, x, y（游戏窗口内相对坐标）, time_sleep}
停止（F10 或 stop()）→ 保存 JSON 到 knowledge/trajectories/。

回放（replayer.py）按同格式重放——轨迹 = 玩家一次手动操作的全记录。
"""
import json
import time
from pathlib import Path

# 录制按键白名单（锄大地/宝箱跑图常用键）
KEY_WHITELIST = {"w", "a", "s", "d", "e", "f", "r", "v", "x",
                 "space", "esc", "shift", "ctrl", "1", "2", "3", "4"}

TRAJ_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge" / "trajectories"


class TrajectoryRecorder:
    def __init__(self, game_hwnd=None):
        self.game_hwnd = game_hwnd
        self.events = []
        self._last_time = None
        self._key_down = {}
        self._recording = False
        self._keyboard_listener = None
        self._mouse_listener = None
        self._started_at = None
        self._client_size = None  # 录制时游戏客户区 (w, h)——分辨率归一化基准

    @property
    def recording(self):
        return self._recording

    def _client_rect(self):
        """游戏客户区（GetClientRect——不含边框，全屏=显示器客户区）。"""
        if not self.game_hwnd:
            return None
        import ctypes
        import ctypes.wintypes
        rect = ctypes.wintypes.RECT()
        if not ctypes.windll.user32.GetClientRect(self.game_hwnd,
                                                  ctypes.byref(rect)):
            return None
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return None
        return (w, h)

    def start(self):
        """开始录制（3 秒后正式计数——给玩家切窗口时间）。"""
        if self._recording:
            return False
        from pynput import keyboard, mouse
        self.events = []
        self._key_down = {}
        self._mouse_pos = None
        self._started_at = time.time() + 3.0
        self._last_time = self._started_at
        # 记录录制时的客户区尺寸——回放按当前尺寸归一化换算
        # （分辨率/全屏变化自适应——否则点击/视角全部偏移）
        self._client_size = self._client_rect()

        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release)
        self._mouse_listener = mouse.Listener(
            on_move=self._on_move, on_click=self._on_click)
        self._keyboard_listener.start()
        self._mouse_listener.start()
        self._recording = True
        return True

    def _now(self):
        """录制时间轴（开始后 3 秒起算）。"""
        return time.time()

    def _tick(self):
        t = self._now()
        if t < self._last_time:
            return
        self._last_time = t

    def _on_press(self, key):
        if not self._recording:
            return
        t = time.time()
        if t < self._started_at:
            return
        k = self._key_name(key)
        if k not in KEY_WHITELIST or k in self._key_down:
            return
        self._key_down[k] = t

    def _on_release(self, key):
        if not self._recording:
            return
        t = time.time()
        if t < self._started_at:
            return
        k = self._key_name(key)
        if k not in self._key_down:
            return
        down = self._key_down.pop(k)
        duration = round(t - down, 2)
        if duration < 0.05:
            duration = 0.05
        self.events.append({
            "key": k,
            "time_sleep": round(down - self._last_time, 2),
            "duration": duration,
        })
        self._last_time = down

    def _on_move(self, x, y):
        if not self._recording:
            return
        t = time.time()
        if t < self._started_at:
            return
        if self._mouse_pos is None:
            self._mouse_pos = (x, y)
            return
        dx = x - self._mouse_pos[0]
        dy = y - self._mouse_pos[1]
        self._mouse_pos = (x, y)
        # 视角移动：小位移忽略（抖动），聚合到显著位移
        if abs(dx) < 3 and abs(dy) < 3:
            return
        # 归一化位移（相对客户区宽高）——分辨率/全屏变化时回放按当前尺寸换算
        w, h = self._client_size or (1, 1)
        self.events.append({
            "view_dx": round(dx / w, 4), "view_dy": round(dy / h, 4),
            "time_sleep": round(t - self._last_time, 2),
        })
        self._last_time = t

    def _on_click(self, x, y, button, pressed):
        if not self._recording or not pressed:
            return
        t = time.time()
        if t < self._started_at:
            return
        if str(button) != "Button.left":
            return
        # 归一化点击（客户区 0-1）——回放按当前客户区换算，分辨率自适应
        w, h = self._client_size or (1, 1)
        ox, oy = 0, 0
        if self.game_hwnd:
            import ctypes
            import ctypes.wintypes
            import win32gui
            # 客户区原点（屏幕绝对坐标）——鼠标 x 是屏幕坐标，须先减原点
            ox, oy = win32gui.ClientToScreen(self.game_hwnd, (0, 0))
            rect = ctypes.wintypes.RECT()
            if ctypes.windll.user32.GetClientRect(self.game_hwnd,
                                                  ctypes.byref(rect)):
                cw = rect.right - rect.left
                ch = rect.bottom - rect.top
                if cw > 0 and ch > 0:
                    w, h = cw, ch
        self.events.append({
            "click": True,
            "nx": round((x - ox) / w, 4), "ny": round((y - oy) / h, 4),
            "time_sleep": round(t - self._last_time, 2),
        })
        self._last_time = t

    @staticmethod
    def _key_name(key):
        try:
            if hasattr(key, "char") and key.char:
                return key.char.lower()
            name = str(key).replace("Key.", "").lower()
            return name
        except Exception:
            return "?"

    def stop(self):
        """停止录制并返回事件列表。"""
        if not self._recording:
            return []
        self._recording = False
        if self._keyboard_listener:
            self._keyboard_listener.stop()
        if self._mouse_listener:
            self._mouse_listener.stop()
        self._keyboard_listener = None
        self._mouse_listener = None
        return self.events

    def save(self, name=None):
        """保存轨迹 JSON 到 knowledge/trajectories/。返回路径。"""
        if not self.events:
            return None
        TRAJ_DIR.mkdir(parents=True, exist_ok=True)
        name = name or f"traj_{int(time.time())}"
        path = TRAJ_DIR / f"{name}.json"
        payload = {
            "version": 1,
            "recorded_at": time.time(),
            "client_w": (self._client_size or (1920, 1080))[0],
            "client_h": (self._client_size or (1920, 1080))[1],
            "events": self.events,
            "count": len(self.events),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        return path
