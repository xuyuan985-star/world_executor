"""界面归一化测试（March7th Screen._handle_autotry 适配）。

Test 1：OCR 命中战斗词（波次/回合）→ ESC 退出 → 第二轮干净 → 任务正常跑
Test 2：OCR 持续命中战斗词 6 轮 → 超轮次 → crashed（不裸跑）
Test 3：mock 无 ocr_lines（FakeVision 原样）→ 放行不阻断
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.events.bus import EventBus  # noqa: E402
from runtime.knowledge_loader import KnowledgePackage  # noqa: E402
from runtime.orchestrator import WorkflowOrchestrator  # noqa: E402
from tools.smoke_orchestrator import FakeInput, FakeObserver, FakeVLM  # noqa: E402
from unittest import mock  # noqa: E402

KNOWLEDGE = ROOT / "knowledge" / "source" / "black_tower_test"


class OcrSequence:
    """按调用次数返回 OCR 文本序列的 FakeVision 包装。"""

    def __init__(self, vision, sequences):
        self._vision = vision
        self._seqs = list(sequences)
        self.calls = 0

    def ocr_lines(self, crop=(0, 0, 1, 1)):
        self.calls += 1
        if self._seqs:
            seq = self._seqs.pop(0)
            if isinstance(seq, str):
                return [(seq, [[0, 0, 10, 10]])]
            return [(t, [[0, 0, 10, 10]]) for t in seq]
        return []

    def __getattr__(self, name):
        return getattr(self._vision, name)


def run(target_id, ocr_sequences, clicks):
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append((e.type, e.context)))
    pkg = KnowledgePackage(KNOWLEDGE)
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id="ready-test",
                                use_vlm=True)
    orch.foreground_check = False
    orch.observer = FakeObserver(text=["chest_A"])

    fake_input = FakeInput(clicks, click_result=True)

    def driver_factory():
        from tools.smoke_orchestrator import FakeDriver
        return FakeDriver([])

    wrapper = None

    def patch_driver():
        nonlocal wrapper
        from tools.smoke_orchestrator import FakeDriver
        return FakeDriver([])

    with mock.patch("runtime.drivers.march7th.get_driver",
                    side_effect=patch_driver), \
            mock.patch("runtime.step_executor.VLMVisionObserver", FakeVLM), \
            mock.patch("runtime.drivers.march7th.window.find_game_window",
                       return_value={"hwnd": 1, "client": (1920, 1080)}), \
            mock.patch.object(orch, "start_emergency", lambda: None):
        orch.executor._input_override = fake_input
        # 注入 OCR 序列到 driver.vision（按调用轮次切换文本）
        vision = orch.executor.driver.vision
        if ocr_sequences is not None:
            wrapper = OcrSequence(vision, ocr_sequences)
            orch.executor._driver.vision = wrapper
            orch.executor.driver.vision = wrapper
        try:
            results, completed = orch.run_mission([target_id])
        except RuntimeError as e:
            # 真实链路：RuntimeAPI.runner 会转 crashed——测试直接捕获
            return {"crashed": str(e), "events": seen,
                    "ocr_calls": getattr(wrapper, "calls", None)}
    return {"results": results, "completed": completed,
            "state": orch._machine.state, "events": seen,
            "ocr_calls": getattr(wrapper, "calls", None),
            "presses": fake_input.clicks}


def main():
    # Test 1：战斗词 → ESC → 干净 → 任务正常（模板命中）
    r1 = run("chest_A", ["波次 1", ""], [True] * 6)
    assert r1["results"]["chest_A"] is True, r1["events"]
    exit_evt = [c for t, c in r1["events"] if t == "state_changed"
                and c.get("action") == "ready_battle"]
    ready = [c for t, c in r1["events"] if t == "state_changed"
             and c.get("action") == "ready_ok"]
    assert exit_evt, f"应识别战斗词并 ESC 退出: {r1['events']}"
    assert ready, r1["events"]
    print(f"[ready] Test 1 PASS（战斗词→ESC×{len(exit_evt)}→就绪→任务成功）")

    # Test 2：持续战斗词 6 轮 → 超时 → crashed（RuntimeError 由 runner 转 crashed）
    r2 = run("chest_A", ["波次"] * 6, [True] * 6)
    assert "crashed" in r2 and "未就绪" in r2["crashed"], r2
    assert r2["ocr_calls"] == 6, r2["ocr_calls"]
    print("[ready] Test 2 PASS（持续战斗词→6 轮→中止，不在错误界面裸跑）")

    # Test 3：无 ocr_lines（原始 FakeVision）→ 放行
    r3 = run("chest_A", None, [True] * 6)
    assert r3["results"]["chest_A"] is True, r3["events"]
    print("[ready] Test 3 PASS（无 OCR 能力 → 放行不阻断）")

    print("[ready] Test 1-3 全部 PASS")


if __name__ == "__main__":
    main()
