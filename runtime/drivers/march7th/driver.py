"""March7th Driver 薄门面：只组合 input/vision/window，不做业务逻辑。

约束：本目录任何文件不得演化为"新的 automation.py 巨石"——
input 管动作、vision 管观测、window 管窗口，各司其职。
"""
import threading

from runtime.drivers.march7th.input import March7thInputBackend
from runtime.drivers.march7th.vision import March7thVision
from runtime.drivers.march7th.window import find_game_window, set_foreground_with_retry


class March7thDriver:
    name = "march7th"

    def __init__(self):
        self.input = March7thInputBackend()
        self.vision = March7thVision()
        self.find_window = find_game_window
        self.activate_window = set_foreground_with_retry


_cached = None
_driver_lock = threading.Lock()


def get_driver():
    # 审查：单例加锁——多线程首次调用竞态会创建两个 driver（后写覆盖，
    # 各线程持有不同 driver → input/vision 状态分裂）。锁后幂等。
    global _cached
    if _cached is None:
        with _driver_lock:
            if _cached is None:
                _cached = March7thDriver()
    return _cached
