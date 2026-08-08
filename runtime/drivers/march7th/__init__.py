"""March7th Driver：输入/视觉/窗口 统一入口。"""
from runtime.drivers.march7th.input import March7thInputBackend
from runtime.drivers.march7th.vision import March7thVision
from runtime.drivers.march7th.window import find_game_window, set_foreground_with_retry

_cached = {}


def get_driver():
    if "march7th" not in _cached:
        _cached["march7th"] = {
            "input": March7thInputBackend(),
            "vision": March7thVision(),
            "window": find_game_window,
            "window_activate": set_foreground_with_retry,
        }
    return _cached["march7th"]
