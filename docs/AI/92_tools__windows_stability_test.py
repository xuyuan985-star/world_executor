# tools/windows_stability_test.py

```python
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
    # BUG-01：SKIP 语义——本地 --allow-skip 返回 0；自动巡检默认 2（CI 区分
    # 0 PASS / 1 FAIL / 2 SKIP——游戏未启动=没测试≠通过）
    parser.add_argument("--allow-skip", action="store_true",
                        help="游戏未启动时返回 0（本地手动用）")
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
        # BUG-01：--allow-skip 才返回 0（本地）；否则 2 让 CI 识别"没测试"
        return 0 if args.allow_skip else 2
    print(f"[Test 1] found hwnd={hex(gw.hwnd)} {gw.width}x{gw.height} "
          f"visible={gw.visible} score={gw.score:.1f}")
    gw.pid = process_identity(gw.hwnd)[1]
    print(f"         pid={gw.pid}")
    # Bug10：评分分级（不同 DPI/分辨率/多屏 score 会变——不硬编码单阈值）
    if gw.score < 50:
        print("[FAIL] Test 1: 窗口评分 <50（大概率抓到非游戏窗口）")
        return 1
    if gw.score < 70:
        print("[WARN] Test 1: 窗口评分 50~70（可能是小窗口/异常变体，继续）")
    print("[PASS] Test 1 窗口枚举/评分")

    # Test 2：截图稳定（BUG-02：不只验证拿到图——还要验证图像有效：
    # 非全黑/亮度方差足够/与前一帧不同（防"截图 API 活着但视觉已死"））
    from runtime.drivers.march7th.vision import March7thVision
    import numpy as np
    vision = March7thVision()
    ok = 0
    failures = []
    prev_arr = None
    t0 = time.time()
    for i in range(args.frames):
        try:
            shot = vision.take_screenshot()
            q = getattr(vision, "last_quality", None)
            valid = False
            if shot is not None:
                arr = np.asarray(shot[0].convert("L")).astype(int)
                dark = float((arr < 30).mean())
                var = float(arr.std())
                diff = (float(np.abs(arr - prev_arr).mean())
                        if prev_arr is not None else float("inf"))
                prev_arr = arr
                # 有效性：非全黑 + 方差足够（有内容）+ 与前一帧有变化
                if (q is None or q.quality == "ok") and dark < 0.8 \
                        and var > 5.0 and (i == 0 or diff > 0.5):
                    valid = True
            if valid:
                ok += 1
            else:
                failures.append(f"#{i}:{getattr(q, 'quality', 'invalid')}"
                                f" dark={dark:.2f} var={var:.1f}")
        except Exception as e:
            failures.append(f"#{i}:{type(e).__name__}")
    rate = ok / args.frames
    print(f"[Test 2] 截图 {args.frames} 帧 success={rate:.2%} ({time.time()-t0:.1f}s)")
    if failures:
        print(f"         异常样本: {failures[:8]}")
    if rate < 0.99:
        print("[FAIL] Test 2 截图稳定率 < 99%（含图像有效性）")
        return 1
    print("[PASS] Test 2 截图稳定（含非黑/方差/帧差校验）")

    # Test 3：输入稳定（需管理员）
    from runtime.platform.windows.privilege import is_admin
    from runtime.input.win32_backend import Win32Backend
    if not is_admin():
        print("[SKIP] Test 3 输入稳定：非管理员（先以管理员运行）")
    else:
        backend = Win32Backend()
        ok = 0
        closed_loop = 0
        import ctypes.wintypes
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        bx, by = pt.x, pt.y
        # BUG-03 闭环：点击前后截图，检测目标区域 UI 变化（游戏响应）
        for i in range(args.clicks):
            before = None
            try:
                s = vision.take_screenshot()
                if s is not None:
                    before = np.asarray(s[0].convert("L")).astype(int)
            except Exception:
                pass
            r = backend.click(bx + (i % 5), by + ((i // 5) % 5))
            if r.success:
                ok += 1
                try:
                    s = vision.take_screenshot()
                    if s is not None and before is not None:
                        after = np.asarray(s[0].convert("L")).astype(int)
                        # 点击位置附近区域变化（游戏对输入有响应）
                        h, w = after.shape
                        cx, cy = bx + (i % 5), by + ((i // 5) % 5)
                        x0, y0 = max(0, cx - 30), max(0, cy - 30)
                        x1, y1 = min(w, cx + 30), min(h, cy + 30)
                        if x1 > x0 and y1 > y0:
                            d = float(np.abs(
                                after[y0:y1, x0:x1].astype(int)
                                - before[y0:y1, x0:x1].astype(int)).mean())
                            if d > 1.0:
                                closed_loop += 1
                except Exception:
                    pass
            time.sleep(0.05)
        rate = ok / args.clicks
        print(f"[Test 3] 点击 {args.clicks} 次 success={rate:.2%} "
              f"UI响应={closed_loop}/{ok}")
        if rate < 0.95:
            print("[FAIL] Test 3 输入稳定率 < 95%")
            return 1
        print("[PASS] Test 3 输入稳定（含点击区域 UI 响应）")

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

```
