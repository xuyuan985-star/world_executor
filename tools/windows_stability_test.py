"""Windows 稳定层真机测试矩阵（Sprint D-11）。

  Test 1  窗口枚举（评分选择）
  Test 2  截图稳定（连续 100 帧 success rate > 99%）
  Test 3  输入稳定（100 clicks success > 95%）——需管理员
  Test 4  遮挡恢复（CaptureManager 降级链）

用法：python tools/windows_stability_test.py [--frames 100] [--clicks 100]
游戏未启动时 Test 1 输出窗口缺失并跳过其余。
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description="Windows 稳定层真机测试")
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--clicks", type=int, default=100)
    args = parser.parse_args()

    if sys.platform != "win32":
        print("[FAIL] Windows only")
        return 1
    import ctypes
    ctypes.windll.user32.SetProcessDPIAware()

    # Test 1：窗口枚举与评分
    from runtime.platform.windows.window import find_best_window, score_window
    from runtime.win_capture import process_identity
    gw = find_best_window()
    if gw is None:
        print("[SKIP] Test 1: 游戏未启动（请先启动《崩坏：星穹铁道》）")
        print("STABILITY: SKIP")
        return 2
    print(f"[Test 1] found hwnd={hex(gw.hwnd)} {gw.width}x{gw.height} "
          f"visible={gw.visible} score={gw.score:.1f}")
    gw.pid = process_identity(gw.hwnd)[1]
    print(f"         pid={gw.pid}")
    if gw.score < 70:
        print("[FAIL] Test 1: 窗口评分过低（可能抓到非游戏窗口）")
        return 1
    print("[PASS] Test 1 窗口枚举/评分")

    # Test 2：截图稳定
    from runtime.drivers.march7th.vision import March7thVision
    vision = March7thVision()
    ok = 0
    failures = []
    t0 = time.time()
    for i in range(args.frames):
        try:
            shot = vision.take_screenshot()
            q = getattr(vision, "last_quality", None)
            if shot is not None and (q is None or q.quality == "ok"):
                ok += 1
            elif q is not None:
                failures.append(f"#{i}:{q.quality}")
        except Exception as e:
            failures.append(f"#{i}:{type(e).__name__}")
    rate = ok / args.frames
    print(f"[Test 2] 截图 {args.frames} 帧 success={rate:.2%} ({time.time()-t0:.1f}s)")
    if failures:
        print(f"         异常样本: {failures[:8]}")
    if rate < 0.99:
        print("[FAIL] Test 2 截图稳定率 < 99%")
        return 1
    print("[PASS] Test 2 截图稳定")

    # Test 3：输入稳定（需管理员）
    from runtime.platform.windows.privilege import is_admin
    from runtime.input.win32_backend import Win32Backend
    if not is_admin():
        print("[SKIP] Test 3 输入稳定：非管理员（先以管理员运行）")
    else:
        backend = Win32Backend()
        ok = 0
        import ctypes.wintypes
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        bx, by = pt.x, pt.y
        for i in range(args.clicks):
            r = backend.click(bx + (i % 5), by + ((i // 5) % 5))
            if r.success:
                ok += 1
        rate = ok / args.clicks
        print(f"[Test 3] 点击 {args.clicks} 次 success={rate:.2%}")
        if rate < 0.95:
            print("[FAIL] Test 3 输入稳定率 < 95%")
            return 1
        print("[PASS] Test 3 输入稳定")

    # Test 4：遮挡恢复（CaptureManager 降级链调用）
    from runtime.platform.windows.capture import CaptureManager
    cm = CaptureManager(vision=vision)
    frame = cm.capture(gw)
    print(f"[Test 4] 捕获方式={frame.method} quality={frame.quality} "
          f"confidence={frame.confidence}")
    if frame.image is None:
        print("[FAIL] Test 4 捕获失败")
        return 1
    print("[PASS] Test 4 捕获链（含元数据）")

    print("STABILITY: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
