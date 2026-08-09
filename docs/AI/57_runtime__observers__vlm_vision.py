# runtime/observers/vlm_vision.py

```python
import json
import re
import tempfile
import time
from pathlib import Path

from ingest.vlm_client import get_provider


class VLMVisionObserver:
    def __init__(self, provider=None, model=None):
        self.provider = provider or get_provider("qwen")
        self.overwrite_model = model

    def _chat_vision(self, screenshot, system, prompt, max_tokens=1200):
        tmp = None
        if isinstance(screenshot, (str, Path)):
            tmp = None
            image_path = str(screenshot)
        else:
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            screenshot.save(tmp.name, "JPEG", quality=92)
            image_path = tmp.name
        try:
            content = [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{self._b64(image_path)}"}},
                {"type": "text", "text": prompt},
            ]
            messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
            text = self.provider._chat(messages, model=self.overwrite_model, max_tokens=max_tokens, temperature=0)
            return self._parse_json(text)
        finally:
            if tmp:
                Path(tmp.name).unlink(missing_ok=True)

    @staticmethod
    def _b64(path):
        import base64
        return base64.b64encode(Path(path).read_bytes()).decode()

    @staticmethod
    def _parse_json(text):
        if not text:
            return {}
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return {"raw": text[:200]}
        try:
            return json.loads(m.group(0))
        except Exception:
            return {"raw": text[:200]}

    def observe_room(self, screenshot, known_rooms):
        prompt = (
            "这是《崩坏：星穹铁道》游戏画面。根据环境特征判断角色当前所在房间/区域。\n"
            f"候选房间（可能都不匹配）: {json.dumps(known_rooms, ensure_ascii=False)}\n"
            "若画面是地图/UI/加载界面，请如实说明。\n"
            '输出JSON: {"room": "房间id或unknown", "ui_state": "game|map|loading|menu|dialogue|combat", '
            '"confidence": 0~1, "reason": "一句话依据"}'
        )
        return self._chat_vision(
            screenshot,
            "你是黑塔空间站房间判定器，只做观测，不做任何操作建议。",
            prompt,
        )

    def locate_target(self, screenshot, target_desc, expect_bbox=True):
        prompt = (
            f"在画面中寻找目标: {target_desc}\n"
            "区分：实体模型(游戏世界内) vs UI图标(小地图/界面)。只报告实体或明确指出是UI。\n"
            "若找到，给出屏幕中心点坐标（0-1000归一化坐标系，以画面左上为原点）。\n"
            '输出JSON: {"found": true/false, "screen_x": 0-1000, "screen_y": 0-1000, '
            '"is_ui": true/false, "confidence": 0~1, "note": "简短说明"}'
        )
        return self._chat_vision(
            screenshot,
            "你是崩铁目标定位器，只报告目标位置，不给出操作建议。",
            prompt,
        )

    def heading_check(self, screenshot, target_desc):
        prompt = (
            "角色面向判断：\n"
            f"目标: {target_desc}\n"
            "根据第三人称视角推断目标在角色当前视野的方位。\n"
            '输出JSON: {"target_in_view": true/false, "target_side": "center|left|right|behind|unknown", '
            '"confidence": 0~1}'
        )
        return self._chat_vision(
            screenshot,
            "你是镜头朝向判定器，只做观测。",
            prompt,
        )

    def sample_stability(self, capture_fn, observe_fn, samples=3, interval=2.5, min_agree=0.75):
        """时间稳定性采样：连续 samples 帧独立观测，统计一致率。

        capture_fn: () -> PIL.Image 截图
        observe_fn: (image) -> dict 单帧观测（如 self.observe_room / self.locate_target）
        返回: {"samples": n, "stable": bool, "consistency": 0~1, "decision": 主决策值,
               "reads": [逐帧关键值]}
        """
        reads = []
        key = None
        for _ in range(samples):
            shot = capture_fn()
            if shot is None:
                reads.append(None)
                continue
            data = observe_fn(shot)
            if "room" in data:
                key = "room"
            elif "found" in data:
                key = "found"
            else:
                key = key or "value"
            reads.append(data.get(key))
            time.sleep(interval)
        reads = [r for r in reads if r is not None]
        if not reads:
            return {"samples": 0, "stable": False, "consistency": 0.0, "decision": None, "reads": []}
        from collections import Counter
        counts = Counter(repr(r) for r in reads)
        decision, count = counts.most_common(1)[0]
        decision = reads[[repr(r) for r in reads].index(decision)]
        consistency = count / len(reads)
        return {
            "samples": len(reads),
            "stable": consistency >= min_agree,
            "consistency": round(consistency, 2),
            "decision": decision,
            "reads": reads,
        }

```
