"""视觉观察层（第 8 步：OCR + VLM 双通道融合）。

输入：screenshot（或注入 capture_fn 自行取帧）
输出：Observation（fuse_observation 合并双通道）

禁止：Action / Driver / Input——只从画面生成观察结果。
解决 ISSUE-13：单通道高置信幻觉——错误截图 + VLM 猜场景 + 高置信 = 灾难；
双通道交叉验证后置信度才会抬升。
"""
from runtime.observation import Observation


class OCRAdapter:
    """March7th OCR 适配：detect(screenshot) → {"text": [...], "boxes": [...]}。

    统一 ocr.run 的 dict 列表返回（ISSUE-14 结构差异在适配层消化）。
    B-03/B-08：保留 bbox——证据链记录 + 未来 UI 语义区域验证。
    """

    def __init__(self, ocr_engine):
        self.ocr = ocr_engine

    def detect(self, screenshot):
        import numpy as np
        from runtime.drivers.march7th.vision import merge_ocr_lines, normalize_ocr
        raw = np.asarray(screenshot)
        results = []
        for t in self.ocr.run(raw) or []:
            if isinstance(t, dict) and t.get("txt"):
                box = t.get("box")
                results.append((normalize_ocr(str(t["txt"])),
                                list(box) if box is not None else None))
        # 行级合并（m7 块合并适配）：碎片拼行 → join 关键词匹配不断列
        merged = merge_ocr_lines(results)
        out = [m[0] for m in merged]
        boxes = [m[1] for m in merged]
        return {"text": out, "boxes": boxes}


def validate_vlm_output(data, kind="room"):
    """BUG-21：VLM 输出 schema 校验（防模型自由发挥污染决策）。

    kind="room"：observe_room 输出（room/ui_state/confidence）
    kind="locate"：locate_target 输出（found/screen_x/screen_y/confidence）
    返回 (ok, reason)。字段类型不合法/缺失关键字段 → False。
    """
    if not isinstance(data, dict):
        return False, f"vlm_output_not_dict:{type(data).__name__}"
    conf = data.get("confidence")
    if conf is not None and not isinstance(conf, (int, float)):
        return False, f"vlm_confidence_type:{type(conf).__name__}"
    if kind == "locate":
        found = data.get("found")
        if found is not None and not isinstance(found, bool):
            return False, f"vlm_found_type:{type(found).__name__}"
        for k in ("screen_x", "screen_y"):
            v = data.get(k)
            if v is not None and not isinstance(v, (int, float)):
                return False, f"vlm_{k}_type:{type(v).__name__}"
        if found is True and (data.get("screen_x") is None
                              or data.get("screen_y") is None):
            return False, "vlm_locate_missing_xy"
        return True, "ok"
    has_room = data.get("room") is not None
    has_ui = data.get("ui_state") is not None
    if not (has_room or has_ui):
        return False, "vlm_no_semantic_fields"  # 模型答非所问（如 {"answer": ...}）
    for k in ("room", "ui_state"):
        v = data.get(k)
        if v is not None and not isinstance(v, str):
            return False, f"vlm_{k}_type:{type(v).__name__}"
    return True, "ok"


class VLMAdapter:
    """VLM 观察适配：observe(screenshot) → {"room", "ui_state", "confidence"}。

    包装 VLMVisionObserver.observe_room（房间判定 + UI 状态 + 置信度）。
    BUG-34：输出过 schema 校验，非法 → 空结果（走 VLM 弱分支）。
    """

    def __init__(self, vlm, room_ids=None):
        self.vlm = vlm
        self.room_ids = room_ids or []

    def observe(self, screenshot):
        data = self.vlm.observe_room(screenshot, self.room_ids) or {}
        ok, reason = validate_vlm_output(data)
        if not ok:
            data = {"room": None, "ui_state": None, "confidence": 0.0,
                    "schema_error": reason}
        return {"room": data.get("room"),
                "ui_state": data.get("ui_state"),
                "confidence": data.get("confidence", 0.0),
                "schema_error": data.get("schema_error")}


class VisionObserver:
    """统一视觉入口：双通道各自 try 隔离（单通道故障不拖垮观察）。"""

    def __init__(self, ocr=None, vlm=None, capture_fn=None):
        self.ocr = ocr
        self.vlm = vlm
        self.capture_fn = capture_fn  # () -> screenshot；None 时要求显式传入

    def observe(self, screenshot=None) -> Observation:
        if screenshot is None and self.capture_fn is not None:
            try:
                screenshot = self.capture_fn()
            except Exception:
                screenshot = None
        ocr_result = None
        vlm_result = None
        if screenshot is not None and self.ocr is not None:
            try:
                ocr_result = self.ocr.detect(screenshot)
            except Exception:
                ocr_result = None
        if screenshot is not None and self.vlm is not None:
            try:
                vlm_result = self.vlm.observe(screenshot)
            except Exception:
                vlm_result = None
        return fuse_observation(screenshot, ocr_result, vlm_result)


def fuse_observation(screenshot, ocr, vlm) -> Observation:
    """双通道融合（ISSUE-13 核心）：不相信单一来源。

    - 双通道一致（VLM 的 ui_state 出现在 OCR 文本中）→ 置信抬升 min(1, vlm+0.5)
    - 双通道矛盾 → 置信压到 0.3（低置信拒绝行动）
    - 单通道 → 打折（vlm*0.5 / ocr 0.5）
    """
    text = []
    if ocr:
        text.extend(ocr.get("text") or [])
    room = vlm.get("room") if vlm else None
    ui_state = vlm.get("ui_state") if vlm else None
    vlm_conf = (vlm.get("confidence") or 0.0) if vlm else 0.0

    if vlm and ocr and ui_state:
        joined = "".join(text)
        if ui_state in joined:
            confidence = min(1.0, vlm_conf + 0.5)
        else:
            confidence = 0.3  # VLM 说一套、OCR 另一套——拒绝
    elif vlm:
        confidence = vlm_conf * 0.5
    elif ocr:
        confidence = 0.5
    else:
        confidence = 0.0

    source = []
    if ocr:
        source.append("ocr")
    if vlm:
        source.append("vlm")
    return Observation(
        screenshot=screenshot if isinstance(screenshot, str) else None,
        room=room,
        ui_state=ui_state,
        text=text,
        confidence=round(confidence, 3),
        source="+".join(source) or "none",
    )
