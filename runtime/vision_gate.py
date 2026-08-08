"""VisionGate（Sprint B：决策前可信度控制——"证据是否足以相信这是目标画面"）。

分层：
  FrameValidator（结构：黑屏/黑边/白屏/静态/尺寸）→ VisionGate（内容：双通道评分）

评分（可解释，不上复杂模型）：
  score = 0.45*ocr_score + 0.45*vlm_score + 0.10*consistency
  - ocr_score：游戏正向词命中比例，负向词（IDE/浏览器/桌面）命中直接压制
  - vlm_score：ui_state ∈ 游戏态 或 room 已知 → confidence；否则打折
  - consistency：VLM 状态关键词出现在 OCR 文本 → 1（OCR+VLM 互相印证）；否则 0

拒绝：score < threshold → VISION_UNTRUSTED（禁止点击）。
VLM 缺失：降档阈值（OCR-only 低风险动作可放行，如观察/等待）。
"""
from dataclasses import dataclass, field


GAME_OCR_KEYWORDS = (
    "UID", "信用点", "开拓", "跃迁", "背包", "商店", "任务",
    "队伍", "星穹", "模拟宇宙", "委托", "遗器", "光锥",
    "购买", "商品", "兑换", "确认", "返回",
)

# 负向词：命中说明画面不是游戏（IDE/浏览器/桌面/终端）
NON_GAME_KEYWORDS = (
    "Visual Studio", "Python", "terminal", "Edge", "chrome",
    "浏览器", "代码", "搜索", "Git", "桌面", "终端", "PowerShell",
)

GAME_UI_STATES = {"game", "menu", "map", "dialogue", "shop"}

# VLM 场景标签 → OCR 中文同义词（中英一致性判定）
SCENE_ALIASES = {
    "shop": ("商店", "购买", "商品"),
    "menu": ("菜单", "设置", "主界面"),
    "map": ("地图",),
    "dialogue": ("对话", "任务", "对话选项"),
    "game": ("游戏",),
}

OCR_WEIGHT = 0.45
VLM_WEIGHT = 0.45
CONSISTENCY_WEIGHT = 0.10


@dataclass
class OCREvidence:
    texts: list = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class VLMEvidence:
    scene: str = None      # ui_state（game/menu/...）
    room: str = None
    confidence: float = 0.0


@dataclass
class VisionEvidence:
    ocr: OCREvidence = field(default_factory=OCREvidence)
    vlm: VLMEvidence = field(default_factory=VLMEvidence)
    frame_quality: str = "ok"   # FrameValidator 输出


class VisionGate:
    """双通道评分门：evaluate(evidence) → {allowed, score, reason, signals}。"""

    def __init__(self, threshold=0.75, ocr_only_threshold=0.5,
                 ocr_keywords=GAME_OCR_KEYWORDS, non_game_keywords=NON_GAME_KEYWORDS,
                 ui_states=GAME_UI_STATES, scene_aliases=SCENE_ALIASES):
        self.threshold = threshold
        self.ocr_only_threshold = ocr_only_threshold  # VLM 缺失时降档（低风险动作）
        self.ocr_keywords = ocr_keywords
        self.non_game_keywords = non_game_keywords
        self.ui_states = ui_states
        self.scene_aliases = scene_aliases

    def evaluate(self, evidence: VisionEvidence):
        signals = []
        reasons = []
        joined = "".join(evidence.ocr.texts or [])

        # OCR 评分：正向命中 + 负向压制（单关键词命中即视为有游戏文本信号）
        ocr_hits = sum(1 for k in self.ocr_keywords if k in joined)
        non_game = any(k in joined for k in self.non_game_keywords)
        ocr_score = min(1.0, ocr_hits)
        if ocr_hits:
            signals.append("ocr_game_keyword")
        if non_game:
            ocr_score *= 0.2  # 负向命中 → 压制
            reasons.append("OCR 命中非游戏词")
        if not ocr_hits and evidence.ocr.texts:
            reasons.append("OCR 无游戏关键词")

        # VLM 评分
        vlm = evidence.vlm
        vlm_ok = vlm.scene in self.ui_states or (vlm.room and vlm.room != "unknown")
        vlm_score = (vlm.confidence or 0.0) if vlm_ok else (vlm.confidence or 0.0) * 0.3
        if vlm_ok:
            signals.append("vlm_game_state")
        else:
            reasons.append("VLM 未确认游戏状态")

        # 一致性：VLM 场景（含中文同义词）出现在 OCR 文本 → 互相印证
        consistency = 0.0
        aliases = self.scene_aliases.get(vlm.scene or "", ())
        if any(a in joined for a in aliases) or (vlm.scene and vlm.scene in joined):
            consistency = 1.0
            signals.append("ocr_vlm_agreement")
        elif vlm.room and vlm.room != "unknown" and vlm.room in joined:
            consistency = 1.0
            signals.append("ocr_vlm_agreement")
        if not consistency:
            reasons.append("OCR/VLM 不一致")

        if evidence.frame_quality is None or evidence.frame_quality == "ok":
            signals.append("frame_quality_ok")
        else:
            reasons.append(f"帧质量 {evidence.frame_quality}")

        # VLM 通道存在性：scene/room 有效，或置信度>0（存在但弱=走双通道评分）
        has_vlm = bool(vlm.scene or vlm.room or (vlm.confidence or 0.0) > 0)
        if has_vlm:
            score = OCR_WEIGHT * ocr_score + VLM_WEIGHT * vlm_score \
                + CONSISTENCY_WEIGHT * consistency
            threshold = self.threshold
        else:
            # VLM 缺失：OCR-only 降档（允许低风险动作）
            score = OCR_WEIGHT * ocr_score / OCR_WEIGHT * 0.55  # 近似归一
            threshold = self.ocr_only_threshold
        # 帧质量惩罚：结构异常（黑屏/黑边/白屏/尺寸）→ 直接压分
        if evidence.frame_quality not in (None, "ok"):
            score *= 0.5
            reasons.append(f"帧质量 {evidence.frame_quality}")
        score = round(min(1.0, max(0.0, score)), 3)

        allowed = score >= threshold

        # Sprint B-6 融合语义：三元判定（ACCEPT / OBSERVE / REJECT）
        #   OCR高 + VLM高 → accept（confirmed）
        #   OCR高 + VLM低 → observe（可观察不执行，等待重试）
        #   VLM高 + OCR无 → reject（vlm_only——幻觉特征）
        #   都弱          → reject
        mode = "accept" if allowed else "reject"
        if not allowed and ocr_hits and not vlm_ok:
            mode = "observe"
        elif not allowed and not ocr_hits and vlm_ok:
            mode = "reject"  # vlm_only

        return {
            "allowed": allowed,
            "mode": mode,
            "score": score,
            "threshold": threshold,
            "reason": "vision verified" if allowed
                      else "; ".join(reasons) or "low confidence",
            "signals": signals,
        }

    def validate(self, frame_quality=None, ocr_texts=None, vlm=None):
        """兼容旧接口（observe_act 第 26 轮接入点）：内部转 evidence。"""
        ev = VisionEvidence(
            ocr=OCREvidence(texts=list(ocr_texts or [])),
            vlm=VLMEvidence(scene=(vlm or {}).get("ui_state"),
                            room=(vlm or {}).get("room"),
                            confidence=(vlm or {}).get("confidence") or 0.0),
            frame_quality=frame_quality,
        )
        d = self.evaluate(ev)
        return {"valid": d["allowed"], "reason": d["reason"],
                "signals": d["signals"], "confidence": d["score"]}
