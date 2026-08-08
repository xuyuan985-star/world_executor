"""VisionGate（Sprint B：内容级决策门——"这张图能否用于决策"）。

FrameValidator 管结构（黑屏/黑边/白屏）；VisionGate 管内容——
错窗口/错画面时 VLM 会一本正经胡说（ISSUE-13），用多信号交叉确认：

PASS 需满足至少 2 个信号：
  1. OCR 命中游戏关键词（UID/菜单/经济词……）
  2. VLM 报游戏状态（ui_state ∈ 游戏态 或 room 已知）
  3. 帧结构质量 ok（FrameValidator）

不足 2 信号 → VISION_UNTRUSTED：禁止点击（Planner 门按低置信拒绝）。
"""
GAME_OCR_KEYWORDS = (
    "UID", "信用点", "开拓", "跃迁", "背包", "商店", "任务",
    "队伍", "星穹", "模拟宇宙", "委托", "遗器", "光锥",
)

GAME_UI_STATES = {"game", "menu", "map", "dialogue"}


class VisionGate:
    """内容可信度门：validate(frame_quality, ocr_texts, vlm) → {valid, reason, signals}。"""

    def __init__(self, ocr_keywords=GAME_OCR_KEYWORDS,
                 ui_states=GAME_UI_STATES, min_signals=2):
        self.ocr_keywords = ocr_keywords
        self.ui_states = ui_states
        self.min_signals = min_signals

    def validate(self, frame_quality=None, ocr_texts=None, vlm=None):
        signals = []
        reasons = []

        joined = "".join(ocr_texts or [])
        if any(k in joined for k in self.ocr_keywords):
            signals.append("ocr_game_keyword")
        elif ocr_texts:
            reasons.append("OCR 无游戏关键词")

        ui_state = (vlm or {}).get("ui_state")
        room = (vlm or {}).get("room")
        vlm_conf = (vlm or {}).get("confidence") or 0.0
        if ui_state in self.ui_states or (room and room != "unknown"):
            signals.append("vlm_game_state")
        elif vlm:
            reasons.append("VLM 未确认游戏状态")

        if frame_quality is None or frame_quality == "ok":
            signals.append("frame_quality_ok")
        else:
            reasons.append(f"帧质量 {frame_quality}")

        valid = len(signals) >= self.min_signals
        return {
            "valid": valid,
            "reason": "; ".join(reasons) if reasons else "trusted",
            "signals": signals,
            "confidence": round(min(1.0, 0.4 + 0.3 * len(signals)), 2),
        }
