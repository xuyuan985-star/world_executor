"""实体坐标兜底测试（March7th 路线机制适配）。

背景：30 个真点位模板是视频帧整帧截图——当前画面匹配分数实测全 <0.54
（阈值 0.6/0.8 全不中）→ interact 必失败 → 任务"自动结束"。
修复：模板未命中 → 按 chests.json 归一化坐标兜底点击（m7 的固定坐标路线）。

Test 1：模板失败 + 实体有坐标 → 坐标点击 → 目标 PASS
Test 2：模板失败 + 实体无坐标（chest_A）→ 无兜底 → 目标失败（F1_TEMPLATE）
Test 3：模板成功 → 不触发兜底（模板优先）
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from runtime.events.bus import EventBus  # noqa: E402
from runtime.knowledge_loader import KnowledgePackage  # noqa: E402
from runtime.orchestrator import WorkflowOrchestrator  # noqa: E402
from runtime.state_machine import State  # noqa: E402
from tools.smoke_orchestrator import FakeInput, FakeObserver, FakeVLM  # noqa: E402
from unittest import mock  # noqa: E402

KNOWLEDGE = ROOT / "knowledge" / "source" / "black_tower_test"


def run_target(target_id, clicks):
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append((e.type, e.context)))
    pkg = KnowledgePackage(KNOWLEDGE)
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id="pos-fallback",
                                use_vlm=True)
    orch.foreground_check = False
    orch.observer = FakeObserver(text=["chest_A"])

    fake_input = FakeInput(clicks, click_result=True)

    def driver_factory():
        from tools.smoke_orchestrator import FakeDriver
        return FakeDriver([])

    with mock.patch("runtime.drivers.march7th.get_driver", side_effect=driver_factory), \
            mock.patch("runtime.step_executor.VLMVisionObserver", FakeVLM), \
            mock.patch("runtime.drivers.march7th.window.find_game_window",
                       return_value={"hwnd": 1, "client": (1920, 1080)}), \
            mock.patch.object(orch, "start_emergency", lambda: None):
        orch.executor._input_override = fake_input
        results, completed = orch.run_mission([target_id])
    return {"results": results, "completed": completed,
            "state": orch._machine.state, "clicks": fake_input.clicks,
            "events": seen}


def main():
    # Test 1：真点位模板失败 → 坐标兜底 → 成功（0.451,0.562 → 865,606）
    r1 = run_target("herta_space_station_base_zone_0006_87d3", [])
    assert r1["results"]["herta_space_station_base_zone_0006_87d3"] is True, r1["events"]
    fallback = [c for c in r1["clicks"] if isinstance(c[0], (int, float))]
    assert fallback, f"无坐标兜底点击: {r1['clicks']}"
    x, y = fallback[0]
    assert abs(x - 0.451 * 1920) <= 1 and abs(y - 0.562 * 1080) <= 1, (x, y)
    # 帧模板 verify 恒不中 → 应留 verify_degraded 证据（不假成功不静默）
    deg = [c for t, c in r1["events"] if t == "verify_degraded"]
    assert deg, r1["events"]
    assert deg[0]["template"] == "herta_space_station_base_zone_0006_87d3.png", deg
    print(f"[pos-fallback] Test 1 PASS（模板失败→坐标点击 ({x},{y})→目标成功，"
          f"verify 降级证据留档 {len(deg)} 条）")

    # Test 2：chest_A 无坐标 → 无兜底 → 失败（F1_TEMPLATE 分类）
    r2 = run_target("chest_A", [])
    assert r2["results"]["chest_A"] is False, r2["events"]
    cats = [c.get("category") for t, c in r2["events"] if t == "fail_recorded"]
    assert any("F1_TEMPLATE" in c for c in cats), cats
    print(f"[pos-fallback] Test 2 PASS（无坐标实体不兜底→失败 {set(cats)}）")

    # Test 3：模板命中 → 模板优先（无坐标兜底）
    r3 = run_target("chest_A", [True] * 6)  # move 步骤先消费 1 个
    assert r3["results"]["chest_A"] is True, r3["events"]
    coord_clicks = [c for c in r3["clicks"] if isinstance(c[0], (int, float))]
    assert not coord_clicks, f"模板命中不应触发坐标兜底: {r3['clicks']}"
    print("[pos-fallback] Test 3 PASS（模板命中→模板优先，无兜底）")

    print("[pos-fallback] Test 1-3 全部 PASS")


if __name__ == "__main__":
    main()
