"""三大策略测试（遇怪/未解锁/机关——审查反思落地）。

Test 1：遇怪 auto——战斗词→按自动战斗键→结算→继续
Test 2：遇怪 kill——战斗词→按战技键（秒杀角色）→结算
Test 3：未解锁——portal 后 OCR 含"未解锁"→ map_locked 失败（不重试）
Test 4：机关——interact 前 OCR 含"机关"→ requires_mechanism 跳过
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from unittest import mock  # noqa: E402


class SeqVision:
    """按调用序返回 OCR 文本序列。"""

    def __init__(self, seq):
        self.seq = list(seq)
        self.calls = 0

    def ocr_lines(self, crop=(0, 0, 1, 1)):
        self.calls += 1
        if self.seq:
            t = self.seq.pop(0)
            return [(t, [[0, 0, 10, 10]])]
        return []


class FakeIn:
    name = "fake"

    def __init__(self):
        self.keys = []

    def press_key(self, key, wait_time=0.2):
        self.keys.append((key, wait_time))
        return type("R", (), {"success": True, "detail": {}})()


def make_orch(strategy="auto"):
    from runtime.orchestrator import WorkflowOrchestrator
    orch = object.__new__(WorkflowOrchestrator)
    orch.battle_strategy = strategy
    orch._stop_check = None
    orch._monitor = None
    orch._watchdog = None
    orch._bus = None
    orch._executor = mock.MagicMock()
    orch._executor.driver.vision = None
    orch._emit = lambda *a, **k: None
    orch._interruptible_wait = lambda s: True
    orch._interrupted = lambda t: None
    return orch


def main():
    # Test 1：auto 策略——战斗→按 v→结算
    orch = make_orch("auto")
    orch._executor.driver.vision = SeqVision(["回合 1", "胜利"])
    orch._executor.input = FakeIn()
    ok = orch._handle_battle_if_needed(max_rounds=4)
    assert ok, "战斗应解决"
    assert any(k == "v" for k, _ in orch._executor.input.keys), \
        orch._executor.input.keys
    print(f"[strategies] Test 1 PASS（auto：按 {orch._executor.input.keys[0][0]} 自动战斗→结算）")

    # Test 2：kill 策略——战斗→按 e（战技）秒杀
    orch2 = make_orch("kill")
    orch2._executor.driver.vision = SeqVision(["波次 1", ""])
    orch2._executor.input = FakeIn()
    ok2 = orch2._handle_battle_if_needed(max_rounds=4)
    assert ok2
    assert any(k == "e" for k, _ in orch2._executor.input.keys), \
        orch2._executor.input.keys
    print(f"[strategies] Test 2 PASS（kill：按 {orch2._executor.input.keys[0][0]} 战技秒杀）")

    # Test 3：未解锁检测
    orch3 = make_orch()
    orch3._executor.driver.vision = SeqVision(["该区域尚未解锁"])
    hint = orch3._check_map_locked()
    assert hint == "尚未解锁", hint
    print("[strategies] Test 3 PASS（未解锁提示词检测）")

    # Test 4：机关检测
    orch4 = make_orch()
    orch4._executor.driver.vision = SeqVision(["需要启动机关"])
    mech = orch4._check_mechanism()
    assert mech == "机关", mech
    print("[strategies] Test 4 PASS（机关提示词检测）")

    print("[strategies] Test 1-4 全部 PASS")


if __name__ == "__main__":
    main()
