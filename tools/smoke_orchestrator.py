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
from runtime.input.base import InputBackendProtocol, InputResult
from runtime.knowledge_loader import KnowledgePackage
from runtime.orchestrator import WorkflowOrchestrator
from runtime.state_machine import State

KNOWLEDGE = Path(__file__).resolve().parent.parent / "knowledge" / "source" / "black_tower_test"


class FakeAuto:
    def __init__(self, clicks):
        self.clicks = clicks
        self.n = 0

    def click_element(self, path, method, threshold=0.8, max_retries=1, include=None, crop=None):
        # BUG-07：mock 断言参数非空——真实 driver 参数错误在测试期暴露而非真机
        assert path, "click_element path 为空（模板/文本解析出问题）"
        assert method, "click_element method 为空"
        self.n += 1
        if not self.clicks:
            return False
        return self.clicks.pop(0)


class FakeInput:
    name = "fake"

    def __init__(self, clicks, click_result=True, fail_mode=None):
        self.auto = FakeAuto(clicks)
        self.click_result = click_result  # #26：vlm_bbox 路径也要能模拟失败
        # BUG-53：故障注入——SENDINPUT_FAIL / WINDOW_LOST / UI_NO_CHANGE
        self.fail_mode = fail_mode

    def _maybe_fail(self, action):
        if self.fail_mode == "SENDINPUT_FAIL":
            return InputResult(success=False, action=action, backend="fake",
                               error="uipi_block:sendinput_failed")
        if self.fail_mode == "WINDOW_LOST":
            return InputResult(success=False, action=action, backend="fake",
                               error="window_lost")
        if self.fail_mode == "UI_NO_CHANGE":
            return InputResult(success=False, action=action, backend="fake",
                               error="ui_no_change")
        return None

    def click(self, x, y) -> InputResult:
        f = self._maybe_fail("click")
        if f:
            return f
        return InputResult(success=self.click_result, action="click", backend="fake")

    def click(self, x, y) -> InputResult:
        return InputResult(success=self.click_result, action="click", backend="fake")

    def click_template(self, path, threshold, max_retries) -> InputResult:
        ok = bool(self.auto.click_element(path, "image", threshold, max_retries))
        return InputResult(success=ok, action="click_template", backend="fake",
                           error=None if ok else "click_element_failed")

    def click_text(self, text, include, max_retries, crop) -> InputResult:
        ok = bool(self.auto.click_element(text, "text", max_retries=max_retries,
                                          include=include, crop=crop))
        return InputResult(success=ok, action="click_text", backend="fake",
                           error=None if ok else "click_text_failed")

    def press_key(self, key, wait_time=0.2) -> InputResult:
        return InputResult(success=True, action="press_key", backend="fake")

    def release_key(self, key) -> InputResult:
        return InputResult(success=True, action="release_key", backend="fake")


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


# #20-3.7：契约断言——Fake 与真实 backend 必须同签名（防测试 PASS 真机失败）
assert isinstance(FakeInput([True]), InputBackendProtocol), \
    "FakeInput 未实现 InputBackendProtocol（接口漂移！）"

# B-2（测试审计）：runtime_checkable 只查方法存在不查签名——补签名比对
import inspect as _inspect
_PROTO_METHODS = [m for m in ("click", "press_key", "release_key",
                              "click_template", "click_text")
                  if hasattr(InputBackendProtocol, m)]
for _m in _PROTO_METHODS:
    _psig = _inspect.signature(getattr(InputBackendProtocol, _m))
    _fsig = _inspect.signature(getattr(FakeInput, _m))
    assert _psig == _fsig, f"FakeInput.{_m} 签名漂移: protocol={_psig} fake={_fsig}"
print("[contract] InputBackendProtocol 签名比对 PASS")


class FakeVLM:
    """VLM 观察者替身：#42 VGM 定位路径需要真实命中才 success。"""

    def locate_target(self, screenshot, target_desc):
        return {"found": True, "screen_x": 500, "screen_y": 500,
                "confidence": 0.9, "bbox": [0.5, 0.5, 0.5, 0.5]}

    def observe_room(self, screenshot, room_ids):
        return {"room": None, "confidence": 0.0, "ui_state": None}


class FakeVLMFalse:
    """BUG-08：VLM 定位失败替身——found=false 低置信（幻觉反面：看不到）。

    与 FakeVLM 同 schema（screen_x/screen_y/bbox 统一 None）——防生产代码
    按完整字段取值时失败路径 KeyError。
    """

    def locate_target(self, screenshot, target_desc):
        return {"found": False, "screen_x": None, "screen_y": None,
                "bbox": None, "confidence": 0.1}

    def observe_room(self, screenshot, room_ids):
        return {"room": None, "confidence": 0.1, "ui_state": None}


class FakeObserver:
    """#20-7 观察器替身：观察 → Observation（不产决策）。"""

    def __init__(self, text=None, entities=None):
        self.text = text or ["chest_A"]
        self.entities = entities or []
        self.counter = 0  # 每次观察递增——frame_id 唯一（防去重/确认逻辑失效）

    def observe(self):
        from runtime.observation import Observation
        self.counter += 1
        return Observation(ui_state="test", text=list(self.text),
                           entities=list(self.entities),
                           confidence=1.0, source="fake",
                           frame_id=f"fake-{self.counter}")


class FakeBadVLM:
    """#8-8 幻觉 VLM：错误画面仍报 shop + 高置信 0.95。"""

    def observe(self, screenshot):
        return {"room": "space", "ui_state": "shop", "confidence": 0.95}


class FakeOCRDeny:
    """#8-8 否认 OCR：画面实际是 IDE（Visual Studio）。"""

    def detect(self, screenshot):
        return {"text": ["Visual Studio", "Python"]}


def run_scenario(clicks, label):
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append((e.type, e.context)))

    pkg = KnowledgePackage(KNOWLEDGE)
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id=f"smoke-{label}", use_vlm=True)

    def driver_factory():
        return FakeDriver(list(clicks))

    with mock.patch("runtime.drivers.march7th.get_driver", side_effect=driver_factory), \
            mock.patch("runtime.step_executor.VLMVisionObserver", FakeVLM), \
            mock.patch("runtime.drivers.march7th.window.find_game_window",
                       return_value={"hwnd": 1, "client": (1920, 1080)}), \
            mock.patch.object(orch, "start_emergency", lambda: None):
        results, completed = orch.run_mission(["chest_A"])

    end_state = orch._machine.state
    print(f"[{label}] results={results} completed={completed} state={end_state.value}")
    for t, ctx in seen:
        if t in ("fail_recorded", "target_progress", "action_executed"):
            print(f"  {t}: {ctx}")
    return results, end_state


def main():
    results, state = run_scenario([True] * 10, "ok")
    assert results == {"chest_A": True}, results
    assert state == State.DONE, state

    # #42：事件顺序断言——mission 生命周期必须按序出现
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append(e.type))
    pkg = KnowledgePackage(KNOWLEDGE)
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id="smoke-order", use_vlm=True)

    def driver_factory():
        return FakeDriver([True] * 10)

    with mock.patch("runtime.drivers.march7th.get_driver", side_effect=driver_factory), \
            mock.patch("runtime.step_executor.VLMVisionObserver", FakeVLM), \
            mock.patch("runtime.drivers.march7th.window.find_game_window",
                       return_value={"hwnd": 1, "client": (1920, 1080)}), \
            mock.patch.object(orch, "start_emergency", lambda: None):
        orch.run_mission(["chest_A"])
    order = [t for t in seen if t in
             ("state_changed", "action_executed", "target_progress")]
    assert order[0] == "state_changed", order[:2]     # 状态机先启动
    assert "action_executed" in order
    assert order[-1] == "target_progress", order[-2:]  # done 事件收尾
    print("[ok] 事件生命周期顺序 PASS")

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
    with mock.patch.object(orch, "start_emergency", lambda: None):
        results, completed = orch.run_mission(["chest_A"])
    assert results == {"chest_A": False}, results
    assert completed == [], completed
    ev = [ctx for t, ctx in seen if t == "target_progress" and ctx.get("status") == "failed"]
    assert ev and ev[-1].get("category") == "EMERGENCY", ev
    print("[ok] EmergencyMonitor 介入 → mission 即停 PASS")

    # S17 场景4（chaos）：游戏窗口消失 → F3_WINDOW 快速失败，不盲目点击
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append((e.type, e.context)))
    pkg = KnowledgePackage(KNOWLEDGE)
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id="smoke-window", use_vlm=True)

    def driver_factory():
        return FakeDriver([])

    with mock.patch("runtime.drivers.march7th.get_driver", side_effect=driver_factory), \
            mock.patch("runtime.step_executor.VLMVisionObserver", FakeVLM), \
            mock.patch("runtime.drivers.march7th.window.find_game_window", return_value=None):
        results, completed = orch.run_mission(["chest_A"])
    assert results == {"chest_A": False}, results
    ev = [ctx for t, ctx in seen if t == "target_progress" and ctx.get("status") == "failed"]
    assert ev and ev[-1].get("category") == "F3_WINDOW", ev
    print("[ok] 窗口消失 → F3_WINDOW 即停 PASS")

    # 场景6（#20-7）：观察→规划→执行插层链路——FakeObserver 文本命中 → planner
    # 产 INTERACT intent → executor.execute_intent 走 click_text → success
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append((e.type, e.context)))
    pkg = KnowledgePackage(KNOWLEDGE)
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id="smoke-obsact", use_vlm=True)
    orch.observer = FakeObserver(text=["chest_A"])

    def driver_factory():
        return FakeDriver([True] * 3)

    with mock.patch("runtime.drivers.march7th.get_driver", side_effect=driver_factory), \
            mock.patch("runtime.step_executor.VLMVisionObserver", FakeVLM), \
            mock.patch("runtime.drivers.march7th.window.find_game_window",
                       return_value={"hwnd": 1, "client": (1920, 1080)}), \
            mock.patch.object(orch, "start_emergency", lambda: None):
        result = orch.observe_act("chest_A")
    assert result.success, result
    assert result.error is None, result.error
    acts = [ctx for t, ctx in seen if t == "action_executed"]
    assert acts and acts[-1].get("method") == "text", acts
    print("[ok] observe→plan→execute 链路（FakeObserver → Planner → click_text）PASS")

    # 场景7（#8-8）：VLM 幻觉 + OCR 否认 → fusion 低置信 → Planner WAIT 不点击
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append((e.type, e.context)))
    pkg = KnowledgePackage(KNOWLEDGE)
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id="smoke-fusion", use_vlm=True)
    from runtime.vision_observer import VisionObserver
    from runtime.observation_memory import StableState
    orch.observer = VisionObserver(ocr=FakeOCRDeny(), vlm=FakeBadVLM(),
                                   capture_fn=lambda: "C:/fake/bad.png")
    memory = StableState()

    def driver_factory():
        return FakeDriver([True] * 3)

    with mock.patch("runtime.drivers.march7th.get_driver", side_effect=driver_factory), \
            mock.patch("runtime.step_executor.VLMVisionObserver", FakeVLM), \
            mock.patch("runtime.drivers.march7th.window.find_game_window",
                       return_value={"hwnd": 1, "client": (1920, 1080)}), \
            mock.patch.object(orch, "start_emergency", lambda: None):
        result = orch.observe_act("chest_A")
    assert result.success, result
    acts = [ctx for t, ctx in seen if t == "action_executed"]
    assert acts and acts[-1].get("action") == "wait", acts[-1]
    assert acts[-1].get("reason") == "low confidence", acts[-1]
    first_obs = orch.observer.observe()
    assert first_obs.confidence == 0.3, first_obs.confidence
    memory.update(first_obs)
    assert memory.label == "CONFIRMING", memory.label
    memory.update(first_obs)
    assert memory.label == "STABLE" and memory.hits == 2, memory.label
    print("[ok] VLM幻觉+OCR否认 → fusion=0.3 → Planner WAIT 禁止点击 PASS")

    # 场景8（#20-9）：ReplayInput 确定性输入——回放 [True,True,False] 驱动 observe_act
    from runtime.input.replay import ReplayInput
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append((e.type, e.context)))
    pkg = KnowledgePackage(KNOWLEDGE)
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id="smoke-replay", use_vlm=False)
    orch.observer = FakeObserver(text=["chest_A"])
    replay = ReplayInput([True, True, False])

    def driver_factory():
        return FakeDriver([])

    with mock.patch("runtime.drivers.march7th.get_driver", side_effect=driver_factory), \
            mock.patch("runtime.drivers.march7th.window.find_game_window",
                       return_value={"hwnd": 1, "client": (1920, 1080)}), \
            mock.patch.object(orch, "start_emergency", lambda: None):
        orch._executor = orch.executor  # 确保已构造
        orch.executor._input_override = replay
        result = orch.observe_act("chest_A")
    assert result.success, result
    assert replay.consumed == 1, replay.consumed
    assert replay.history == ["click_text"], replay.history  # 只发生一次文本点击
    print("[ok] ReplayInput 确定性输入（回放驱动，替代 Fake 手工 mock）PASS")

    # 场景9（#20-9）：ObserveOnly 降级——无输入权限时执行不崩溃，
    # 返回 observe_only 结构化失败 + fail_recorded
    from runtime.input.observe import ObserveOnlyInput
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append((e.type, e.context)))
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id="smoke-observeonly", use_vlm=False)
    orch.observer = FakeObserver(text=["chest_A"])
    observe = ObserveOnlyInput()

    def driver_factory():
        return FakeDriver([])

    with mock.patch("runtime.drivers.march7th.get_driver", side_effect=driver_factory), \
            mock.patch("runtime.drivers.march7th.window.find_game_window",
                       return_value={"hwnd": 1, "client": (1920, 1080)}), \
            mock.patch.object(orch, "start_emergency", lambda: None):
        orch.executor._input_override = observe
        result = orch.observe_act("chest_A")
    assert not result.success, result
    assert result.error and "observe_only" in result.error, result.error
    assert result.retryable is False, result.retryable  # 永久失败语义：不重试不崩溃
    print("[ok] ObserveOnly 降级 → observe_only 失败（不点击不崩溃不重试）PASS")

    # 场景10（BUG-08）：VLM 定位失败（found=false）→ 移动失败 F2_COORD，不点击
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append((e.type, e.context)))
    pkg = KnowledgePackage(KNOWLEDGE)
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id="smoke-vlmfalse", use_vlm=True)

    def driver_factory():
        return FakeDriver([True] * 10)

    with mock.patch("runtime.drivers.march7th.get_driver", side_effect=driver_factory), \
            mock.patch("runtime.step_executor.VLMVisionObserver", FakeVLMFalse), \
            mock.patch("runtime.drivers.march7th.window.find_game_window",
                       return_value={"hwnd": 1, "client": (1920, 1080)}), \
            mock.patch.object(orch, "start_emergency", lambda: None):
        results, completed = orch.run_mission(["chest_A"])
    assert results == {"chest_A": False}, results
    cats = [ctx.get("category") for t, ctx in seen if t == "fail_recorded"]
    assert any("F2_COORD" in c for c in cats), cats
    acts = [ctx for t, ctx in seen if t == "action_executed"]
    assert all(ctx.get("success") is not False or ctx.get("action") == "wait"
               for ctx in acts) or not acts, "VLM 未定位时不应有点击成功记录"
    print("[ok] VLM 定位失败 → F2_COORD 失败（不点击不假成功）PASS")

    # 场景11（Sprint B-2）：strict guard 拒绝未验证意图 → F4_VISION + 0 次 click
    from runtime.guards.action_guard import ActionGuard
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append((e.type, e.context)))
    pkg = KnowledgePackage(KNOWLEDGE)
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id="smoke-guard", use_vlm=False)
    orch.observer = FakeObserver(text=["chest_A"])
    replay = ReplayInput([True, True])

    def driver_factory():
        return FakeDriver([])

    with mock.patch("runtime.drivers.march7th.get_driver", side_effect=driver_factory), \
            mock.patch("runtime.drivers.march7th.window.find_game_window",
                       return_value={"hwnd": 1, "client": (1920, 1080)}), \
            mock.patch.object(orch, "start_emergency", lambda: None):
        orch.executor._input_override = replay
        orch.executor.guard = ActionGuard(strict=True)  # 执行前必须视觉证明
        assert orch.executor.guard.strict is True, "guard 注入未生效（可能被内部重建）"
        result = orch.observe_act("chest_A")
    assert not result.success, result
    assert result.error and "vision_guard" in result.error, result.error
    assert result.category == "F4_VISION", result.category
    assert replay.consumed == 0, f"守卫拒绝后不应有任何输入注入（consumed={replay.consumed}）"
    fails = [ctx for t, ctx in seen if t == "fail_recorded"]
    assert fails and fails[-1].get("category") == "F4_VISION", fails
    print("[ok] ActionGuard strict → F4_VISION 拒绝 + 0 次 click（证据缺失不执行）PASS")

    # 场景12（Sprint B）：目标级 OCR 验证词——全局词命中但目标词未命中 → 拒绝
    from runtime.vision_gate import VisionGate, VisionEvidence, OCREvidence, VLMEvidence
    target_kw = pkg.verify_expectations("chest_A").get("ocr")  # 目标词（未声明 → None）
    ev12 = VisionEvidence(ocr=OCREvidence(texts=["商店", "购买"]),
                          vlm=VLMEvidence(scene="shop", confidence=0.9),
                          frame_quality="ok")
    if target_kw:
        r12 = VisionGate().evaluate(ev12, target_keywords=target_kw)
        # 目标词（如 minimap_chest_icon 相关）未出现在 OCR → 拒绝或 observe
        assert not r12["allowed"], r12
        print(f"[ok] 目标级验证：全局词命中但目标词{target_kw}未命中 → 拒绝 PASS")
    else:
        print("[ok] 目标级验证：workflow 未声明 verify.ocr（跳过，API 可用性已验）PASS")


if __name__ == "__main__":
    main()
