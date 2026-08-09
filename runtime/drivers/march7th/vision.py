"""March7th 视觉桥接：后台截图 / OCR / 模板匹配封装。

坐标体系（源码确认）：截图内坐标 + screenshot_pos（客户区左上角绝对屏幕坐标）= 绝对坐标；
>1920px 截图由 screenshot_scale_factor 归一化。执行器不感知 relative/DPI。
"""
import sys

from runtime.drivers.march7th.window import ensure_march7th_env


class March7thVision:
    name = "march7th"

    def __init__(self):
        ensure_march7th_env()
        from module.automation import auto
        from module.ocr import ocr
        self.auto = auto
        self.ocr = ocr
        # #17-G：最近一次截图的结构质量（成功 ≠ 正确，供调用方在进 VLM 前决策）
        self.last_quality = None
        self._validator = None

    @property
    def validator(self):
        if self._validator is None:
            from runtime.vision_quality import FrameValidator
            self._validator = FrameValidator()
        return self._validator

    def take_screenshot(self, crop=None):
        """#39 截图降级链：PrintWindow 后台 → 前台 mss（失败不裸崩）。

        返回 (PIL.Image, screenshot_pos, scale_factor)。
        crop：截图内归一化裁剪（0-1 四元组），仅 PrintWindow 路径支持；
        前台 mss 降级时忽略 crop（整帧）。
        #17-G：返回前做结构质量校验（全黑/全白/黑边），记入 self.last_quality——
        不抛异常（截图本身成功），由调用方在进 OCR/VLM 前决策。
        BUG-26：降级原因记录进 last_quality.meta.fallback_chain——排查
        "为什么一直走 mss"有据可查。
        """
        source = "print_window"
        chain = []
        try:
            if crop is None:
                out = self.auto.take_screenshot()
            else:
                out = self.auto.take_screenshot(crop=crop)
        except Exception as e:
            chain.append(f"print_window_failed:{type(e).__name__}")
            out = None
        if out is None:
            try:
                from runtime.win_capture import capture_game_foreground
                from runtime.drivers.march7th.window import find_game_window
                game = find_game_window()
                if game is None:
                    raise RuntimeError("no game window for foreground capture")
                img = capture_game_foreground(game)
                left, top = game["client"][0], game["client"][1]
                out = (img, (left, top, game["client"][0], game["client"][1]), 1.0)
                source = "foreground_mss"
            except Exception as e:
                chain.append(f"foreground_mss_failed:{type(e).__name__}")
                raise RuntimeError("截图降级链失败：PrintWindow 与前台 mss 均不可用")
        img = out[0]
        self.last_quality = self.validator.validate(img, source=source)
        if chain:
            self.last_quality.meta["fallback_chain"] = chain
        return out

    def screenshot_path(self, out_dir):
        """后台截图落盘，返回路径（VLM 观测帧用）。"""
        import time
        from pathlib import Path
        shot = self.take_screenshot()
        img, _, _ = shot
        p = Path(out_dir) / f"shot_{int(time.time() * 1000)}.jpg"
        p.parent.mkdir(parents=True, exist_ok=True)
        img.save(p, "JPEG", quality=90)
        return p

    def ocr_lines(self, crop=(0, 0, 1, 1)):
        """OCR 返回 [(text, box), ...]，box 为四点 [(x,y),...] 截图内坐标。"""
        import numpy as np
        # crop 仅对 March7th 后台截图有效（前台 mss 降级路径不支持裁剪）
        img, _, _ = self.take_screenshot(crop=crop)
        out = []
        for t in self.ocr.run(np.asarray(img)) or []:
            if isinstance(t, dict) and t.get("txt"):
                out.append((t["txt"], t["box"]))
        return out

    def find_text(self, text, include=True, max_retries=1, crop=None):
        """find_element("文字", "text") → ((left,top),(right,bottom)) 绝对坐标或 None。"""
        return self.auto.find_element(text, "text", max_retries=max_retries,
                                      include=include, crop=crop)

    def find_template(self, path, threshold=0.8, max_retries=1):
        """find_element(图片, "image") → 绝对坐标框或 None。"""
        return self.auto.find_element(path, "image", threshold, max_retries=max_retries)

    def to_absolute(self, norm_x, norm_y):
        """归一化坐标(0-1) → 绝对屏幕坐标（vlm 定位结果消费，执行细节）。"""
        img, screenshot_pos, scale = self.take_screenshot()
        left, top, w, h = screenshot_pos
        img_w, img_h = img.size
        return left + int(norm_x * img_w / (scale or 1)), top + int(norm_y * img_h / (scale or 1))
