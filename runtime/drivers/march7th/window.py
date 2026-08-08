"""March7th 窗口桥接：可见窗口枚举 + 客户区信息。

March7th 自带的 get_window 取第一个 title 匹配（双实例会踩中隐藏 0x0 窗口），
这里用可见窗口枚举 + 最大客户区选择规避。
"""
import ctypes
import sys
import time
from pathlib import Path

M7_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent / "March7thAssistant"


def find_game_window():
    import win32gui
    best = None
    def cb(hwnd, _):
        nonlocal best
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title or "星穹铁道" not in title:
            return True
        rect = win32gui.GetWindowRect(hwnd)
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        # #22 增强：过滤 0x0/极小窗口（游戏标题的托盘/隐藏变体）
        if w < 500 or h < 500:
            return True
        if best is None or w * h > best[1]:
            best = (hwnd, w * h, (w, h))
        return True
    win32gui.EnumWindows(cb, None)
    if best is None:
        return None
    hwnd, _, (w, h) = best
    return {"hwnd": hwnd, "client": (w, h)}


def set_foreground_with_retry(hwnd, attempts=3):
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    for _ in range(attempts):
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)
            time.sleep(0.1)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.15)
        fg = user32.GetForegroundWindow()
        if fg == hwnd:
            return True
        if user32.IsWindowVisible(hwnd):
            fg_thread = kernel32.GetCurrentThreadId()
            win_thread = user32.GetWindowThreadProcessId(hwnd, None)
            user32.AttachThreadInput(fg_thread, win_thread, True)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.AttachThreadInput(fg_thread, win_thread, False)
    return False


def ensure_march7th_env():
    """March7th 硬约束：cwd 必须为根目录（CONFIG_PATH=./config.yaml）。

    同时注入 pylnk3 stub：pylnk3 是 PyPI 历史投毒包（0.4.2 恶意版本事件，
    module/config 存在混淆授权校验），本项目不启动游戏、不用 .lnk 解析，
    禁止装真包（ISSUE-03）。
    """
    import types
    if not sys.modules.get("pylnk3"):
        stub = types.ModuleType("pylnk3")

        class Lnk:
            # #33：补齐常用属性，避免后续代码访问 Lnk().path 等直接炸
            path = ""
            arguments = ""
            work_dir = ""

            def __init__(self, f):
                self.path = str(f)
        stub.Lnk = Lnk
        sys.modules["pylnk3"] = stub
    if str(M7_ROOT) not in sys.path:
        sys.path.insert(0, str(M7_ROOT))
    import os
    if os.getcwd() != str(M7_ROOT):
        os.chdir(M7_ROOT)
