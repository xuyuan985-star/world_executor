import sys
import time
from pathlib import Path

from runtime.input.base import InputBackend, InputResult

M7_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "March7thAssistant"


class March7thBackend(InputBackend):
    """March7thAssistant 输入后端（pyautogui/win32 封装）。"""

    name = "march7th"

    def __init__(self):
        self._auto = None

    def ensure_auto(self):
        if self._auto is not None:
            return self._auto
        sys.path.insert(0, str(M7_ROOT))
        from module.automation import auto
        self._auto = auto
        return auto

    def _wrap(self, action, fn, *args):
        try:
            fn(*args)
            return InputResult(success=True, action=action, backend=self.name)
        except Exception as e:
            return InputResult(success=False, action=action, backend=self.name,
                               error=f"{type(e).__name__}: {e}")

    def click(self, x, y):
        auto = self.ensure_auto()
        return self._wrap("click", auto.mouse_click, int(x), int(y))

    def move(self, x, y):
        auto = self.ensure_auto()
        return self._wrap("move", auto.mouse_move, int(x), int(y))

    def press_key(self, key, wait_time=0.2):
        auto = self.ensure_auto()
        return self._wrap("press_key", auto.press_key, key, wait_time)
