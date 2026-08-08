import time
from pathlib import Path

from runtime.decision.action import ActionIntent, ActionMethod
from runtime.naturalness import NaturalnessPolicy
from runtime.observation_store import ObservationStore
from runtime.observers.vlm_vision import VLMVisionObserver

M7_ROOT = Path(__file__).resolve().parent.parent.parent / "March7thAssistant"

# 只对这些动作执行自然性 sleep（#27）：查询/verify/noop 不应人为等待
INPUT_ACTIONS = {"interact", "click_text", "move", "click"}

# 失败子分类（#30）：保持 F1/F2/F3 主类（v0.12.1 冻结），后缀细化供训练/分析
FAILURE_SUBCLASSES = [
    ("uipi", "F1_PERMISSION"),
    ("admin", "F1_PERMISSION"),
    ("executor_exception", "F1_EXEC"),
    ("unknown_method", "F1_INTERNAL"),
    ("unknown_entity", "F1_TEMPLATE"),
    ("click_element_failed", "F1_TEMPLATE"),
    ("click_text_failed", "F1_TEMPLATE"),
    ("no_observation", "F2_COORD"),
    ("invalid_bbox_format", "F2_COORD"),
    ("click", "F2_COORD"),
]


def subclass_for(error):
    if not error:
        return None
    for key, sub in FAILURE_SUBCLASSES:
        if key in error:
            return sub
    return None


class RealExecutor:
    """真机执行器：基于 March7th Driver（v0.12.1）。

    决策层只产 ActionIntent（不携带坐标）；VLM 定位坐标经 ObservationStore
    进入执行层（#29：executor 不依赖 observer 模块），换算属于执行细节。
    """

    def __init__(self, pkg, bus=None, execution_id=None, use_vlm=True):
        self.pkg = pkg
        self.bus = bus
        self.execution_id = execution_id
        self.naturalness = NaturalnessPolicy()
        self.vlm = VLMVisionObserver() if use_vlm else None
        self.obs_store = ObservationStore()
        self._driver = None
        self._entity_templates = None
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
        """世界实体 id → 模板路径（executor 层解析，intent 不携带模板名）。

        防路径穿越（#13）：只允许纯文件名（Path.name 白名单化），
        实体 id 来自知识包映射而非自由输入。
        """
        name = self.entity_templates().get(entity_id)
        if not name:
            return None
        name = Path(name).name
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
            self.obs_store.set(target_desc, bbox)
        self._emit("observation", detail=f"locate:{'found' if found else 'miss'}",
                   context={"observer": "vlm_vision", "target": target_desc,
                            "confidence": data.get("confidence"),
                            "screen_x": bbox[0] if bbox else None,
                            "screen_y": bbox[1] if bbox else None})
        return bbox

    # ---------- 执行（ActionIntent） ----------

    def execute(self, intent: ActionIntent):
        """执行动作意图。坐标不进入 intent：位置来自观测记录（executor 解析）。

        异常 = 可观测失败（executor_exception → fail_recorded），禁止黑盒崩溃。
        #27：只对输入类动作做自然性 sleep，查询/verify 不人为等待。
        """
        from runtime.input.base import InputResult
        backend = self.driver.input
        delay = self.naturalness.click_delay() if intent.action in INPUT_ACTIONS else 0.0
        time.sleep(delay)
        try:
            if intent.method == ActionMethod.TEMPLATE.value:
                result = self._execute_template(intent)
            elif intent.method == ActionMethod.VLM_BBOX.value:
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
        # #11：action 保持 intent 语义，backend 方法记录在 method 字段，不污染 action
        return InputResult(success=ok, action=intent.action, backend="march7th",
                           method="template",
                           error=None if ok else "click_element_failed")

    def _execute_vlm_bbox(self, intent):
        from runtime.input.base import InputResult
        obs = self.obs_store.get(intent.target)
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
        # #30：按 result.error 特征细分子分类（保持 F1/F2/F3 主类冻结）
        sub = subclass_for(result.error)
        cat = f"{category}_{sub[3:]}" if sub and sub.startswith(category) else (sub or category)
        self._emit("fail_recorded", detail=f"{cat}:{intent.action}:{intent.target}",
                   context={"category": cat, "target": intent.target,
                            "error": result.error,
                            "related_events": list(self._recent_events[-8:])})

    # ---------- 便捷包装（调用方免构造 intent） ----------

    def interact_template(self, entity_id, threshold=0.85, max_retries=3):
        """entity_id = 世界实体 id（chest_A），模板解析在本层完成。

        #12：intent 是系统边界，非法实体（None/空）不得进入。
        """
        if not entity_id:
            return False
        return self.execute(ActionIntent(
            action="interact", target=entity_id, method=ActionMethod.TEMPLATE.value,
            params={"threshold": threshold, "max_retries": max_retries},
            reason="objective_interact"))

    def click_text(self, text, include=True, max_retries=3, crop=None):
        if not text:
            return False
        return self.execute(ActionIntent(
            action="click_text", target=text, method=ActionMethod.TEXT.value,
            params={"include": include, "max_retries": max_retries, "crop": crop},
            reason="objective_ui"))

    def click_vlm_entity(self, entity_id):
        """按世界实体 id 点击：位置取自该实体的最近观测记录。"""
        return self.execute(ActionIntent(
            action="interact", target=entity_id, method=ActionMethod.VLM_BBOX.value,
            reason="objective_interact_vlm"))

    def move_visual_guided(self, target_desc, ticks, step_seconds, threshold=0.8):
        """VLM 短步移动：#14 方向修正（目标在左 → 左转 a），#15 收敛判断。"""
        for i in range(ticks):
            pos = self.locate_target(target_desc)
            if pos is None:
                break
            x, y = pos
            # 收敛：目标已在屏幕中央附近 → 停（避免撞墙/来回）
            if abs(x - 0.5) < 0.05 and abs(y - 0.5) < 0.15:
                break
            dur = self.naturalness.sprint_duration(step_seconds)
            if abs(x - 0.5) < 0.1:
                self.driver.input.press_key("w", wait_time=dur)
                self._emit("action_executed", detail=f"move_forward:{dur:.1f}s",
                           context={"naturalized": True, "tick": i})
            else:
                side = "a" if x < 0.5 else "d"  # 目标在左 → 左转
                self.driver.input.press_key(side, wait_time=self.naturalness.rotate_duration())
                self._emit("action_executed", detail=f"steer:{side}",
                           context={"naturalized": True, "tick": i})
        return True

    def portal_transition(self, portal, wait_base, threshold=0.8, verify_timeout=10):
        """#16：点击成功 ≠ 传送成功——click → wait → verify_signal 三步缺一不可。"""
        trigger = portal["trigger"]
        ok = self.interact_template(portal["id"], trigger["threshold"])
        if not ok:
            return False
        wait = self.naturalness.transition_wait(wait_base)
        time.sleep(wait)
        vtmpl = trigger.get("verify_template")
        if vtmpl:
            return self.verify_signal(vtmpl, "present", verify_timeout)
        return True

    def verify_signal(self, template, expected, timeout, threshold=0.8):
        vision = self.driver.vision
        deadline = time.time() + timeout
        delay = 0.2
        while time.time() < deadline:
            # #17：阈值参数化（默认 0.8，后续可配置化），不硬编码
            found = vision.find_template(str(self.pkg.templates_dir / template), threshold) is not None
            if (expected == "vanished" and not found) or (expected == "present" and found):
                return True
            time.sleep(delay)
            delay = min(delay * 1.5, 1.5)
        return False
