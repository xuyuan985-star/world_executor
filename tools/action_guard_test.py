"""ActionGuard 测试（Sprint C-10：执行前最后一道保险）。

用法：python tools/action_guard_test.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runtime.guards.action_guard import ActionGuard  # noqa: E402
from runtime.guards.risk import calculate_risk  # noqa: E402
from runtime.guards.policy import allowed, risk_limit  # noqa: E402
from runtime.action_intent import ActionIntent, ActionMethod  # noqa: E402


def make_intent(action, target="shop_button", vision_verified=False,
                vision_confidence=0.0, evidence_id=None):
    return ActionIntent(action=action, target=target,
                        method=ActionMethod.TEXT.value,
                        vision_verified=vision_verified,
                        vision_confidence=vision_confidence,
                        evidence_id=evidence_id)


def main():
    guard = ActionGuard(strict=True)

    # Case 1：正常点击——视觉已确认高置信 → PASS risk 低
    intent = make_intent("interact", vision_verified=True, vision_confidence=0.91,
                         evidence_id="evid_x")
    r = guard.check(intent)
    assert r["allowed"], r
    assert r["risk"] == 0, r  # 无 observation、已确认 → 不加风险

    # Case 2：VLM 幻觉——未验证 + strict → BLOCK VISION_NOT_VERIFIED
    intent2 = make_intent("interact")
    r2 = guard.check(intent2)
    assert not r2["allowed"], r2
    assert r2["reason"] == "VISION_NOT_VERIFIED", r2

    # Case 3：购买动作——即使低风险场景也需极低风险
    intent3 = make_intent("purchase", vision_verified=True, vision_confidence=0.9)
    # 未带 observation：risk = 0 + 危险动作 +30 = 30 > 10 → BLOCK
    r3 = guard.check(intent3)
    assert not r3["allowed"], r3
    assert r3["reason"] == "ACTION_RISK_HIGH", r3
    assert risk_limit("purchase") == 10
    assert not allowed("purchase", 30)
    assert allowed("click", 20)

    # Case 4：点击成功但 UI 未变 → ActionVerifier 语义（verify 步骤闭环，此处验证 risk 函数）
    class Obs:
        accepted = True
        ocr_confidence = 0.85
        vlm_confidence = 0.9
    risk_safe = calculate_risk(make_intent("interact", vision_verified=True), Obs())
    assert risk_safe == 0, risk_safe  # 双通道确认 → 零风险

    # 附加：VLM 单独高置信幻觉风险（observation 明确 OCR 弱 + 未过 gate）
    class ObsFake:
        accepted = True
        ocr_confidence = 0.1
        vlm_confidence = 0.95
    risk_fake = calculate_risk(make_intent("interact", vision_verified=False), ObsFake())
    assert risk_fake == 40, risk_fake  # vlm>0.8 且 ocr<0.3 → +40
    # 已过 gate（vision_verified）→ 不再叠加幻觉风险
    risk_verified = calculate_risk(make_intent("interact", vision_verified=True,
                                               vision_confidence=0.95), ObsFake())
    assert risk_verified == 0, risk_verified

    # Sprint B.2：ActionIntent 不得携带坐标（架构冻结——intent 字段白名单断言）
    forbidden = {"x", "y", "px", "py", "screen_x", "screen_y", "coordinate", "bbox"}
    fields = set(make_intent("interact").__dataclass_fields__.keys())
    assert not (fields & forbidden), f"ActionIntent 出现坐标字段: {fields & forbidden}"
    print("[guard] ActionIntent 字段白名单（无坐标）PASS")

    # Sprint C（BUG-54）：risk 等级策略
    def intent_risk(risk, conf=0.95):
        return make_intent("interact", vision_verified=True, vision_confidence=conf) \
            .__class__(action="interact", target="shop_button",
                       method=ActionMethod.TEXT.value,
                       vision_verified=True, vision_confidence=conf, risk=risk)
    from runtime.guards.policy import confidence_for, is_critical
    assert confidence_for("high") == 0.85 and confidence_for("low") == 0.0
    assert is_critical("critical") and not is_critical("high")
    # high 等级 + 0.8 置信（低于 0.85）→ 拒绝
    r_high = guard.check(intent_risk("high", 0.8))
    assert not r_high["allowed"] and r_high["reason"] == "VISION_LOW_CONFIDENCE", r_high
    # high 等级 + 0.9 置信 → 放行
    assert guard.check(intent_risk("high", 0.9))["allowed"]
    # critical → 拒绝自动执行
    assert not guard.check(intent_risk("critical"))["allowed"]
    print("[guard] risk 四级策略（high 提置信/critical 人工确认）PASS")

    # #24：错误成功测试——失败 InputResult 不得被转成 success=True
    from runtime.input.base import InputResult
    from runtime.step_executor import RealExecutor
    from unittest import mock
    from pathlib import Path
    from runtime.knowledge_loader import KnowledgePackage
    pkg = KnowledgePackage(Path(__file__).resolve().parent.parent /
                           "knowledge" / "source" / "black_tower_test")
    ex = RealExecutor(pkg, use_vlm=False)
    with mock.patch("runtime.drivers.march7th.get_driver"):
        r_fail = ex._to_result(
            make_intent("interact", vision_verified=True, vision_confidence=0.9),
            InputResult(success=False, action="click", backend="fake",
                        error="click_element_failed"))
    assert r_fail.success is False, "失败 InputResult 被误转为成功！"
    assert r_fail.retryable is True, r_fail  # transient 可重试
    print("[guard] 错误成功防护（失败不被当成功）PASS")

    print("[guard] Case 1-4 + 幻觉风险 全部 PASS")


if __name__ == "__main__":
    main()
