import time
from pathlib import Path

from runtime.decision.action import ActionIntent, ActionMethod
from runtime.execution import ExecutionResult
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
    ("low_confidence", "F2_COORD"),
    ("stale_observation", "F2_COORD"),
    ("verify_timeout", "F2_TIMEOUT"),
]

# permanent 失败（#49：#31 的 retryable=False）——重试无意义，直接失败
PERMANENT_MARKERS = (
    "unknown_entity", "unknown_method", "invalid_bbox_format",
    "no_observation", "low_confidence", "stale_observation",
    "executor_exception", "uipi_block", "gate_blocked",
)

# 观测时效（#39）：超过该秒数的 bbox 视为过期，拒绝执行
OBS_MAX_AGE = 1.5
# 观测置信度下限（#40）：低于此值拒绝执行
OBS_MIN_CONFIDENCE = 0.6


def subclass_for(error):
    if not error:
        return None
    for key, sub in FAILURE_SUBCLASSES:
        if key in error:
            return sub
    return None


def retryable_for(error):
    """#49 恢复策略：permanent 失败不重试（模板缺/权限/低置信），transient 重试。"""
    if not error:
        return True
    return not any(m in error for m in PERMANENT_MARKERS)


class RealExecutor:
    """真机执行器：基于 March7th Driver（v0.12.1）。

    决策层只产 ActionIntent（不携带坐标）；VLM 定位坐标经 ObservationStore
    进入执行层（#29：executor 不依赖 observer 模块），换算属于执行细节。
    """

    def __init__(self, pkg, bus=None, execution_id=None, use_vlm=True, natural_mode=True):
        self.pkg = pkg
        self.bus = bus
        self.execution_id = execution_id
        self.naturalness = NaturalnessPolicy()
        self.natural_mode = natural_mode   # #44：False 时确定性（delay=0，测试可复现）
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

    def emergency_stop(self):
        """#42：紧急停止——esc 打断当前交互 + 兜底释放可能卡住的按键。"""
        try:
            self.driver.input.press_key("esc", wait_time=0.3)
        except Exception:
            pass
        for k in ("w", "a", "s", "d", "shift"):
            try:
                self.driver.input.release_key(k)
            except Exception:
                pass

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
        conf = data.get("confidence")
        bbox = None
        if found and x and y:
            bbox = (float(x) / 1000.0, float(y) / 1000.0)
            self.obs_store.set(target_desc, bbox, confidence=conf,
                               frame_id=Path(shot).name)
        self._emit("observation", detail=f"locate:{'found' if found else 'miss'}",
                   context={"observer": "vlm_vision", "target": target_desc,
                            "confidence": conf,
                            "screen_x": bbox[0] if bbox else None,
                            "screen_y": bbox[1] if bbox else None})
        return bbox

    # ---------- 执行（ActionIntent） ----------

    def execute(self, intent: ActionIntent) -> ExecutionResult:
        """执行动作意图，返回 ExecutionResult（#31：bool 丢失错误上下文）。

        - #45：intent 填充 execution_id，事件/失败可关联
        - 异常 = 可观测失败（executor_exception），禁止黑盒崩溃
        - #44：natural_mode=False 时确定性（delay=0）
        """
        from runtime.input.base import InputResult
        intent.execution_id = self.execution_id
        backend = self.driver.input
        delay = (self.naturalness.click_delay() if self.natural_mode else 0.0) \
            if intent.action in INPUT_ACTIONS else 0.0
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
                   context={"naturalized": self.natural_mode,
                            "delay_ms": int(delay * 1000),
                            **intent.to_context(), **result.to_context()})
        if not result.success:
            self._record_failure(intent, result)
        return self._to_result(intent, result)

    @staticmethod
    def _to_result(intent, result) -> ExecutionResult:
        sub = subclass_for(result.error)
        cat = sub or "F1"
        return ExecutionResult(
            success=result.success,
            error=result.error,
            retryable=retryable_for(result.error) if intent.idempotent else False,
            category=cat,
        )

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
        # #39：过期观测拒绝（角色可能已移动，旧坐标不可信）
        if obs.is_stale(max_age=OBS_MAX_AGE):
            return InputResult(success=False, action=intent.action, backend="march7th",
                               error=f"stale_observation:{intent.target}")
        # #40：低置信观测拒绝（VLM 猜测不构成执行依据）
        if obs.confidence is not None and obs.confidence < OBS_MIN_CONFIDENCE:
            return InputResult(success=False, action=intent.action, backend="march7th",
                               error=f"low_confidence:{obs.confidence:.2f}")
        bbox = obs.bbox
        if len(bbox) == 2:
            nx, ny = bbox
        elif len(bbox) == 4:
            x1, y1, x2, y2 = bbox
            nx, ny = (x1 + x2) / 2, (y1 + y2) / 2
        else:
            return InputResult(success=False, action=intent.action, backend="march7th",
                               error=f"invalid_bbox_format:{len(bbox)}")
        px, py = self.driver.vision.to_absolute(nx, ny)
        return self.driver.input.click(px, py)

    def _record_failure(self, intent, result):
        # #30：按 result.error 特征细分子分类（保持 F1/F2/F3 主类冻结）
        sub = subclass_for(result.error)
        cat = sub or "F1"
        ctx = {"category": cat, "target": intent.target,
               "error": result.error,
               "related_events": list(self._recent_events[-8:])}
        # #46：失败瞬间截图快照（真机可用时；mock 下 driver 无 vision 则跳过）
        try:
            if self.driver.vision is not None:
                frame = self.driver.vision.screenshot_path("failure_reports/frames")
                ctx["frame"] = str(frame)
        except Exception:
            pass
        self._emit("fail_recorded", detail=f"{cat}:{intent.action}:{intent.target}",
                   context=ctx)

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
        """#16：点击成功 ≠ 传送成功——click → wait → verify_signal 三步缺一不可。

        #25：无 verify_template 时回退通用 loading 信号（模板存在才校验）。
        """
        trigger = portal["trigger"]
        result = self.interact_template(portal["id"], trigger["threshold"])
        if not result.success:
            return False
        wait = self.naturalness.transition_wait(wait_base)
        time.sleep(wait)
        vtmpl = trigger.get("verify_template") or "loading.png"
        if self.pkg.template_exists(vtmpl):
            return self.verify_signal(vtmpl, "vanished", verify_timeout)
        return True

    def verify_signal(self, template, expected, timeout, threshold=0.8):
        """#24：template 必须解析在 templates_dir 内（防知识包路径穿越）。"""
        tpl = self._resolve_template_path(template)
        if tpl is None:
            return False
        vision = self.driver.vision
        deadline = time.time() + timeout
        delay = 0.2
        while time.time() < deadline:
            # #17：阈值参数化（默认 0.8，后续可配置化），不硬编码
            found = vision.find_template(str(tpl), threshold) is not None
            if (expected == "vanished" and not found) or (expected == "present" and found):
                return True
            time.sleep(delay)
            delay = min(delay * 1.5, 1.5)
        return False

    def _resolve_template_path(self, template):
        """模板名 → templates_dir 内绝对路径；越界/不存在返回 None。"""
        try:
            candidate = (self.pkg.templates_dir / template).resolve()
        except Exception:
            return None
        if self.pkg.templates_dir.resolve() not in candidate.parents:
            return None
        return candidate
