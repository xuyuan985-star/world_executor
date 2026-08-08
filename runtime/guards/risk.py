"""Risk Score（Sprint C-3：动作风险量化——为 Policy 提供决策输入）。

风险来源（可解释，简单累加）：
  +50  视觉未确认（observation 未通过/未验证）
  +40  VLM 单独高置信（vlm>0.8 且 ocr<0.3——幻觉特征）
  +30  危险动作（confirm/purchase/delete）
  +10  证据过期（非 null 表示）
"""
DANGEROUS_ACTIONS = {"confirm", "purchase", "delete", "exit", "use_resource"}


def calculate_risk(intent, observation=None, evidence_expired=False):
    """intent + observation → risk score（0~100+）。"""
    risk = 0

    # 视觉未确认
    if observation is None:
        if not getattr(intent, "vision_verified", False):
            risk += 50
    elif not getattr(observation, "accepted", True):
        risk += 50

    # VLM 单独高置信（OCR 弱）——仅当有明确 observation 且已知 OCR 弱时叠加；
    # vision_verified=True 表示已过 VisionGate 双通道交叉（含一致性），不再叠加
    ocr_conf = (getattr(observation, "ocr_confidence", 0.0)
                if observation is not None else 0.0)
    vlm_conf = (getattr(observation, "vlm_confidence", 0.0)
                if observation is not None
                else getattr(intent, "vision_confidence", 0.0))
    if (observation is not None and vlm_conf > 0.8 and ocr_conf < 0.3
            and not getattr(intent, "vision_verified", False)):
        risk += 40

    # 危险动作
    if getattr(intent, "action", None) in DANGEROUS_ACTIONS:
        risk += 30

    # 证据过期
    if evidence_expired:
        risk += 10

    return risk
