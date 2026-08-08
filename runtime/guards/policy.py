"""Policy（Sprint C-4：动作允许规则——按动作类型差异化门槛）。

点击：允许一定误差（风险 < 30）
购买/删除/确认：必须极低风险（风险 < 10）
其他（move/verify/wait）：宽松（风险 < 60）
"""
MAX_CLICK_RISK = 30
MAX_DANGEROUS_RISK = 10
MAX_SAFE_RISK = 60


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
