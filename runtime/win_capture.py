import ctypes
import time

import win32gui
import win32ui
import win32con

GAME_TITLE = "崩坏：星穹铁道"
GAME_PROCESS = "StarRail.exe"


def process_identity(hwnd):
    """#17-F：窗口身份三元组 (hwnd, pid, process_create_time)。

    GetWindowThreadProcessId 取 pid；OpenProcess + GetProcessTimes 取创建时间。
    创建时间取不到时返回 (hwnd, pid, None)——此时降级为二元组判定。
    """
    pid = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, None) or None
    create_time = None
    if pid:
        import ctypes.wintypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            try:
                created = ctypes.wintypes.FILETIME()
                if ctypes.windll.kernel32.GetProcessTimes(
                        handle, ctypes.byref(created), None, None, None):
                    create_time = (created.dwHighDateTime << 32) | created.dwLowDateTime
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
    return (hwnd, pid, create_time)


def find_game_window(title=GAME_TITLE):
    """枚举可见窗口：标题匹配 + 客户区面积最大。

    #20：优先按进程名过滤（StarRail.exe），避免启动器/覆盖层同名窗口抢选；
    进程名取不到时退化为面积最大（旧行为）。
    """
    import win32process
    found = []

    def collect(hwnd, _):
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return
        # 最小化窗口不可操作（截图/点击都失效）——不能算"游戏窗口"
        if ctypes.windll.user32.IsIconic(hwnd):
            return
        if win32gui.GetWindowText(hwnd) != title:
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = win32process.GetModuleFileNameEx(win32gui.GetWindowProcess(hwnd))
        except Exception:
            proc = ""
        if proc and GAME_PROCESS.lower() not in proc.lower():
            return
        cl = win32gui.GetClientRect(hwnd)
        found.append((hwnd, cl, cl[2] * cl[3]))

    win32gui.EnumWindows(collect, None)
    if not found:
        return None
    found.sort(key=lambda x: -x[2])
    hwnd, cl, _ = found[0]
    return {
        "hwnd": hwnd,
        "client": (cl[2], cl[3]),
        "visible": True,
    }


class WindowStateMonitor:
    """#19：监测游戏窗口状态变化（旧名 WindowLock 误导——它不 lock，只 detect）。

    客户区尺寸变化 = 状态变化（resize/遮挡/最小化恢复），供调用方决策。
    #17-F：身份三元组（hwnd + pid + 进程创建时间）——HWND 可被系统复用
    （游戏重启/更新后旧句柄可能指向新窗口），仅靠 hwnd 会错绑。
    """

    def __init__(self, title=GAME_TITLE):
        self.title = title
        self._last_rect = None
        self._identity = None  # (hwnd, pid, create_time)

    def acquire(self):
        info = find_game_window(self.title)
        if info is None:
            raise RuntimeError("未找到可见的游戏窗口")
        rect = info["client"]
        changed = self._last_rect is not None and self._last_rect != rect
        identity = process_identity(info["hwnd"])
        if identity != self._identity:
            changed = True  # 窗口句柄/进程变化（重启、复用）→ 视为窗口更换
        self._last_rect = rect
        self._identity = identity
        info["pid"] = identity[1] if identity else None
        return {**info, "changed": changed}


def try_capture_window(info, flags=3):
    """#21：尝试经 PrintWindow 捕获窗口（旧名 capture_game_background 误导）。

    PrintWindow 对 DX 游戏后台常失败（ISSUE-08），这是"尝试"而非"后台保证"——
    失败抛异常由调用方走前台路径或失败报告。
    """
    hwnd = info["hwnd"]
    w, h = info["client"]
    if w <= 0 or h <= 0:
        raise RuntimeError(f"游戏客户区为空: {w}x{h}")
    hwndDC = None
    mfcDC = None
    saveDC = None
    bmp = None
    try:
        hwndDC = win32gui.GetWindowDC(hwnd)
        mfcDC = win32ui.CreateDCFromHandle(hwndDC)
        saveDC = mfcDC.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfcDC, w, h)
        saveDC.SelectObject(bmp)
        result = ctypes.windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), flags)
        from PIL import Image
        bmpinfo = bmp.GetInfo()
        buf = bmp.GetBitmapBits(True)
        img = Image.frombuffer("RGB", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]), buf, "raw", "BGRX", 0, 1)
        if result != 1:
            raise RuntimeError(f"PrintWindow 失败 code={result}")
        return img
    finally:
        # GDI 资源必须释放，中途异常也不得泄漏（DC/bitmap handle）
        if bmp is not None:
            try:
                win32gui.DeleteObject(bmp.GetHandle())
            except Exception:
                pass
        if saveDC is not None:
            try:
                saveDC.DeleteDC()
            except Exception:
                pass
        if mfcDC is not None:
            try:
                mfcDC.DeleteDC()
            except Exception:
                pass
        if hwndDC is not None:
            try:
                win32gui.ReleaseDC(hwnd, hwndDC)
            except Exception:
                pass


def set_foreground_with_retry(hwnd):
    """激活窗口（含 AttachThreadInput 回退，参考 March7th set_foreground_window_with_retry）。"""
    import time
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    SW_RESTORE = 9
    if user32.IsWindow(hwnd) == 0:
        raise RuntimeError(f"Invalid window handle: {hwnd}")
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.1)
    # 验证循环：SetForeground 返回非 0 不保证前台生效
    # （UAC 提权瞬间前台被系统清空 → GetForegroundWindow 可为 0）
    for _ in range(5):
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.1)
        if user32.GetForegroundWindow() == hwnd:
            return True
    try:
        user32.BringWindowToTop(hwnd)
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.05)
        if user32.SetForegroundWindow(hwnd):
            time.sleep(0.1)
            if user32.GetForegroundWindow() == hwnd:
                return True
    except Exception:
        pass
    fg = user32.GetForegroundWindow()
    if fg:
        attached = False
        try:
            fg_tid = user32.GetWindowThreadProcessId(fg, None)
            this_tid = kernel32.GetCurrentThreadId()
            attached = bool(user32.AttachThreadInput(this_tid, fg_tid, True))
            try:
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                time.sleep(0.05)
                if user32.GetForegroundWindow() == hwnd:
                    return True
            finally:
                if attached:
                    user32.AttachThreadInput(this_tid, fg_tid, False)
        except Exception:
            pass
    raise RuntimeError("Failed to set window foreground after multiple attempts")


def capture_game_foreground(info, wait_seconds=0.8, prewarm=True):
    """激活游戏窗口后截取其客户区（C.4 窗口锁定协议：操作前必须激活窗口）。

    #18：SetProcessDPIAware 不在本函数调用——DPI context 必须在进程早期设置，
    由各入口 main() 统一处理（gui/run.py、工具脚本）。
    #11：截图前确认前台仍为游戏窗口（0.8s 等待期间用户切走则放弃，防截错窗口）。
    """
    import time
    hwnd = info["hwnd"]
    set_foreground_with_retry(hwnd)
    time.sleep(wait_seconds)
    if ctypes.windll.user32.GetForegroundWindow() != hwnd:
        raise RuntimeError("前台已被切换（用户介入或抢焦点失败），放弃前台截图")

    pt = win32gui.ClientToScreen(hwnd, (0, 0))
    w, h = info["client"]
    import mss
    with mss.mss() as sct:
        region = {"left": pt[0], "top": pt[1], "width": w, "height": h}
        if prewarm:
            sct.grab(region)
            time.sleep(1.2)
        shot = sct.grab(region)
    from PIL import Image
    return Image.frombytes("RGB", shot.size, shot.rgb)
