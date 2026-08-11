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

# 全局活动录制器（GUI 关闭时收尾——closeEvent 停录制防钩子残留）
_active_recorder = None


class TrajectoryRecorder:
    def __init__(self, game_hwnd=None, game_sensitivity=4):
        self.game_hwnd = game_hwnd
        # 游戏内灵敏度（1-5，星穹铁道设置项）——录制时记入 JSON，回放换算/提示用
        self.game_sensitivity = game_sensitivity
        self.events = []
        self._last_time = None
        self._key_down = {}
        self._mouse_down = None  # 鼠标按下状态（长按 duration 用）
        self._mouse_pos = None   # 鼠标上次位置（视角位移差分）
        self._view_acc = [0.0, 0.0]  # 视角小位移累积
        self._recording = False
        self._keyboard_listener = None
        self._mouse_listener = None
        self._started_at = None
        self._client_size = None  # 录制时游戏客户区 (w, h)——分辨率归一化基准
        self._event_hook = None  # 实时回调（HUD 显示用）——pynput 线程调用，须线程安全
        # 键盘诊断（0.6.0 排查：键盘 0 事件——区分钩子死 vs 白名单过滤）
        self._diag_keys = []      # 钩子收到的全部按键（含白名单外）
        self._diag_filtered = []  # 被白名单过滤的按键
        self._diag_releases = []  # 收到的 release（无对应 press）

    def _diag_reset(self):
        self._diag_keys = []
        self._diag_filtered = []
        self._diag_releases = []

    def _diag_report(self):
        """诊断摘要（HUD 显示）：钩子收到的按键 vs 白名单过滤 vs release 孤儿。"""
        if not self._diag_keys and not self._diag_releases:
            return "键盘钩子未收到任何按键！"
        parts = []
        if self._diag_keys:
            from collections import Counter
            c = Counter(self._diag_keys)
            parts.append("收到: " + ", ".join(f"{k}×{n}" for k, n in c.most_common(8)))
        if self._diag_filtered:
            parts.append(f"白名单外: {sorted(set(self._diag_filtered))}")
        if self._diag_releases:
            parts.append(f"孤儿 release(无 press): {len(self._diag_releases)}")
        return "键盘: " + "；".join(parts)

    def set_event_hook(self, cb):
        """注册实时事件回调：每个事件记录后调用 cb(event_dict)。

        HUD 实时显示用——回调在 pynput 监听线程，实现必须线程安全
        （GameHudController.append_external 是线程安全入队）。
        """
        self._event_hook = cb

    def _emit_hook(self, event):
        if self._event_hook is not None:
            try:
                self._event_hook(event)
            except Exception:
                pass

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
        self._diag_reset()
        self._mouse_pos = None
        self._mouse_down = None  # 0.6.0 第5轮：跨会话残留——上次按住时
        # 停止，下次录制首次 release 会配对旧状态产生幽灵点击
        self._view_acc = [0.0, 0.0]  # 视角小位移累积（连续慢移不丢）
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
        global _active_recorder
        _active_recorder = self
        return True

    def _on_press(self, key):
        if not self._recording:
            return
        t = time.time()
        if t < self._started_at:
            return
        k = self._key_name(key)
        # 诊断：所有收到的按键都记录（区分钩子死 vs 白名单过滤）
        self._diag_keys.append(k)
        if k not in KEY_WHITELIST:
            self._diag_filtered.append(k)
            self._emit_hook({"type": "diag", "text": self._diag_report()})
            return
        if k in self._key_down:
            return
        self._key_down[k] = t
        self._emit_hook({"type": "diag", "text": self._diag_report()})

    def _on_release(self, key):
        if not self._recording:
            return
        t = time.time()
        if t < self._started_at:
            return
        k = self._key_name(key)
        # 诊断：release 无对应 press（钩子 press 丢失的证据）
        if k not in self._key_down:
            self._diag_releases.append(k)
            self._emit_hook({"type": "diag", "text": self._diag_report()})
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
        self._emit_hook({"type": "key", "key": k, "duration": duration})

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
        # 视角移动：小位移不丢弃——累积到阈值再记录（连续慢移鼠标
        # 每帧位移 <3px，原实现直接 return → 连续转视角完全录不到）
        self._view_acc[0] += dx
        self._view_acc[1] += dy
        if abs(self._view_acc[0]) < 3 and abs(self._view_acc[1]) < 3:
            return
        adx, ady = self._view_acc
        self._view_acc = [0.0, 0.0]
        # 归一化位移（相对客户区宽高）——分辨率/全屏变化时回放按当前尺寸换算
        w, h = self._client_size or (1, 1)
        self.events.append({
            "view_dx": round(adx / w, 4), "view_dy": round(ady / h, 4),
            "time_sleep": round(t - self._last_time, 2),
        })
        self._last_time = t
        self._emit_hook({"type": "view",
                         "dx": round(adx / w, 4), "dy": round(ady / h, 4)})

    def _on_click(self, x, y, button, pressed):
        if not self._recording:
            return
        t = time.time()
        if t < self._started_at:
            return
        if str(button) != "Button.left":
            return
        if pressed:
            # 按下：记录位置与时间（release 时算 duration——支持长按）
            self._mouse_down = {"t": t, "x": x, "y": y}
            return
        # 释放：生成点击事件（带按住时长 duration——长按可回放）
        down = self._mouse_down
        self._mouse_down = None
        if down is None:
            return
        duration = round(t - down["t"], 2)
        if duration < 0.05:
            duration = 0.05
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
            "nx": round((down["x"] - ox) / w, 4),
            "ny": round((down["y"] - oy) / h, 4),
            "duration": duration,  # 按住时长（长按可回放）
            "time_sleep": round(down["t"] - self._last_time, 2),
        })
        self._last_time = down["t"]
        self._emit_hook({"type": "click",
                         "nx": round((down["x"] - ox) / w, 4),
                         "ny": round((down["y"] - oy) / h, 4),
                         "duration": duration})

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
        try:
            # 第 8 轮：listener.stop 异常吞掉（录制停止不能被钩子故障打断）
            try:
                if self._keyboard_listener:
                    self._keyboard_listener.stop()
            except Exception:
                pass
            try:
                if self._mouse_listener:
                    self._mouse_listener.stop()
            except Exception:
                pass
            # 0.6.0 完善：等钩子线程退出（stop 异步——不 join 则事件可能
            # 在返回后被追加，回放读到的列表不完整）
            for _l in (self._keyboard_listener, self._mouse_listener):
                try:
                    if _l is not None and _l.is_alive():
                        _l.join(timeout=1.0)
                except Exception:
                    pass
        finally:
            # 第 8 轮：listener.stop 抛异常也保证注销（防僵尸引用）
            self._keyboard_listener = None
            self._mouse_listener = None
            global _active_recorder
            if _active_recorder is self:
                _active_recorder = None
        # 诊断摘要落日志（0.6.0 排查：键盘 0 事件——钩子死 vs 白名单）
        try:
            import logging
            logging.getLogger("runtime.input.recorder").warning(
                "录制键盘诊断: %s", self._diag_report())
        except Exception:
            pass
        return self.events

    def save(self, name=None):
        """保存轨迹 JSON 到 knowledge/trajectories/。返回路径。

        默认命名：自定义-1、自定义-2…（按现有最大序号递增，可读可排序）。
        """
        if not self.events:
            return None
        TRAJ_DIR.mkdir(parents=True, exist_ok=True)
        if name is None:
            # 默认命名规则：自定义-N（现有最大序号 + 1）
            max_n = 0
            for f in TRAJ_DIR.glob("自定义-*.json"):
                try:
                    n = int(f.stem.split("-")[1])
                    max_n = max(max_n, n)
                except Exception:
                    pass
            name = f"自定义-{max_n + 1}"
        path = TRAJ_DIR / f"{name}.json"
        payload = {
            "version": 1,
            "recorded_at": time.time(),
            "client_w": (self._client_size or (1920, 1080))[0],
            "client_h": (self._client_size or (1920, 1080))[1],
            # 游戏内灵敏度（1-5，星穹铁道设置项）——回放按比例换算视角位移
            "game_sensitivity": self.game_sensitivity,
            "events": self.events,
            "count": len(self.events),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        return path
