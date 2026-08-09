"""自研模板点击：cv2 多尺度匹配 + Win32 点击（绕过 March7th 模板匹配）。

动机：March7th 的 click_element 匹配受其环境依赖影响（本机被 security stub
污染导入链），且其 scale_and_match_template 分数低于自研 cv2 多尺度。
验证：真机截图 0.724 @ scale 0.55（模板 260px → 截图 1920）命中。
"""
import time

import cv2
import numpy as np

from runtime.input.win32_backend import Win32Backend


class TemplateMatcher:
    """截图 + 多尺度模板匹配（全屏坐标体系，1:1 映射屏幕坐标）。"""

    SCALES = np.linspace(0.4, 2.5, 43)

    def __init__(self, threshold=0.60, backend=None):
        self.threshold = threshold
        self.backend = backend or Win32Backend()

    def _screenshot(self):
        import mss
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
        # mss 新版本 shot.rgb 为 RGB bytes（无 alpha）
        return np.frombuffer(shot.rgb, dtype=np.uint8).reshape(
            shot.height, shot.width, 3)[:, :, ::-1]

    def locate(self, template_path):
        """返回 (best_val, cx, cy) 屏幕绝对中心坐标；未命中返回 None。"""
        t = cv2.imread(template_path)
        if t is None:
            return None
        screen = self._screenshot()
        sh, sw = screen.shape[:2]
        best = (0.0, 0, 0)
        for scale in self.SCALES:
            th = cv2.resize(t, None, fx=scale, fy=scale,
                            interpolation=cv2.INTER_AREA)
            if th.shape[0] >= sh or th.shape[1] >= sw:
                continue
            res = cv2.matchTemplate(screen, th, cv2.TM_CCOEFF_NORMED)
            _, mv, _, ml = cv2.minMaxLoc(res)
            if mv > best[0]:
                best = (mv, ml[0], ml[1])
        val, x, y = best
        if val < self.threshold:
            return None
        t_h, t_w = t.shape[:2]
        return val, x + int(t_w * 0.55 / 2), y + int(t_h * 0.55 / 2)

    def click_template(self, path, threshold=None, max_retries=3,
                       scale_range=None):
        th = threshold or self.threshold
        for attempt in range(max_retries):
            hit = self.locate(path)
            if hit is None:
                time.sleep(0.8)
                continue
            val, cx, cy = hit
            r = self.backend.click(cx, cy)
            if r.success:
                return r
            time.sleep(0.8)
        return None
