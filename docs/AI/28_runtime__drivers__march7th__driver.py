# runtime/drivers/march7th/driver.py

```python
"""March7th Driver 薄门面：只组合 input/vision/window，不做业务逻辑。

约束：本目录任何文件不得演化为"新的 automation.py 巨石"——
input 管动作、vision 管观测、window 管窗口，各司其职。
"""
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


def get_driver():
    global _cached
    if _cached is None:
        _cached = March7thDriver()
    return _cached

```
