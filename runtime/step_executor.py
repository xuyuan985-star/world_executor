import time
from pathlib import Path

from runtime.decision.action import ActionIntent
from runtime.naturalness import NaturalnessPolicy
from runtime.observers.vlm_vision import VLMVisionObserver

M7_ROOT = Path(__file__).resolve().parent.parent.parent / "March7thAssistant"


class RealExecutor:
    """真机执行器：基于 March7th Driver（v0.12.1）。

    决策层只产 ActionIntent（不携带坐标）；VLM 定位坐标只进 observation，
    executor 消费后换算绝对坐标（换算属于执行细节）。
    """

    def __init__(self, pkg, bus=None, execution_id=None, use_vlm=True):
        self.pkg = pkg
        self.bus = bus
        self.execution_id = execution_id
        self.naturalness = NaturalnessPolicy()
        self.vlm = VLMVisionObserver() if use_vlm else None
        self._driver = None
        self._last_vlm_pos = None  # (norm_x, norm_y) 归一化 0-1

    # ---------- driver / 事件 ----------

    @property
    def driver(self):
        if self._driver is None:
            from runtime.drivers.march7th import get_driver
            self._driver = get_driver()
        return self._driver

    def _emit(self, event_type, **kw):
        if self.bus is not None:
            from runtime.events.schema import make_event
            self.bus.publish(make_event(event_type, self.execution_id, **kw))

    def screenshot_path(self):
        return self.driver["vision"].screenshot_path("ingest/raw/frames/live")

    # ---------- 观测（observer 通道，不产决策） ----------

    def observe_room(self, room_ids):
        if self.vlm is None:
            return None, None
        shot = self.screenshot_path()
        data = self.vlm.observe_room(shot, room_ids)
        room = data.get("room")
        confidence = data.get("confidence")
        ui_state = data.get("ui_state")
        self._emit("observation", detail=f"room:{room}",
                   context={"observer": "vlm_vision", "target": "room_id",
                            "confidence": confidence, "room": room, "ui_state": ui_state})
        return room, confidence

    def locate_target(self, target_desc):
        if self.vlm is None:
            return None
        shot = self.screenshot_path()
        data = self.vlm.locate_target(shot, target_desc)
        found = data.get("found") is True
        x, y = data.get("screen_x"), data.get("screen_y")
        if found and x and y:
            self._last_vlm_pos = (float(x) / 1000.0, float(y) / 1000.0)
        else:
            self._last_vlm_pos = None
        self._emit("observation", detail=f"locate:{'found' if found else 'miss'}",
                   context={"observer": "vlm_vision", "target": target_desc,
                            "confidence": data.get("confidence"),
                            "screen_x": self._last_vlm_pos[0] if self._last_vlm_pos else None,
                            "screen_y": self._last_vlm_pos[1] if self._last_vlm_pos else None})
        return self._last_vlm_pos

    # ---------- 执行（ActionIntent） ----------

    def execute(self, intent: ActionIntent):
        """执行动作意图。坐标不进入 intent：vlm_absolute 由本层换算。"""
        backend = self.driver["input"]
        delay = self.naturalness.click_delay()
        time.sleep(delay)
        if intent.method == "vlm_absolute":
            result = self._click_vlm_absolute(intent)
        else:
            result = backend.execute(intent)
        self._emit("action_executed", detail=f"{intent.action}:{intent.target}",
                   context={"naturalized": True, "delay_ms": int(delay * 1000),
                            **intent.to_context(), **result.to_context()})
        return result.success

    def _click_vlm_absolute(self, intent):
        if self._last_vlm_pos is None:
            from runtime.input.base import InputResult
            return InputResult(success=False, action="click_vlm_absolute",
                               backend=self.driver["input"].name,
                               error="no_vlm_position: 缺少最近一次定位观测")
        nx, ny = self._last_vlm_pos
        px, py = self.driver["vision"].to_absolute(nx, ny)
        return self.driver["input"].click(px, py)

    # ---------- 便捷包装（调用方免构造 intent） ----------

    def interact_template(self, template, threshold=0.85, max_retries=3):
        return self.execute(ActionIntent(
            action="interact", target=template, method="template",
            params={"threshold": threshold, "max_retries": max_retries},
            reason="objective_interact"))

    def click_text(self, text, include=True, max_retries=3, crop=None):
        return self.execute(ActionIntent(
            action="click_text", target=text, method="text",
            params={"include": include, "max_retries": max_retries, "crop": crop},
            reason="objective_ui"))

    def move_visual_guided(self, target_desc, ticks, step_seconds):
        for i in range(ticks):
            pos = self.locate_target(target_desc)
            if pos is None:
                break
            x, y = pos
            dur = self.naturalness.sprint_duration(step_seconds)
            if 0.4 < x < 0.6:
                self.driver["input"].press_key("w", wait_time=dur)
                self._emit("action_executed", detail=f"move_forward:{dur:.1f}s",
                           context={"naturalized": True, "tick": i})
            else:
                side = "d" if x < 0.5 else "a"
                self.driver["input"].press_key(side, wait_time=self.naturalness.rotate_duration())
                self._emit("action_executed", detail=f"steer:{side}",
                           context={"naturalized": True, "tick": i})
        return True

    def portal_transition(self, portal, wait_base):
        trigger = portal["trigger"]
        ok = self.interact_template(trigger["template"], trigger["threshold"])
        if not ok:
            return False
        wait = self.naturalness.transition_wait(wait_base)
        time.sleep(wait)
        return True

    def verify_signal(self, template, expected, timeout):
        vision = self.driver["vision"]
        deadline = time.time() + timeout
        while time.time() < deadline:
            found = vision.find_template(str(self.pkg.templates_dir / template), 0.8) is not None
            if (expected == "vanished" and not found) or (expected == "present" and found):
                return True
            time.sleep(1.5)
        return False
