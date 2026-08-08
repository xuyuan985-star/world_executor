"""诊断脚本：连拍 3 帧游戏前台截图，输出亮度/帧差（画面变化探活用）。"""
import ctypes
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np
from PIL import Image

from runtime.win_capture import find_game_window, capture_game_foreground


def main():
    ctypes.windll.user32.SetProcessDPIAware()  # #18：DPI context 进程早期设置
    g = find_game_window()
    if g is None:
        print("[FAIL] 未找到可见游戏窗口")
        return 1
    out_dir = os.path.join(ROOT, "ingest", "raw", "frames", "live")
    os.makedirs(out_dir, exist_ok=True)
    imgs = []
    for i in range(3):
        im = capture_game_foreground(g)
        a = np.asarray(im).astype(int)
        imgs.append(a)
        dark = round((a.mean(axis=2) < 30).mean() * 100, 1)
        bright = round((a.mean(axis=2) > 200).mean() * 100, 1)
        print(f"frame{i}: {im.size} mean={a.mean():.1f} dark%={dark} bright%={bright}")
        Image.fromarray(a.astype("uint8")).save(os.path.join(out_dir, f"diag_{i}.jpg"), "JPEG", quality=92)
        time.sleep(1.0)
    for n, d in [("0-1", np.abs(imgs[0] - imgs[1]).mean()),
                 ("1-2", np.abs(imgs[1] - imgs[2]).mean()),
                 ("0-2", np.abs(imgs[0] - imgs[2]).mean())]:
        print(f"frame diff {n}: {d:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
