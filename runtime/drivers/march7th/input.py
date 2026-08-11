"""March7th 输入桥接（数据内化）：全自研——不再 import m7 的 module.automation。

click/move/press_key/release_key → runtime.input.win32_backend（SendInput）
click_template → runtime.input.template_backend（cv2 多尺度 + Win32 点击）
click_text → 自研 OCR 定位（ocr_engine）+ 点击
"""

from runtime.input.base import InputBackend, InputResult


class March7thInputBackend(InputBackend):
    name = "march7th"

    def __init__(self):
        # 数据内化：构造零外部依赖（不再 ensure_march7th_env / import module）
        from runtime.input.win32_backend import Win32Backend
        self.backend = Win32Backend()

    def _wrap(self, action, fn, *args, **kw):
        try:
            r = fn(*args, **kw)
            if getattr(r, "success", None) is False:
                return r
            return InputResult(success=True, action=action, backend=self.name)
        except Exception as e:
            return InputResult(success=False, action=action, backend=self.name,
                               error=f"{type(e).__name__}: {e}")

    def click(self, x, y):
        return self._wrap("click", self.backend.click, int(x), int(y))

    def move(self, x, y):
        return self._wrap("move", self.backend.move, int(x), int(y))

    def press_key(self, key, wait_time=0.2):
        """最低层组合 keyDown→sleep→finally keyUp（win32_backend 内部保证
        finally 释放——卡死/异常时按键不卡住）。"""
        return self.backend.press_key(key, wait_time)

    def release_key(self, key):
        """兜底 keyup（防卡键）。"""
        return self.backend.release_key(key)

    def execute(self, intent):
        """执行 ActionIntent（不接触坐标的动作语义）。"""
        p = intent.params
        if intent.method == "template":
            return self.click_template(intent.target, p.get("threshold", 0.85),
                                       p.get("max_retries", 3),
                                       scale_range=p.get("scale_range"))
        if intent.method == "text":
            return self.click_text(intent.target, p.get("include", True),
                                   p.get("max_retries", 3), p.get("crop"))
        if intent.method == "key":
            return self.press_key(intent.target, p.get("wait_time", 0.2))
        return InputResult(success=False, action=intent.action, backend=self.name,
                           error=f"unknown_method:{intent.method}")

    def click_template(self, path, threshold, max_retries, scale_range=None):
        # 模板点击走自研 cv2 多尺度匹配（见 runtime/input/template_backend.py）
        from runtime.input.template_backend import TemplateMatcher
        try:
            result = TemplateMatcher(threshold=threshold).click_template(
                path, threshold=threshold, max_retries=max_retries,
                scale_range=scale_range)
        except Exception as e:
            return InputResult(success=False, action="click_template", backend=self.name,
                               error=f"template_backend:{type(e).__name__}: {e}")
        if result is None:
            return InputResult(success=False, action="click_template", backend=self.name,
                               error="click_element_failed")
        result.detail["backend"] = self.name + "+win32"
        return result

    def click_text(self, text, include=True, max_retries=3, crop=None):
        """自研：OCR 定位文本 → 框中心点击（替代 m7 auto.click_element text）。"""
        import time
        from runtime.drivers.march7th.vision import March7thVision
        vision = March7thVision()
        for _ in range(max(1, max_retries or 1)):
            box = vision.find_text(text, include=include, crop=crop)
            if box:
                (lx, ty), (rx, by) = box
                r = self.backend.click((lx + rx) // 2, (ty + by) // 2)
                if r.success:
                    return InputResult(success=True, action="click_text",
                                       backend=self.name)
            time.sleep(0.5)
        return InputResult(success=False, action="click_text", backend=self.name,
                           error="click_text_failed")
