"""ActionGuard（Sprint B-2：执行前安全闸门——executor 不相信任何人）。

任何执行必须经过 allow()：
- vision_verified 未确认 → VISION_NOT_VERIFIED（strict 模式）
- vision_confidence < 门槛 → VISION_LOW_CONFIDENCE
- evidence 过期（TTL）→ VISION_EXPIRED（10 秒前看到商店 ≠ 现在可以点）
- 高风险动作（购买/删除/退出）：更严 TTL + 更高置信门槛（双保险）

兼容模式：strict=False 时未验证意图放行（workflow 模板路径——自身带
verify 步骤闭环）；但已验证的意图仍按完整校验。
"""
import time

DEFAULT_MAX_AGE = 3.0          # 证据有效窗口（秒）
HIGH_RISK_MAX_AGE = 1.5        # 高风险动作更严
HIGH_RISK_CONFIDENCE = 0.85    # 高风险动作置信门槛


class ActionGuard:
    def __init__(self, min_confidence=0.75, max_age=DEFAULT_MAX_AGE,
                 strict=False, evidence_store=None):
        self.min_confidence = min_confidence
        self.max_age = max_age
        self.strict = strict        # True：未验证意图直接拒绝
        self.evidence_store = evidence_store  # id → {timestamp, confidence}

    def allow(self, intent):
        """返回 (allowed, reason)。"""
        if not intent.vision_verified:
            if self.strict:
                return False, "VISION_NOT_VERIFIED"
            return True, "OK_LAX"  # 兼容模式（workflow 模板路径）

        high = intent.risk == "high"
        age = self._evidence_age(intent.evidence_id)
        if age is not None and age > (HIGH_RISK_MAX_AGE if high else self.max_age):
            return False, "VISION_EXPIRED"

        threshold = HIGH_RISK_CONFIDENCE if high else self.min_confidence
        if intent.vision_confidence < threshold:
            return False, "VISION_LOW_CONFIDENCE"

        return True, "OK"

    def _evidence_age(self, evidence_id):
        if not evidence_id or self.evidence_store is None:
            return None  # 无证据记录：由 confidence 门槛把关
        ev = self.evidence_store.get(evidence_id)
        if not ev:
            return None
        return time.time() - ev.get("timestamp", time.time())
