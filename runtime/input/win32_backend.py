import ctypes
import time

from runtime.input.base import InputBackend, InputResult


class Win32Backend(InputBackend):
    """原生 win32 输入后端（SendInput/SetCursorPos）。UIPI 拦截时 success=False, error=uipi_block。"""

    name = "win32"

    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.user32.SetProcessDPIAware()
        # Bug 386：输入状态快照——当前按住的键（异常/停止时可全量释放）
        self.pressed_keys = set()

    def release_all(self):
        """Bug 415：释放全部按住键（紧急停止/异常退出兜底）。"""
        import ctypes
        KEYEVENTF_KEYUP = 0x0002
        for key in list(self.pressed_keys):
            try:
                self.user32.keybd_event(key, 0, KEYEVENTF_KEYUP, 0)
            except Exception:
                pass
        self.pressed_keys.clear()

    @staticmethod
    def _send_input(inputs):
        ret = ctypes.windll.user32.SendInput(
            len(inputs), ctypes.byref(inputs), ctypes.sizeof(inputs[0]))
        if ret != len(inputs):
            return False
        return True

    def click(self, x, y):
        r = self.move(x, y)
        if not r.success:
            return r
        time.sleep(0.05)
        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004

        class MOUSEINPUT(ctypes.Structure):
            # dwExtraInfo 必须 ULONG_PTR（64 位下 c_size_t）——c_ulong 会致
            # 结构大小错误，SendInput 拒绝（管理员下 move 成功 click 失败的根因）
            _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                        ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                        ("dwExtraInfo", ctypes.c_size_t)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("mi", MOUSEINPUT)]

        inputs = (INPUT * 2)()
        inputs[0].type = 0
        inputs[0].mi.dwFlags = MOUSEEVENTF_LEFTDOWN
        inputs[1].type = 0
        inputs[1].mi.dwFlags = MOUSEEVENTF_LEFTUP
        if not self._send_input(inputs):
            return InputResult(success=False, action="click", backend=self.name,
                               error="uipi_block: SendInput 被拒绝（需要管理员权限）")
        return InputResult(success=True, action="click", backend=self.name)

    def click_hold(self, x, y, duration):
        """长按点击：移动到 (x,y) → 按住 duration 秒 → 释放（长按回放用）。"""
        r = self.move(x, y)
        if not r.success:
            return r
        time.sleep(0.05)
        if not self.click_down(x, y).success:
            return InputResult(success=False, action="click_hold",
                               backend=self.name,
                               error="uipi_block: SendInput 被拒绝（需要管理员权限）")
        time.sleep(max(0.0, float(duration or 0)))
        up = self.click_up()
        if not up.success:
            return InputResult(success=False, action="click_hold",
                               backend=self.name, error=up.error)
        return InputResult(success=True, action="click_hold", backend=self.name)

    def click_down(self, x, y):
        """移动到 (x,y) 并按住左键（长按回放分段用——可中断）。"""
        r = self.move(x, y)
        if not r.success:
            return r
        time.sleep(0.05)
        MOUSEEVENTF_LEFTDOWN = 0x0002

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                        ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                        ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("mi", MOUSEINPUT)]

        # 修复（0.6.0 第2轮审查）：不能用 (INPUT*1)(inp)——Structure 实例
        # 被当 sequence（len=2）→ TypeError。仿 click() 用 (INPUT*1)() 逐字段
        inputs = (INPUT * 1)()
        inputs[0].type = 0
        inputs[0].mi.dwFlags = MOUSEEVENTF_LEFTDOWN
        if not self._send_input(inputs):
            return InputResult(success=False, action="click_down",
                               backend=self.name,
                               error="uipi_block: SendInput 被拒绝（需要管理员权限）")
        return InputResult(success=True, action="click_down", backend=self.name)

    def click_up(self):
        """释放左键（长按回放分段用）。"""
        MOUSEEVENTF_LEFTUP = 0x0004

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                        ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                        ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("mi", MOUSEINPUT)]

        inputs = (INPUT * 1)()
        inputs[0].type = 0
        inputs[0].mi.dwFlags = MOUSEEVENTF_LEFTUP
        if not self._send_input(inputs):
            return InputResult(success=False, action="click_up",
                               backend=self.name,
                               error="uipi_block: SendInput 被拒绝（需要管理员权限）")
        return InputResult(success=True, action="click_up", backend=self.name)

    def move(self, x, y):
        if not self.user32.SetCursorPos(int(x), int(y)):
            return InputResult(success=False, action="move", backend=self.name,
                               error="SetCursorPos 失败")
        return InputResult(success=True, action="move", backend=self.name)

    def press_key(self, key, wait_time=0.2):
        vk = self._vk(key)
        if vk is None:
            return InputResult(success=False, action="press_key", backend=self.name,
                               error=f"unknown_key:{key}")
        KEYEVENTF_KEYUP = 0x0002
        self.user32.keybd_event(vk, 0, 0, 0)
        self.pressed_keys.add(vk)  # Bug 386：按下状态登记
        try:
            time.sleep(wait_time)
        finally:
            self.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            self.pressed_keys.discard(vk)  # Bug 385：异常也释放
        return InputResult(success=True, action="press_key", backend=self.name)

    def release_key(self, key):
        """#42：仅发送 keyup，不按 wait_time 等待。"""
        vk = self._vk(key)
        if vk is None:
            return InputResult(success=False, action="release_key", backend=self.name,
                               error=f"unknown_key:{key}")
        self.user32.keybd_event(vk, 0, 0x0002, 0)
        self.pressed_keys.discard(vk)
        return InputResult(success=True, action="release_key", backend=self.name)

    @staticmethod
    def _vk(key):
        """审查 P1：多字符键名显式映射——原 ord(首字母) 导致 shift→S/ctrl→C
        （emergency_stop 释放 shift 实际按 S）。未知键返回 None（显式失败）。"""
        VK = {"esc": 0x1B, "w": 0x57, "a": 0x41, "s": 0x53, "d": 0x44,
              "m": 0x4D, "space": 0x20, "enter": 0x0D, "tab": 0x09,
              "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
              "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27}
        k = str(key).lower()
        if k in VK:
            return VK[k]
        if len(k) == 1 and k.isalnum():
            return ord(k.upper())
        return None
