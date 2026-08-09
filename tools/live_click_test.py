"""真机点击测试（M1-A G2）：模板匹配定位 → 真实点击宝箱 → 截图验证。

非管理员时自动提权重启（pyuac/ShellExecute runas——本机 UAC 为不提示直接提升）。
错误写 logs/live_click.log（提权进程控制台一闪而过，日志可查）。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # 提权后 cwd 可能变 System32——必须 __file__ 定位
sys.path.insert(0, str(ROOT))
LOG = ROOT / "logs" / "live_click.log"


def _log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg)


def main():
    try:
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            _log("[提权] 需要管理员权限（本机 UAC=不提示直接提升）")
            import pyuac
            pyuac.runAsAdmin()
            sys.exit(0)
        _run()
    except Exception as e:
        import traceback
        _log("EXC: " + traceback.format_exc())
        return 1
    return 0


def _run():
    import ctypes
    import ctypes.wintypes
    _log(f"[diag] IsUserAnAdmin={bool(ctypes.windll.shell32.IsUserAnAdmin())}")
    try:
        tok = ctypes.wintypes.HANDLE()
        if ctypes.windll.advapi32.OpenProcessToken(
                ctypes.windll.kernel32.GetCurrentProcess(), 0x0008,
                ctypes.byref(tok)):
            il = ctypes.wintypes.DWORD()
            sz = ctypes.wintypes.DWORD()
            ctypes.windll.advapi32.GetTokenInformation(
                tok, 25, ctypes.byref(il), 4, ctypes.byref(sz))
            _log(f"[diag] 完整性级别={il.value:#x} (High=0x3000)")
            ctypes.windll.kernel32.CloseHandle(tok)
    except Exception as e:
        _log(f"[diag] integrity EXC: {e}")

    import cv2
    import numpy as np
    from runtime.drivers.march7th.vision import March7thVision

    _log("=== live_click_test（管理员）===")
    vision = March7thVision()
    shot = vision.take_screenshot()
    if shot is None:
        _log("[FAIL] 截图失败")
        return 1
    img, screenshot_pos, _ = shot
    frame = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2GRAY)
    _log(f"[ok] 截图 {img.size} pos={screenshot_pos}")

    # 模板匹配：找置信最高的宝箱
    templates = sorted((ROOT / "knowledge" / "guides" / "maps" /
                        "02_herta_space_station" / "templates").glob("*.png"))
    best = None
    for tmpl in templates:
        t = cv2.imread(str(tmpl), cv2.IMREAD_GRAYSCALE)
        if t is None or t.shape[0] >= frame.shape[0] or t.shape[1] >= frame.shape[1]:
            continue
        res = cv2.matchTemplate(frame, t, cv2.TM_CCOEFF_NORMED)
        _, maxv, _, maxloc = cv2.minMaxLoc(res)
        if best is None or maxv > best[0]:
            best = (maxv, tmpl.name, maxloc, t.shape)
    if best is None or best[0] < 0.6:
        _log(f"[FAIL] 无高置信宝箱模板（最高 {best[0] if best else 0:.2f}）")
        return 2
    conf, name, (tx, ty), (th, tw) = best
    cx, cy = tx + tw // 2, ty + th // 2
    left, top, _, _ = screenshot_pos
    ax, ay = left + cx, top + cy
    _log(f"[ok] 命中 {name} 置信 {conf:.2f} → 绝对 ({ax},{ay})")

    from runtime.input.win32_backend import Win32Backend
    # 详细 SendInput 探针：move 与 click 分开测
    try:
        import ctypes.wintypes
        user32 = ctypes.windll.user32
        class MI(ctypes.Structure):
            _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                        ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                        ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]
        class INP(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("mi", MI)]
        i = INP(); i.type = 0; i.mi.dx = 1; i.mi.dy = 0; i.mi.dwFlags = 0x0001
        ret_move = user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INP))
        _log(f"[diag] SendInput move ret={ret_move}")
        i2 = INP(); i2.type = 0; i2.mi.dwFlags = 0x0002  # LEFTDOWN
        ret_down = user32.SendInput(1, ctypes.byref(i2), ctypes.sizeof(INP))
        _log(f"[diag] SendInput leftdown ret={ret_down}")
        i3 = INP(); i3.type = 0; i3.mi.dwFlags = 0x0004  # LEFTUP
        ret_up = user32.SendInput(1, ctypes.byref(i3), ctypes.sizeof(INP))
        _log(f"[diag] SendInput leftup ret={ret_up}")
    except Exception as e:
        _log(f"[diag] SendInput probe EXC: {e}")
    backend = Win32Backend()
    r = backend.click(ax, ay)
    _log(f"[ok] 点击 {'成功' if r.success else '失败'} {r.error or ''}")

    import time
    time.sleep(1.0)
    shot2 = vision.take_screenshot()
    if shot2:
        img2 = shot2[0]
        frame2 = cv2.cvtColor(np.asarray(img2), cv2.COLOR_RGB2GRAY)
        # 审查 P1：必须用实际点击的那个模板（best[1]）验证——
        # 原用 templates[0]（排序第一个）验证的是另一个模板，结果无意义
        t2 = cv2.imread(str(ROOT / "knowledge" / "guides" / "maps" /
                           "02_herta_space_station" / "templates" / name),
                        cv2.IMREAD_GRAYSCALE)
        res2 = cv2.matchTemplate(frame2, t2, cv2.TM_CCOEFF_NORMED)
        _, maxv2, _, _ = cv2.minMaxLoc(res2)
        _log(f"[verify] 点击后模板置信 {maxv2:.2f}")
    _log("CLICK TEST DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
