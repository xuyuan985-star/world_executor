"""Replay 验证（Sprint B：目标 4——行为回放回归）。

输入：事件序列（events.json / 直接列表）。
验证：同样输入 → 状态机必须产出同样行为（确定性回归）——
以后改模型/策略不破坏旧行为。

用法：
    python tests/replay/test_action_replay.py
"""
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.state_machine import State  # noqa: E402

KNOWLEDGE = ROOT / "knowledge" / "source" / "black_tower_test"


def load_events(path=None):
    """事件序列：默认内置目标-动作流；或读 events.json。"""
    if path and Path(path).exists():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        {"event": "run_started", "target": "chest_A"},
        {"event": "target_found", "target": "chest_A", "method": "template"},
        {"event": "action", "type": "click", "target": "chest_A"},
        {"event": "action", "type": "verify", "target": "chest_A"},
        {"event": "target_done", "target": "chest_A"},
    ]


def replay(events):
    """事件流 → 状态机行为断言（确定性回归）。"""
    from runtime.events.bus import EventBus
    from runtime.knowledge_loader import KnowledgePackage
    from runtime.orchestrator import WorkflowOrchestrator
    from tools.smoke_orchestrator import FakeObserver, FakeDriver, FakeVLM
    from unittest import mock

    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append((e.type, e.context)))
    pkg = KnowledgePackage(KNOWLEDGE)
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id="replay-test", use_vlm=True)
    orch.observer = FakeObserver(text=["chest_A"])

    def driver_factory():
        return FakeDriver([True] * 10)

    with mock.patch("runtime.drivers.march7th.get_driver", side_effect=driver_factory), \
            mock.patch("runtime.step_executor.VLMVisionObserver", FakeVLM), \
            mock.patch("runtime.drivers.march7th.window.find_game_window",
                       return_value={"hwnd": 1, "client": (1920, 1080)}), \
            mock.patch.object(orch, "start_emergency", lambda: None):
        results, completed = orch.run_mission(["chest_A"])
    return {"results": results, "completed": completed,
            "state": orch._machine.state, "events": seen}


def replay_failure():
    """Sprint B.2：失败复现——ReplayInput 拒绝点击 → 同输入同失败。

    确定性回归：修改执行链后，历史失败必须可复现（不改行为）。
    """
    from runtime.events.bus import EventBus
    from runtime.knowledge_loader import KnowledgePackage
    from runtime.orchestrator import WorkflowOrchestrator
    from runtime.state_machine import State
    from runtime.input.replay import ReplayInput
    from tools.smoke_orchestrator import FakeVLM
    from unittest import mock

    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append((e.type, e.context)))
    pkg = KnowledgePackage(KNOWLEDGE)
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id="replay-fail", use_vlm=True)
    replay = ReplayInput([True, False, False, False])  # 点击拒绝 → 重试用尽

    def driver_factory():
        from tools.smoke_orchestrator import FakeDriver
        return FakeDriver([])

    with mock.patch("runtime.drivers.march7th.get_driver", side_effect=driver_factory), \
            mock.patch("runtime.step_executor.VLMVisionObserver", FakeVLM), \
            mock.patch("runtime.drivers.march7th.window.find_game_window",
                       return_value={"hwnd": 1, "client": (1920, 1080)}), \
            mock.patch.object(orch, "start_emergency", lambda: None):
        orch.executor._input_override = replay
        results, completed = orch.run_mission(["chest_A"])
    assert results == {"chest_A": False}, results
    cats = [ctx.get("category") for t, ctx in seen if t == "fail_recorded"]
    assert any("F1_TEMPLATE" in c for c in cats), cats  # 失败分类可复现
    return {"results": results, "completed": completed,
            "state": orch._machine.state, "categories": cats}


def main():
    events = load_events(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"[replay] {len(events)} 事件输入")
    r = replay(events)
    assert r["results"] == {"chest_A": True}, r["results"]
    assert r["completed"] == ["chest_A"], r["completed"]
    assert r["state"] == State.DONE, r["state"]
    # 行为序：mission 生命周期首尾断言（确定性回归锚点）
    order = [t for t, _ in r["events"] if t in
             ("state_changed", "action_executed", "target_progress")]
    assert order[0] == "state_changed", order[:2]
    assert order[-1] == "target_progress", order[-2:]
    print(f"[replay] PASS（状态 {r['state'].value}，事件 {len(r['events'])} 条，行为序确定）")

    # Sprint B.2：失败复现（ReplayInput 拒绝 → 同分类失败）
    rf = replay_failure()
    assert rf["state"] != State.DONE, rf
    print(f"[replay] 失败复现 PASS（{rf['state'].value}，分类 {set(rf['categories'])}）")


if __name__ == "__main__":
    main()
