"""坐标校准：后台截图 + OCR → 换算绝对屏幕坐标 → 移动光标回读。

不注入输入事件（不弹 UAC），只验证换算正确性。光标会移动到换算坐标，
请肉眼确认是否落在“商店”按钮上。
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
M7 = ROOT.parent / "March7thAssistant"


def main():
    # #20-3.4：DPI context 必须进程早期设置（任何 GDI/窗口 API 调用之前）；
    # Windows 专用工具在非 Windows 上明确失败
    if os.name != "nt":
        raise RuntimeError("coords_calibrate 仅支持 Windows")
    import ctypes
    ctypes.windll.user32.SetProcessDPIAware()

    from runtime.security import install_pylnk3_stub, require_m7_path
    require_m7_path(M7)
    install_pylnk3_stub()
    os.chdir(M7)
    sys.path.insert(0, str(M7))
    sys.path.insert(0, str(ROOT))

    from module.automation import auto
    from module.ocr import ocr
    from runtime.win_capture import find_game_window
    from ctypes import wintypes

    game = find_game_window()
    if game is None:
        print("[FAIL] 未检测到游戏窗口 —— 请先启动《崩坏：星穹铁道》并进入主菜单")
        sys.exit(1)
    print(f"[info] 游戏窗口: {hex(game['hwnd'])} client={game['client']}")

    shot = auto.take_screenshot()
    if not shot:
        print("[FAIL] take_screenshot 失败（窗口可能没开）")
        sys.exit(1)
    img, screenshot_pos, scale_factor = shot
    pos_left, pos_top, _, _ = screenshot_pos
    print(f"[info] 后台截图: {img.size} pos=({pos_left},{pos_top}) scale={scale_factor}")

    import numpy as np
    lines = []
    for t in ocr.run(np.asarray(img)) or []:
        if isinstance(t, dict) and t.get("txt"):
            lines.append((t["txt"], t["box"]))
    target = None
    for txt, box in lines:
        t = (txt or "").strip()
        # #20-3.3：目标匹配收紧（同 click_test）：防"商店铺/商店公告"误点
        if "商店" in t and len(t) <= 4:
            target = (t, box)
            break
    if target is None:
        print(f"[FAIL] 未找到商店。OCR: {[t for t, _ in lines][:15]}")
        sys.exit(1)

    txt, box = target
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    lx, ly = sum(xs) / len(xs), sum(ys) / len(ys)
    f = scale_factor if scale_factor and scale_factor != 1 else 1
    px = pos_left + int(lx / f)
    py = pos_top + int(ly / f)
    print(f"[ok] “{txt}” 截图内({lx:.0f},{ly:.0f}) → 绝对({px},{py})")

    user32 = ctypes.windll.user32
    user32.SetCursorPos(px, py)
    time.sleep(0.5)
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    print(f"[check] 光标已移至 ({pt.x},{pt.y}) —— 请确认是否落在“商店”按钮上")

    out = ROOT / "ingest" / "raw" / "frames" / "live"
    out.mkdir(parents=True, exist_ok=True)
    img.save(str(out / "calibrate.jpg"), "JPEG", quality=92)
    print(f"[info] 截图已存: {out / 'calibrate.jpg'}")


if __name__ == "__main__":
    main()
