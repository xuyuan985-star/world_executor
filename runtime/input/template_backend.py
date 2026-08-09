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

    # 隐藏 Bug 审查：43 级 → 21 级（步长 0.1）——1440p 降采样后约 1s，
    # 43 级对 0.05 步长收益极低（相邻尺度匹配结果几乎相同）
    SCALES = np.round(np.arange(0.4, 2.6, 0.1), 2)

    def __init__(self, threshold=0.60, backend=None):
        self.threshold = threshold
        self.backend = backend or Win32Backend()
        self.last_match_ms = None  # Bug 157：最近一次匹配耗时（ms）

    def _screenshot(self):
        import mss
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
        # mss 新版本 shot.rgb 为 RGB bytes（无 alpha）
        return np.frombuffer(shot.rgb, dtype=np.uint8).reshape(
            shot.height, shot.width, 3)[:, :, ::-1]

    def _load_template(self, template_path):
        """Bug 336：模板加载校验（空图/损坏 → 明确错误，不崩 matcher）。

        BUG-077：语义完整性——若知识包带 templates_manifest.json（sha256 清单），
        校验模板未被替换/篡改（文件被换内容但保留文件名 → false positive 源）。
        """
        t = cv2.imread(template_path)
        if t is None:
            raise ValueError(f"模板读取失败: {template_path}")
        h, w = t.shape[:2]
        if h < 10 or w < 10:
            raise ValueError(f"模板尺寸过小 {w}x{h}: {template_path}")
        self._verify_manifest_hash(template_path)
        return t

    def _verify_manifest_hash(self, template_path):
        """BUG-077：对照 templates_manifest.json 校验 sha256（manifest 存在时）。"""
        import hashlib
        from pathlib import Path
        try:
            tpl = Path(template_path)
            manifest = tpl.parent / "templates_manifest.json"
            if not manifest.exists():
                return  # 无清单 = 未启用完整性校验（兼容旧知识包）
            import json
            hashes = json.loads(manifest.read_text(encoding="utf-8")).get("hashes", {})
            expected = hashes.get(tpl.name)
            if expected is None:
                return  # 该模板未登记（新模板，未重新生成清单）
            actual = hashlib.sha256(tpl.read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(
                    f"模板哈希不匹配（文件被替换?）: {tpl.name}")
        except ValueError:
            raise
        except Exception:
            pass  # 清单损坏/不可读——不阻断匹配（降级为无校验）

    def locate(self, template_path):
        """返回 (best_val, cx, cy) 屏幕绝对中心坐标；未命中返回 None。

        Bug 156：多尺度结果即隐式 NMS——只取全局最高分单点（同一目标不重复框）。
        审查 P0：中心偏移用【命中尺度的缩放尺寸】算。
        隐藏 Bug 审查：1440p 全屏 × 43 级多尺度实测 15.7s——每点击前卡 16 秒。
        降采样到 1280 宽工作空间匹配（坐标换算回全屏）——耗时 <1.5s。
        """
        import time
        t0 = time.time()
        t = self._load_template(template_path)
        screen = self._screenshot()
        sh, sw = screen.shape[:2]
        # 降采样：工作空间固定 1280 宽（模板源自 1280 帧——1:1 尺度空间）
        work_scale = 1280.0 / sw if sw > 1280 else 1.0
        if work_scale < 1.0:
            work = cv2.resize(screen, (1280, int(sh * work_scale)),
                              interpolation=cv2.INTER_AREA)
        else:
            work = screen
        wh, ww = work.shape[:2]
        best = (0.0, 0, 0, 0.0)  # (val, x, y, scale)
        try:
            for scale in self.SCALES:
                th = cv2.resize(t, None, fx=scale, fy=scale,
                                interpolation=cv2.INTER_AREA)
                if th.shape[0] >= wh or th.shape[1] >= ww:
                    continue
                res = cv2.matchTemplate(work, th, cv2.TM_CCOEFF_NORMED)
                _, mv, _, ml = cv2.minMaxLoc(res)
                if mv > best[0]:
                    best = (mv, ml[0], ml[1], scale)
        except cv2.error as e:
            # Bug 337：OpenCV 失败显式处理（不静默吞/不裸崩）
            raise RuntimeError(f"模板匹配 OpenCV 错误: {e}") from e
        val, x, y, best_scale = best
        if val < self.threshold:
            return None
        # 工作空间坐标 → 全屏坐标（点击用绝对屏幕坐标）
        if work_scale < 1.0:
            x = int(x / work_scale)
            y = int(y / work_scale)
        # 用命中尺度的缩放模板尺寸算中心
        th_w = int(t.shape[1] * best_scale / work_scale)
        th_h = int(t.shape[0] * best_scale / work_scale)
        # Bug 157：匹配耗时记录（定位哪一步慢）
        self.last_match_ms = round((time.time() - t0) * 1000, 1)
        return val, x + th_w // 2, y + th_h // 2

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
