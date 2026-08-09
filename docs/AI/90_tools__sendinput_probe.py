# tools/sendinput_probe.py

```python
"""SendInput 探针（Sprint A-4）：不碰游戏，只验证 Windows 输入注入可用。

解决"pyautogui 不动"的归因问题：
  A. Windows 禁止（UIPI/权限）→ 探针 FAIL
  B. 游戏禁止（游戏内部处理/锁定）→ 探针 PASS 但点击游戏无响应

两个探针：
  1. SetCursorPos 移动（用户态，无 UIPI 拦截面）——快速 sanity
  2. SendInput 注入鼠标移动 1px（受 UIPI 管控）——真注入探针

注意：探针会真实移动鼠标 1px（恢复原位置），无其他副作用。
"""
import ctypes
import ctypes.wintypes
import sys
import time


def probe_setcursor():
    """SetCursorPos 探针：移动 1px 后回读。"""
    user32 = ctypes.windll.user32
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    before = (pt.x, pt.y)
    user32.SetCursorPos(before[0] + 1, before[1] + 1)
    time.sleep(0.2)
    user32.GetCursorPos(ctypes.byref(pt))
    after = (pt.x, pt.y)
    user32.SetCursorPos(before[0], before[1])  # 还原
    return before != after


def probe_sendinput():
    """SendInput 探针：注入相对鼠标移动 1px，读回光标是否变化。"""
    user32 = ctypes.windll.user32

    class INPUT(ctypes.Structure):
        class _MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                        ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                        ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

        _fields_ = [("type", ctypes.c_ulong), ("data", _MOUSEINPUT)]

    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    before = (pt.x, pt.y)
    inp = INPUT()
    inp.type = 0  # INPUT_MOUSE
    inp.data.dx = 1
    inp.data.dy = 0
    inp.data.dwFlags = 0x0001  # MOUSEEVENTF_MOVE
    sent = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
    time.sleep(0.2)
    user32.GetCursorPos(ctypes.byref(pt))
    after = (pt.x, pt.y)
    if after != before:
        user32.SetCursorPos(before[0], before[1])  # 还原
    return sent == 1 and after != before


def main():
    if sys.platform != "win32":
        print("[probe] FAIL (Windows only)")
        return 1
    print("[probe] SetCursorPos 移动 1px ...")
    sc = probe_setcursor()
    print(f"  SetCursorPos : {'PASS' if sc else 'FAIL'}")
    print("[probe] SendInput 注入移动 1px ...")
    si = probe_sendinput()
    print(f"  SendInput    : {'PASS' if si else 'FAIL'}")
    if not sc:
        print("[probe] 结论: Windows 输入注入被禁止（UIPI/权限）——需管理员运行")
        print("[probe] 先执行: python tools/input_privilege_check.py")
        return 1
    if not si:
        print("[probe] 结论: SendInput 被 UIPI 拦截（非管理员）——提权后重试")
        return 2
    print("[probe] 结论: 输入注入可用（若游戏内无响应 → 游戏侧问题，非 Windows）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

```
