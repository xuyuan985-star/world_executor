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
        self._entity_templates = None
        self._obs_store = {}        # 世界实体 id → 最近观测 bbox（归一化 0-1）
        self._recent_events = []    # 最近事件 id（fail_recorded.related_events 用）
        self._MAX_RECENT = 20

    @property
    def driver(self):
        if self._driver is None:
            from runtime.drivers.march7th import get_driver
            self._driver = get_driver()
        return self._driver

    def _emit(self, event_type, **kw):
        if self.bus is not None:
            from runtime.events.schema import make_event
            ev = make_event(event_type, self.execution_id, **kw)
            self.bus.publish(ev)
            self._recent_events.append(ev.id)
            if len(self._recent_events) > self._MAX_RECENT:
                self._recent_events.pop(0)
            return ev
        return None

    def entity_templates(self):
        if self._entity_templates is None:
            self._entity_templates = self.pkg.entity_templates()
        return self._entity_templates

    def resolve_template(self, entity_id):
        """世界实体 id → 模板路径（executor 层解析，intent 不携带模板名）。"""
        name = self.entity_templates().get(entity_id)
        if not name:
            return None
        path = self.pkg.templates_dir / name
        return str(path) if path.exists() else None

    def screenshot_path(self):
        return self.driver.vision.screenshot_path("ingest/raw/frames/live")

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
        bbox = None
        if found and x and y:
            bbox = (float(x) / 1000.0, float(y) / 1000.0)
            self._obs_store[target_desc] = bbox
        self._emit("observation", detail=f"locate:{'found' if found else 'miss'}",
                   context={"observer": "vlm_vision", "target": target_desc,
                            "confidence": data.get("confidence"),
                            "screen_x": bbox[0] if bbox else None,
                            "screen_y": bbox[1] if bbox else None})
        return bbox

    # ---------- 执行（ActionIntent） ----------

    def execute(self, intent: ActionIntent):
        """执行动作意图。坐标不进入 intent：位置来自实体观测记录（executor 解析）。

        异常 = 可观测失败（executor_exception → fail_recorded F1），禁止黑盒崩溃。
        """
        from runtime.input.base import InputResult
        backend = self.driver.input
        delay = self.naturalness.click_delay()
        time.sleep(delay)
        try:
            if intent.method == "template":
                result = self._execute_template(intent)
            elif intent.method == "vlm_bbox":
                result = self._execute_vlm_bbox(intent)
            else:
                result = backend.execute(intent)
        except Exception as e:
            result = InputResult(success=False, action=intent.action, backend="march7th",
                                 error=f"executor_exception:{type(e).__name__}:{e}")
        self._emit("action_executed", detail=f"{intent.action}:{intent.target}",
                   context={"naturalized": True, "delay_ms": int(delay * 1000),
                            **intent.to_context(), **result.to_context()})
        if not result.success:
            self._record_failure(intent, result, category="F1")
        return result.success

    def _execute_template(self, intent):
        from runtime.input.base import InputResult
        path = self.resolve_template(intent.target)
        if path is None:
            return InputResult(success=False, action=intent.action, backend="march7th",
                               error=f"unknown_entity:{intent.target}")
        params = intent.params
        ok = bool(self.driver.input.auto.click_element(
            path, "image", params.get("threshold", 0.85),
            max_retries=params.get("max_retries", 3)))
        return InputResult(success=ok, action="click_template", backend="march7th",
                           error=None if ok else "click_element_failed")

    def _execute_vlm_bbox(self, intent):
        from runtime.input.base import InputResult
        obs = self._obs_store.get(intent.target)
        if obs is None:
            return InputResult(success=False, action=intent.action, backend="march7th",
                               error=f"no_observation:{intent.target}")
        if len(obs) == 2:
            nx, ny = obs
        elif len(obs) == 4:
            x1, y1, x2, y2 = obs
            nx, ny = (x1 + x2) / 2, (y1 + y2) / 2
        else:
            return InputResult(success=False, action=intent.action, backend="march7th",
                               error=f"invalid_bbox_format:{len(obs)}")
        px, py = self.driver.vision.to_absolute(nx, ny)
        return self.driver.input.click(px, py)

    def _record_failure(self, intent, result, category):
        self._emit("fail_recorded", detail=f"{category}:{intent.action}:{intent.target}",
                   context={"category": category, "target": intent.target,
                            "error": result.error,
                            "related_events": list(self._recent_events[-8:])})

    # ---------- 便捷包装（调用方免构造 intent） ----------

    def interact_template(self, entity_id, threshold=0.85, max_retries=3):
        """entity_id = 世界实体 id（chest_A），模板解析在本层完成。"""
        return self.execute(ActionIntent(
            action="interact", target=entity_id, method="template",
            params={"threshold": threshold, "max_retries": max_retries},
            reason="objective_interact"))

    def click_text(self, text, include=True, max_retries=3, crop=None):
        return self.execute(ActionIntent(
            action="click_text", target=text, method="text",
            params={"include": include, "max_retries": max_retries, "crop": crop},
            reason="objective_ui"))

    def click_vlm_entity(self, entity_id):
        """按世界实体 id 点击：位置取自该实体的最近观测记录。"""
        return self.execute(ActionIntent(
            action="interact", target=entity_id, method="vlm_bbox",
            reason="objective_interact_vlm"))

    def move_visual_guided(self, target_desc, ticks, step_seconds):
        for i in range(ticks):
            pos = self.locate_target(target_desc)
            if pos is None:
                break
            x, y = pos
            dur = self.naturalness.sprint_duration(step_seconds)
            if 0.4 < x < 0.6:
                self.driver.input.press_key("w", wait_time=dur)
                self._emit("action_executed", detail=f"move_forward:{dur:.1f}s",
                           context={"naturalized": True, "tick": i})
            else:
                side = "d" if x < 0.5 else "a"
                self.driver.input.press_key(side, wait_time=self.naturalness.rotate_duration())
                self._emit("action_executed", detail=f"steer:{side}",
                           context={"naturalized": True, "tick": i})
        return True

    def portal_transition(self, portal, wait_base):
        trigger = portal["trigger"]
        ok = self.interact_template(portal["id"], trigger["threshold"])
        if not ok:
            return False
        wait = self.naturalness.transition_wait(wait_base)
        time.sleep(wait)
        return True

    def verify_signal(self, template, expected, timeout):
        vision = self.driver.vision
        deadline = time.time() + timeout
        delay = 0.2
        while time.time() < deadline:
            found = vision.find_template(str(self.pkg.templates_dir / template), 0.8) is not None
            if (expected == "vanished" and not found) or (expected == "present" and found):
                return True
            time.sleep(delay)
            delay = min(delay * 1.5, 1.5)
        return False
