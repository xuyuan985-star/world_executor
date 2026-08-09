"""March7th 视觉桥接：后台截图 / OCR / 模板匹配封装。

坐标体系（源码确认）：截图内坐标 + screenshot_pos（客户区左上角绝对屏幕坐标）= 绝对坐标；
>1920px 截图由 screenshot_scale_factor 归一化。执行器不感知 relative/DPI。
"""
import os
import sys
import threading

from runtime.drivers.march7th.window import ensure_march7th_env

# Bug 5：March7th 构造需要 cwd=M7_ROOT（读 ./config.yaml），但 os.chdir 是
# 进程级——多线程（GUI HealthWorker/FrameWorker）会互相污染 cwd。
# 锁内构造 + 构造完立即恢复：cwd 只在瞬态窗口内处于 M7。
_M7_INIT_LOCK = threading.Lock()

# Bug 155：OCR 文本清洗（形近字归一：宝箱O→宝箱0，全角→半角）
_OCR_TRANSLATE = str.maketrans({
    "O": "0", "o": "0", "l": "1", "I": "1",
    "S": "5", "s": "5", "B": "8", "b": "8",
    "G": "6", "g": "6", "Z": "2", "z": "2",
})


def normalize_ocr(text):
    """OCR 文本清洗——全角→半角 + ASCII 形近字归一（防 宝箱O/宝箱0 匹配失败）。"""
    if not text:
        return text
    out = []
    for ch in text:
        code = ord(ch)
        if 0xFF10 <= code <= 0xFF19:  # 全角数字 ０-９
            out.append(chr(code - 0xFEE0))
            continue
        if 0xFF21 <= code <= 0xFF3A or 0xFF41 <= code <= 0xFF5A:  # 全角字母
            out.append(chr(code - 0xFEE0))
            continue
        out.append(ch)
    s = "".join(out)
    # 形近字映射仅在纯 ASCII 文本做（防中文/多字节字符误伤）
    return s.translate(_OCR_TRANSLATE) if s.isascii() else s


class March7thVision:
    name = "march7th"

    def __init__(self):
        with _M7_INIT_LOCK:
            saved = os.getcwd()
            try:
                ensure_march7th_env()
                from module.automation import auto
                from module.ocr import ocr
            finally:
                os.chdir(saved)  # 构造完成即恢复（后续截图/OCR 不依赖 cwd）
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
        """OCR 返回 [(text, box), ...]，box 为四点 [(x,y),...] 截图内坐标。

        Bug 155：文本经 normalize_ocr 清洗（全角/形近字归一）。
        """
        import numpy as np
        # crop 仅对 March7th 后台截图有效（前台 mss 降级路径不支持裁剪）
        img, _, _ = self.take_screenshot(crop=crop)
        out = []
        for t in self.ocr.run(np.asarray(img)) or []:
            if isinstance(t, dict) and t.get("txt"):
                out.append((normalize_ocr(t["txt"]), t["box"]))
        return out

    def find_text(self, text, include=True, max_retries=1, crop=None):
        """find_element("文字", "text") → ((left,top),(right,bottom)) 绝对坐标或 None。"""
        return self.auto.find_element(text, "text", max_retries=max_retries,
                                      include=include, crop=crop)

    def find_template(self, path, threshold=0.8, max_retries=1):
        """find_element(图片, "image") → 绝对坐标框或 None。"""
        return self.auto.find_element(path, "image", threshold, max_retries=max_retries)

    def to_absolute(self, norm_x, norm_y):
        """归一化坐标(0-1) → 绝对屏幕坐标（vlm 定位结果消费，执行细节）。

        Bug 71：归一化边界 clamp；Bug 163：round 而非截断。
        """
        img, screenshot_pos, scale = self.take_screenshot()
        left, top, w, h = screenshot_pos
        img_w, img_h = img.size
        norm_x = max(0.0, min(1.0, float(norm_x)))
        norm_y = max(0.0, min(1.0, float(norm_y)))
        return (left + round(norm_x * img_w / (scale or 1)),
                top + round(norm_y * img_h / (scale or 1)))
