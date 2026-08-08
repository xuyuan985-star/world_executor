import sys
import time

sys.path.insert(0, r"C:\Users\xuyua\Desktop\Open Code\world_executor")
import os

os.chdir(r"C:\Users\xuyua\Desktop\Open Code\world_executor")

import numpy as np
from PIL import Image

from runtime.win_capture import find_game_window, capture_game_foreground

g = find_game_window()
imgs = []
for i in range(3):
    im = capture_game_foreground(g)
    a = np.asarray(im).astype(int)
    imgs.append(a)
    print(f"frame{i}: {im.size} mean={a.mean():.1f} dark%={round((a.mean(axis=2) < 30).mean() * 100, 1)} bright%={round((a.mean(axis=2) > 200).mean() * 100, 1)}")
    Image.fromarray(a.astype("uint8")).save(f"ingest/raw/frames/live/diag_{i}.jpg", "JPEG", quality=92)
    time.sleep(1.0)
for n, d in [("0-1", np.abs(imgs[0] - imgs[1]).mean()), ("1-2", np.abs(imgs[1] - imgs[2]).mean()), ("0-2", np.abs(imgs[0] - imgs[2]).mean())]:
    print(f"frame diff {n}: {d:.2f}")
