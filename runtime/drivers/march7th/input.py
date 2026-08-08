"""March7th 输入桥接：实现 InputBackend 协议 + execute(ActionIntent)。

官方原语（automation.py 源码确认）：
  auto.click_element(path, "image", threshold, max_retries)   # 模板点击
  auto.click_element(text, "text", include, max_retries, crop) # 文字点击
  auto.press_key(key, wait_time)                               # 按键
内部完成 截图→查找→坐标换算→pyautogui 点击，坐标体系由 March7th 保证。
"""
from runtime.drivers.march7th.window import ensure_march7th_env
from runtime.input.base import InputBackend, InputResult


class March7thInputBackend(InputBackend):
    name = "march7th"

    def __init__(self):
        ensure_march7th_env()
        from module.automation import auto
        self.auto = auto

    def _wrap(self, action, fn, *args, **kw):
        try:
            fn(*args, **kw)
            return InputResult(success=True, action=action, backend=self.name)
        except Exception as e:
            return InputResult(success=False, action=action, backend=self.name,
                               error=f"{type(e).__name__}: {e}")

    def click(self, x, y):
        return self._wrap("click", self.auto.mouse_click, int(x), int(y))

    def move(self, x, y):
        return self._wrap("move", self.auto.mouse_move, int(x), int(y))

    def press_key(self, key, wait_time=0.2):
        """#43：March7th 原语 keyDown→sleep→keyUp 无 finally 释放——
        异常时按键会卡死。此处包一层兜底 keyUp 释放（pyautogui 由 March7th 依赖保证可用）。"""
        try:
            self.auto.press_key(key, wait_time)
            return InputResult(success=True, action="press_key", backend=self.name,
                               method="key")
        except Exception as e:
            try:
                import pyautogui
                pyautogui.keyUp(key)
            except Exception:
                pass
            return InputResult(success=False, action="press_key", backend=self.name,
                               error=f"{type(e).__name__}: {e}")

    def release_key(self, key):
        """#42：兜底 keyup（防卡键），pyautogui 由 March7th 依赖保证可用。"""
        try:
            import pyautogui
            pyautogui.keyUp(key)
            return InputResult(success=True, action="release_key", backend=self.name,
                               method="key")
        except Exception as e:
            return InputResult(success=False, action="release_key", backend=self.name,
                               error=f"{type(e).__name__}: {e}")

    def execute(self, intent):
        """执行 ActionIntent（不接触坐标的动作语义）。"""
        p = intent.params
        if intent.method == "template":
            return self.click_template(intent.target, p.get("threshold", 0.85),
                                       p.get("max_retries", 3))
        if intent.method == "text":
            return self.click_text(intent.target, p.get("include", True),
                                   p.get("max_retries", 3), p.get("crop"))
        if intent.method == "key":
            return self.press_key(intent.target, p.get("wait_time", 0.2))
        return InputResult(success=False, action=intent.action, backend=self.name,
                           error=f"unknown_method:{intent.method}")

    def click_template(self, path, threshold, max_retries):
        ok = bool(self.auto.click_element(path, "image", threshold, max_retries=max_retries))
        return InputResult(success=ok, action="click_template", backend=self.name,
                           error=None if ok else "click_element_failed")

    def click_text(self, text, include, max_retries, crop):
        ok = bool(self.auto.click_element(text, "text", max_retries=max_retries,
                                          include=include, crop=crop))
        return InputResult(success=ok, action="click_text", backend=self.name,
                           error=None if ok else "click_text_failed")
