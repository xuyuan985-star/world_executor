"""Policy（Sprint C：动作允许规则——按动作类型+风险等级差异化门槛）。

点击：允许一定误差（风险 < 30）
购买/删除/确认：必须极低风险（风险 < 10）
其他（move/verify/wait）：宽松（风险 < 60）

BUG-54：intent.risk 四级（low/medium/high/critical）→ 置信要求映射：
  LOW     一次视觉确认（min_confidence）
  MEDIUM  双通道（默认门槛）
  HIGH    双通道 + 更高置信（0.85）
  CRITICAL人工确认（guard 拒绝自动执行）
"""
MAX_CLICK_RISK = 30
MAX_DANGEROUS_RISK = 10
MAX_SAFE_RISK = 60

# BUG-54：risk 等级 → 最小置信要求（None = 不额外要求）
RISK_CONFIDENCE = {
    "low": 0.0,
    "medium": 0.75,
    "high": 0.85,
    "critical": 1.01,  # 不可自动达成 → 人工确认
}

VALID_RISK_LEVELS = ("low", "medium", "high", "critical")


def confidence_for(risk_level):
    return RISK_CONFIDENCE.get(risk_level, 0.75)


def is_critical(risk_level):
    return risk_level == "critical"


def allowed(action, risk):
    if action in ("purchase", "delete", "confirm", "exit", "use_resource"):
        return risk < MAX_DANGEROUS_RISK
    if action == "click":
        return risk < MAX_CLICK_RISK
    return risk < MAX_SAFE_RISK


def risk_limit(action):
    if action in ("purchase", "delete", "confirm", "exit", "use_resource"):
        return MAX_DANGEROUS_RISK
    if action == "click":
        return MAX_CLICK_RISK
    return MAX_SAFE_RISK
