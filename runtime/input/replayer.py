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
    def __init__(self, game_hwnd=None, backend=None, speed=1.0,
                 sensitivity=None):
        self.game_hwnd = game_hwnd
        self.backend = backend or Win32Backend()
        self.speed = speed
        # 回放时游戏内灵敏度（None=与录制相同）。多用户环境：录制者灵敏度
        # 与他人不同时，按 录制/回放 比例换算视角像素位移（视角角度一致）
        self.sensitivity = sensitivity
        self.events = []
        self.meta = {}
        self._abort = None  # 当前回放的中止回调（长按分段检查用）
        self._view_remain = [0.0, 0.0]  # 视角小数像素累积（慢速不归零）

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
        self._abort = abort_check
        self._view_remain = [0.0, 0.0]  # 重置视角余量（多次回放不残留）
        ox, oy, cw, ch = self._client_geometry()
        # 分辨率差异提示（录制时尺寸存 meta.client_w/h）
        rw = self.meta.get("client_w")
        rh = self.meta.get("client_h")
        if rw and rh and (rw != cw or rh != ch):
            import logging
            logging.getLogger("runtime.input.replayer").warning(
                "回放分辨率与录制时不同（录制 %sx%s / 当前 %sx%s）——"
                "轨迹按比例缩放，点击/视角为近似值", rw, rh, cw, ch)
        # 游戏内灵敏度换算：视角角度 = 像素位移 × 灵敏度。
        # 录制灵敏度≠回放灵敏度时按比例缩放视角像素位移，保证视角角度一致。
        gs = self.meta.get("game_sensitivity")
        sens_factor = 1.0
        if gs and self.sensitivity and float(gs) != float(self.sensitivity):
            sens_factor = float(gs) / float(self.sensitivity)
            import logging
            logging.getLogger("runtime.input.replayer").info(
                "游戏内灵敏度换算：录制 %s → 回放 %s（视角位移 ×%.3f）",
                gs, self.sensitivity, sens_factor)
        # 视角累积合并（0.6.0 采样率修复）：连续微小移动（录制 3px 粒度）
        # 合并成 ≥8px 步长再发送——单次小位移可能低于游戏输入死区被吞，
        # 分开发送导致"回放视角没动静"。点击/按键/间隔 ≥0.1s 前 flush。
        _v_acc = [0.0, 0.0]
        for i, ev in enumerate(self.events):
            if abort_check and abort_check():
                return False
            if progress:
                progress(i, len(self.events))
            # 分段等待（0.6.0 F10 急停审查）：time_sleep 可能数秒~数十秒，
            # 整段 sleep 期间 abort 无法生效——分 0.1s 段检查中止；
            # 长等待同时发心跳（S3：单事件长 sleep 期间 watchdog 无事件）
            _wait = max(0.0, ev.get("time_sleep", 0)) / self.speed
            _deadline = time.time() + _wait
            _last_beat = 0.0
            while time.time() < _deadline:
                if abort_check is not None and abort_check():
                    return False
                if progress is not None and time.time() - _last_beat > 1.0:
                    progress(i, len(self.events))
                    _last_beat = time.time()
                time.sleep(min(0.1, _deadline - time.time()))
            if "key" in ev:
                if _v_acc[0] or _v_acc[1]:
                    self._replay_view(_v_acc[0], _v_acc[1])
                    _v_acc = [0.0, 0.0]
                self._replay_key(ev["key"], ev.get("duration", 0.1))
            elif "click" in ev:
                if _v_acc[0] or _v_acc[1]:
                    self._replay_view(_v_acc[0], _v_acc[1])
                    _v_acc = [0.0, 0.0]
                nx = max(0.0, min(1.0, ev.get("nx", 0)))
                ny = max(0.0, min(1.0, ev.get("ny", 0)))
                # 长按回放：duration>0.05 时按住再释放（录制支持长按后）
                duration = ev.get("duration") or 0
                if duration > 0.05:
                    self._replay_click_hold(ox + int(nx * cw),
                                            oy + int(ny * ch), duration)
                else:
                    self._replay_click(ox + int(nx * cw), oy + int(ny * ch))
            elif "view_dx" in ev:
                # 游戏内灵敏度换算（sens_factor=录制/回放——视角角度一致）
                _v_acc[0] += ev["view_dx"] * cw * sens_factor
                _v_acc[1] += ev["view_dy"] * ch * sens_factor
                # 达到显著步长（≥8px）或独立动作（间隔 ≥0.1s）时发送
                if abs(_v_acc[0]) >= 8 or abs(_v_acc[1]) >= 8 \
                        or ev.get("time_sleep", 0) >= 0.3:
                    self._replay_view(_v_acc[0], _v_acc[1])
                    _v_acc = [0.0, 0.0]
        # 末尾 flush 残留累积
        if _v_acc[0] or _v_acc[1]:
            self._replay_view(_v_acc[0], _v_acc[1])
        return True

    def _replay_key(self, key, duration):
        """按住 duration 秒再释放（keyDown → sleep → keyUp）。"""
        import logging
        _log = logging.getLogger("runtime.input.replayer")
        try:
            r = self.backend.press_key(key, wait_time=duration)
            # UIPI 拦截等失败以 InputResult(success=False) 返回——不是异常
            if r is not None and not getattr(r, "success", True):
                _log.warning("回放按键失败 %s: %s", key, getattr(r, "error", "?"))
        except Exception as e:
            _log.warning("回放按键异常 %s: %s", key, e)

    def _replay_click(self, x, y):
        import logging
        _log = logging.getLogger("runtime.input.replayer")
        try:
            r = self.backend.click(int(x), int(y))
            if r is not None and not getattr(r, "success", True):
                _log.warning("回放点击失败 (%s,%s): %s",
                             x, y, getattr(r, "error", "?"))
        except Exception as e:
            _log.warning("回放点击异常 (%s,%s): %s", x, y, e)

    def _replay_click_hold(self, x, y, duration):
        """长按回放：按住 duration 秒再释放（分段检查中止）。"""
        import logging
        _log = logging.getLogger("runtime.input.replayer")
        try:
            if hasattr(self.backend, "click_hold"):
                # 分段按住：0.1s 一段检查 abort（F10 急停长按也能断）
                if hasattr(self.backend, "click_down"):
                    self.backend.click_down(int(x), int(y))
                    _deadline = time.time() + max(0.0, float(duration))
                    while time.time() < _deadline:
                        if self._abort is not None and self._abort():
                            break
                        time.sleep(min(0.1, _deadline - time.time()))
                    r = self.backend.click_up()
                    if r is not None and not getattr(r, "success", True):
                        _log.warning("回放长按释放失败 (%s,%s): %s",
                                     x, y, getattr(r, "error", "?"))
                else:
                    r = self.backend.click_hold(int(x), int(y), duration)
                    if r is not None and not getattr(r, "success", True):
                        _log.warning("回放长按失败 (%s,%s): %s",
                                     x, y, getattr(r, "error", "?"))
            else:
                r = self.backend.click(int(x), int(y))
                if r is not None and not getattr(r, "success", True):
                    _log.warning("回放长按点击失败 (%s,%s): %s",
                                 x, y, getattr(r, "error", "?"))
                _deadline = time.time() + max(0.0, float(duration))
                while time.time() < _deadline:
                    if self._abort is not None and self._abort():
                        break
                    time.sleep(min(0.1, _deadline - time.time()))
        except Exception as e:
            _log.warning("回放长按异常 (%s,%s): %s", x, y, e)

    def _replay_view(self, dx, dy):
        """视角相对位移 → 真相对移动事件（0.6.0 修复：Fhoe-Rail 同款）。

        实锤链路：pynput Controller.move = 读当前位置+位移 → SetCursorPos
        （假相对，绝对跳变）→ 指针锁定游戏不认 → 视角不动；我们此前
        GetCursorPos+SetCursorPos 同样无效。游戏指针锁定模式只认
        mouse_event(MOUSEEVENTF_MOVE) 增量事件——Fhoe-Rail 锄大地转视角
        即此实现（mouse_event.py:237-262）。

        小数像素累积：int() 截断会让慢速视角（单帧 <1px）归零。
        """
        import logging
        _log = logging.getLogger("runtime.input.replayer")
        try:
            self._view_remain[0] += dx
            self._view_remain[1] += dy
            ix = int(self._view_remain[0])
            iy = int(self._view_remain[1])
            self._view_remain[0] -= ix
            self._view_remain[1] -= iy
            if not ix and not iy:
                return
            # 真相对移动事件（MOUSEEVENTF_MOVE=0x0001，无 ABSOLUTE）
            import ctypes
            ctypes.windll.user32.mouse_event(0x0001, ix, iy, 0, 0)
        except Exception as e:
            _log.warning("回放视角移动失败: %s", e)
