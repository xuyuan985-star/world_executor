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

    print("[guard] Case 1-4 + 幻觉风险 全部 PASS")


if __name__ == "__main__":
    main()
