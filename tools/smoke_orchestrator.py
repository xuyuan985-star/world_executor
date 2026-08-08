"""WorkflowOrchestrator 冒烟：mock March7th driver，验证全链路与失败路径。

场景1：全步骤成功 → target done、状态机 DONE。
场景2：interact 持续失败 → retry 用尽 → fail_recorded(F1) + target failed。
"""
import sys
import time
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime.events.bus import EventBus
from runtime.knowledge_loader import KnowledgePackage
from runtime.orchestrator import WorkflowOrchestrator
from runtime.state_machine import State

KNOWLEDGE = Path(__file__).resolve().parent.parent / "knowledge" / "source" / "black_tower_test"


class FakeAuto:
    def __init__(self, clicks):
        self.clicks = clicks
        self.n = 0

    def click_element(self, path, method, threshold, max_retries):
        self.n += 1
        if not self.clicks:
            return False
        return self.clicks.pop(0)


class FakeInput:
    def __init__(self, clicks, click_result=True):
        self.auto = FakeAuto(clicks)
        self.click_result = click_result  # #26：vlm_bbox 路径也要能模拟失败

    def click(self, x, y):
        return self.click_result

    def press_key(self, key, wait_time=0):
        time.sleep(0)
        return True


class FakeVision:
    def screenshot_path(self, sub):
        return "C:/fake/live.png"

    def find_template(self, path, threshold):
        return None

    def to_absolute(self, nx, ny):
        return int(nx * 1920), int(ny * 1080)


class FakeDriver:
    """每个场景独立实例：不共享类变量，避免测试互相污染。"""
    name = "fake"

    def __init__(self, clicks):
        self.input = FakeInput(clicks)
        self.vision = FakeVision()


def run_scenario(clicks, label):
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append((e.type, e.context)))

    pkg = KnowledgePackage(KNOWLEDGE)
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id=f"smoke-{label}", use_vlm=False)

    def driver_factory():
        return FakeDriver(list(clicks))

    with mock.patch("runtime.drivers.march7th.get_driver", side_effect=driver_factory):
        results = orch.run_mission(["chest_A"])

    end_state = orch._machine.state
    print(f"[{label}] results={results} state={end_state.value}")
    for t, ctx in seen:
        if t in ("fail_recorded", "target_progress", "action_executed"):
            print(f"  {t}: {ctx}")
    return results, end_state


def main():
    results, state = run_scenario([True] * 10, "ok")
    assert results == {"chest_A": True}, results
    assert state == State.DONE, state
    print("[ok] 全链路成功 PASS")

    results, state = run_scenario([True, False, False, False], "fail")
    assert results == {"chest_A": False}, results
    print("[ok] interact 失败 → retry 用尽 → target failed PASS (state=%s)" % state.value)

    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append((e.type, e.context)))
    pkg = KnowledgePackage(KNOWLEDGE)
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id="smoke-emergency", use_vlm=False)

    class FakePaused:
        def is_paused(self):
            return True

        def stop(self):
            pass

    orch._monitor = FakePaused()
    results = orch.run_mission(["chest_A"])
    assert results == {"chest_A": False}, results
    ev = [ctx for t, ctx in seen if t == "target_progress" and ctx.get("status") == "failed"]
    assert ev and ev[-1].get("category") == "EMERGENCY", ev
    print("[ok] EmergencyMonitor 介入 → mission 即停 PASS")


if __name__ == "__main__":
    main()
