# runtime/input/win32_backend.py

```python
import ctypes
import time
from ctypes import wintypes

from runtime.input.base import InputBackend, InputResult


class Win32Backend(InputBackend):
    """原生 win32 输入后端（SendInput/SetCursorPos）。UIPI 拦截时 success=False, error=uipi_block。"""

    name = "win32"

    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.user32.SetProcessDPIAware()

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
            _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                        ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_ulong)]

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

    def move(self, x, y):
        if not self.user32.SetCursorPos(int(x), int(y)):
            return InputResult(success=False, action="move", backend=self.name,
                               error="SetCursorPos 失败")
        return InputResult(success=True, action="move", backend=self.name)

    def press_key(self, key, wait_time=0.2):
        VK = {"esc": 0x1B, "w": 0x57, "a": 0x41, "s": 0x53, "d": 0x44,
              "m": 0x4D, "space": 0x20, "enter": 0x0D, "tab": 0x09}
        vk = VK.get(str(key).lower(), ord(str(key).upper()[0]))
        KEYEVENTF_KEYUP = 0x0002
        self.user32.keybd_event(vk, 0, 0, 0)
        time.sleep(wait_time)
        self.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        return InputResult(success=True, action="press_key", backend=self.name)

    def release_key(self, key):
        """#42：仅发送 keyup，不按 wait_time 等待。"""
        VK = {"esc": 0x1B, "w": 0x57, "a": 0x41, "s": 0x53, "d": 0x44,
              "m": 0x4D, "space": 0x20, "enter": 0x0D, "tab": 0x09}
        vk = VK.get(str(key).lower(), ord(str(key).upper()[0]))
        self.user32.keybd_event(vk, 0, 0x0002, 0)
        return InputResult(success=True, action="release_key", backend=self.name)

```
