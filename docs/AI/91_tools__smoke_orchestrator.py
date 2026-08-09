# tools/smoke_orchestrator.py

```python
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
        self.clicks = []  # #42-B12：真实调用级点击记录（零误触断言核心）

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
        if self.fail_mode == "EXCEPTION":
            raise TimeoutError("simulated input crash")  # 崩溃注入（F1_EXEC 路径）
        return None

    def click(self, x, y) -> InputResult:
        f = self._maybe_fail("click")
        if f:
            return f
        self.clicks.append((x, y))
        return InputResult(success=self.click_result, action="click", backend="fake")

    def click_template(self, path, threshold, max_retries) -> InputResult:
        f = self._maybe_fail("click_template")
        if f:
            return f
        ok = bool(self.auto.click_element(path, "image", threshold, max_retries))
        self.clicks.append(("template", path))
        return InputResult(success=ok, action="click_template", backend="fake",
                           error=None if ok else "click_element_failed")

    def click_text(self, text, include, max_retries, crop) -> InputResult:
        f = self._maybe_fail("click_text")
        if f:
            return f
        ok = bool(self.auto.click_element(text, "text", max_retries=max_retries,
                                          include=include, crop=crop))
        self.clicks.append(("text", text))
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


class FakeVisionDPI125:
    """#13：125% DPI 变体——client 1536x864 / physical 1920x1080。

    真实换算：0.5,0.5 → (960,540)（物理），不是 (768,432)。
    Fake 不再掩盖 DPI bug。
    """
    LOGICAL = (1536, 864)
    PHYSICAL = (1920, 1080)

    def screenshot_path(self, sub):
        return "C:/fake/dpi125.png"

    def find_template(self, path, threshold):
        return None

    def to_absolute(self, nx, ny):
        return int(nx * self.PHYSICAL[0]), int(ny * self.PHYSICAL[1])


class FakeDriver:
    """每个场景独立实例：不共享类变量，避免测试互相污染。
    BUG-04/05：与真实 Driver 结构同构（window 层 + vision_cls 参数化 DPI）。"""
    name = "fake"

    def __init__(self, clicks, vision_cls=None, window_found=None):
        self.input = FakeInput(clicks)
        self.vision = (vision_cls or FakeVision)()
        # 窗口层（真实 Driver 有 find_window/activate_window）
        self.window_found = window_found if window_found is not None \
            else {"hwnd": 1, "client": (1920, 1080)}
        self.activated = 0

    def find_window(self):
        return self.window_found

    def activate_window(self):
        self.activated += 1
        return True


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
    """VLM 观察者替身：#42 VGM 定位路径需要真实命中才 success。
    #14：按目标返回不同坐标——防"所有目标点击同一点"掩盖绑定 bug。
    BUG-23：参数化 found/confidence——边界测试不再依赖写死高值。"""

    TARGET_POS = {"chest_A": (500, 500), "lm_hall_center": (800, 400),
                  "door_A": (1000, 700)}

    def __init__(self, found=True, confidence=0.9):
        self.found = found
        self.confidence = confidence

    def locate_target(self, screenshot, target_desc):
        if not self.found:
            return {"found": False, "screen_x": None, "screen_y": None,
                    "bbox": None, "confidence": self.confidence}
        x, y = self.TARGET_POS.get(target_desc, (500, 500))
        return {"found": True, "screen_x": x, "screen_y": y,
                "confidence": self.confidence, "bbox": [0.4, 0.4, 0.6, 0.6]}

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
        # Bug16：构造时深复制——外部修改 self.text 不污染后续 observe
        self._text = list(text or ["chest_A"])
        self._entities = list(entities or [])
        self.counter = 0  # 每次观察递增——frame_id 唯一（防去重/确认逻辑失效）

    def observe(self):
        from runtime.observation import Observation
        self.counter += 1
        return Observation(ui_state="test", text=list(self._text),
                           entities=list(self._entities),
                           confidence=1.0, source="fake",
                           frame_id=f"fake-{self.counter}")


class FakeObserverSequence:
    """#29：观察序列替身——模拟目标中途消失（第一次命中，第二次空）。"""

    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.counter = 0

    def observe(self):
        from runtime.observation import Observation
        self.counter += 1
        texts = self.sequence[min(self.counter - 1, len(self.sequence) - 1)]
        return Observation(ui_state="test", text=list(texts),
                           confidence=1.0, source="fake-seq",
                           frame_id=f"seq-{self.counter}")


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
    orch.foreground_check = False  # mock 跳过前台判定

    def driver_factory():
        return FakeDriver(list(clicks))

    with mock.patch("runtime.drivers.march7th.get_driver", side_effect=driver_factory), \
            mock.patch("runtime.step_executor.VLMVisionObserver", FakeVLM), \
            mock.patch("runtime.drivers.march7th.window.find_game_window",
                       return_value={"hwnd": 1, "client": (1920, 1080)}), \
            mock.patch.object(orch, "start_emergency", lambda: None):
        results, completed = orch.run_mission(["chest_A"])

    end_state = orch._machine.state
    # #31：生命周期终点——target_progress(done) 是 orchestrator 层最终事实；
    # run_finished 由 API 层（commands.py）发（orchestrator 直调路径不包含）
    if label == "ok":
        done = [ctx for t, ctx in seen
                if t == "target_progress" and ctx.get("status") == "done"]
        assert done, "mission 未发 target_progress(done)（生命周期断裂）"
    print(f"[{label}] results={results} completed={completed} state={end_state.value}")
    for t, ctx in seen:
        if t in ("fail_recorded", "target_progress", "action_executed"):
            print(f"  {t}: {ctx}")
    # Bug20：返回完整审计面（事件流）——失败可定位"为什么"
    return results, end_state, seen


def main():
    results, state, _seen_ok = run_scenario([True] * 10, "ok")
    assert results == {"chest_A": True}, results
    assert state == State.DONE, state

    # #42：事件顺序断言——mission 生命周期必须按序出现
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append(e.type))
    pkg = KnowledgePackage(KNOWLEDGE)
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id="smoke-order", use_vlm=True)
    orch.foreground_check = False  # mock 跳过前台判定

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

    results, state, _seen_fail = run_scenario([True, False, False, False], "fail")
    assert results == {"chest_A": False}, results
    print("[ok] interact 失败 → retry 用尽 → target failed PASS (state=%s)" % state.value)

    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append((e.type, e.context)))
    pkg = KnowledgePackage(KNOWLEDGE)
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id="smoke-emergency", use_vlm=False)
    orch.foreground_check = False  # mock 跳过前台判定

    class FakePaused:
        # #16：spy——确认 monitor 真的被轮询（防代码路径跳过导致假成功）
        def __init__(self):
            self.polls = 0

        def is_paused(self):
            self.polls += 1
            return True

        def stop(self):
            pass

    spy = FakePaused()
    orch._monitor = spy
    with mock.patch.object(orch, "start_emergency", lambda: None):
        results, completed = orch.run_mission(["chest_A"])
    assert spy.polls > 0, "EmergencyMonitor.is_paused 从未被调用（测试假成功！）"
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
    orch.foreground_check = False  # mock 跳过前台判定

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
    orch.foreground_check = False  # mock 跳过前台判定
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
    orch.foreground_check = False  # mock 跳过前台判定
    from runtime.vision_observer import VisionObserver
    from runtime.observation_memory import StableState
    orch.observer = VisionObserver(ocr=FakeOCRDeny(), vlm=FakeBadVLM(),
                                   capture_fn=lambda: "C:/fake/bad.png")
    memory = StableState()

    def driver_factory():
        return FakeDriver([True] * 3)

    # Bug5（测试审计）：observe_act 走 orch.observer（FakeBadVLM+FakeOCRDeny），
    # 不经过 executor 内部 VLMVisionObserver——此处 patch 纯属多余且会误导
    #（若未来 observe_act 内部改用 executor.vlm 会静默绕过幻觉测试）
    with mock.patch("runtime.drivers.march7th.get_driver", side_effect=driver_factory), \
            mock.patch("runtime.drivers.march7th.window.find_game_window",
                       return_value={"hwnd": 1, "client": (1920, 1080)}), \
            mock.patch.object(orch, "start_emergency", lambda: None):
        result = orch.observe_act("chest_A")
    assert result.success, result
    acts = [ctx for t, ctx in seen if t == "action_executed"]
    assert acts and acts[-1].get("action") == "wait", acts[-1]
    assert acts[-1].get("reason") == "low confidence", acts[-1]
    # #15：显式统计零点击（防"wait 后还点了"漏网）
    clicks = [ctx for ctx in acts if ctx.get("action") in ("interact", "click")]
    assert len(clicks) == 0, f"幻觉场景不应有任何点击: {clicks}"
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
    orch.foreground_check = False  # mock 跳过前台判定
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
    orch.foreground_check = False  # mock 跳过前台判定
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
    orch.foreground_check = False  # mock 跳过前台判定

    def driver_factory():
        return FakeDriver([True] * 10)

    # 场景10（BUG-08）：VLM 定位失败（found=false）→ 移动失败 F2_COORD，不点击
    fake_input_10 = None

    def driver_factory_10():
        nonlocal fake_input_10
        fake_input_10 = FakeInput([True] * 10)
        d = FakeDriver([])
        d.input = fake_input_10
        return d

    with mock.patch("runtime.drivers.march7th.get_driver", side_effect=driver_factory_10), \
            mock.patch("runtime.step_executor.VLMVisionObserver", FakeVLMFalse), \
            mock.patch("runtime.drivers.march7th.window.find_game_window",
                       return_value={"hwnd": 1, "client": (1920, 1080)}), \
            mock.patch.object(orch, "start_emergency", lambda: None):
        results, completed = orch.run_mission(["chest_A"])
    assert results == {"chest_A": False}, results
    cats = [ctx.get("category") for t, ctx in seen if t == "fail_recorded"]
    assert any("F2_COORD" in c for c in cats), cats
    # BUG-13：不只验证 category——还要验证失败原因粒度（vlm 未定位）
    errs = [ctx.get("error") for t, ctx in seen if t == "fail_recorded"]
    assert any(e and ("no_observation" in e or "move_stuck" in e
                      or "move_aborted" in e) for e in errs), errs
    acts = [ctx for t, ctx in seen if t == "action_executed"]
    assert all(ctx.get("success") is not False or ctx.get("action") == "wait"
               for ctx in acts) or not acts, "VLM 未定位时不应有点击成功记录"
    # #42-B12：调用级零误触断言——导航点击（move 模板）合法，
    # 但 VLM 未定位时不得出现对目标 chest 的交互点击
    chest_clicks = [c for c in (fake_input_10.clicks or [])
                    if isinstance(c, tuple) and len(c) == 2
                    and "chest" in str(c[1])]
    assert fake_input_10 is not None and len(chest_clicks) == 0, \
        f"VLM 未定位时仍发生目标交互点击: {chest_clicks}"
    print("[ok] VLM 定位失败 → F2_COORD 失败（事件级+调用级零目标点击）PASS")

    # 场景11（Sprint B-2）：strict guard 拒绝未验证意图 → F4_VISION + 0 次 click
    from runtime.guards.action_guard import ActionGuard
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append((e.type, e.context)))
    pkg = KnowledgePackage(KNOWLEDGE)
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id="smoke-guard", use_vlm=False)
    orch.foreground_check = False  # mock 跳过前台判定
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
    assert target_kw is not None, "workflow 必须声明 verify.ocr（#19：配置缺失=安全规则失效，测试应失败）"
    ev12 = VisionEvidence(ocr=OCREvidence(texts=["商店", "购买"]),
                          vlm=VLMEvidence(scene="shop", confidence=0.9),
                          frame_quality="ok")
    r12 = VisionGate().evaluate(ev12, target_keywords=target_kw)
    # 目标词（如 minimap_chest_icon 相关）未出现在 OCR → 拒绝或 observe
    assert not r12["allowed"], r12
    print(f"[ok] 目标级验证：全局词命中但目标词{target_kw}未命中 → 拒绝 PASS")

    # 场景13（#23）：崩溃注入——输入层抛异常 → F1_EXEC 可观测失败（不黑盒崩溃）
    from runtime.input.replay import ReplayInput as _RI
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append((e.type, e.context)))
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id="smoke-crash", use_vlm=False)
    orch.foreground_check = False  # mock 跳过前台判定
    orch.observer = FakeObserver(text=["chest_A"])

    def driver_factory():
        return FakeDriver([])

    with mock.patch("runtime.drivers.march7th.get_driver", side_effect=driver_factory), \
            mock.patch("runtime.drivers.march7th.window.find_game_window",
                       return_value={"hwnd": 1, "client": (1920, 1080)}), \
            mock.patch.object(orch, "start_emergency", lambda: None):
        orch.executor._input_override = FakeInput([True], fail_mode="EXCEPTION")
        result = orch.observe_act("chest_A")
    assert not result.success, result
    assert result.error and "executor_exception" in result.error, result.error
    assert result.category == "F1_EXEC", result.category
    print("[ok] 崩溃注入 → F1_EXEC 可观测失败（不黑盒崩溃）PASS")

    # 场景14（#29）：目标消失——第一次命中，第二次空 → WAIT 不点击旧坐标
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: seen.append((e.type, e.context)))
    orch = WorkflowOrchestrator(pkg, bus=bus, execution_id="smoke-disappear", use_vlm=False)
    orch.foreground_check = False  # mock 跳过前台判定
    orch.observer = FakeObserverSequence([["chest_A"], []])  # 第二次目标消失

    def driver_factory():
        return FakeDriver([True, True])  # 两次观察都可能点击 → 回放成功

    with mock.patch("runtime.drivers.march7th.get_driver", side_effect=driver_factory), \
            mock.patch("runtime.drivers.march7th.window.find_game_window",
                       return_value={"hwnd": 1, "client": (1920, 1080)}), \
            mock.patch.object(orch, "start_emergency", lambda: None):
        r1 = orch.observe_act("chest_A")   # 命中 → 点击
        r2 = orch.observe_act("chest_A")   # 消失 → WAIT
    assert r1.success, r1
    assert r2.success and r2.error is None, r2  # WAIT 语义：不执行不失败
    acts2 = [ctx for t, ctx in seen if t == "action_executed"]
    assert acts2[-1].get("action") == "wait", acts2[-1]
    print("[ok] 目标消失 → 第二次 WAIT（不点击旧坐标）PASS")


if __name__ == "__main__":
    main()

```
