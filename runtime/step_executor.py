import time
from collections import deque
from pathlib import Path

from runtime.action_intent import ActionIntent, ActionMethod, ActionType
from runtime.errors import (ErrorCode, PERMANENT_CODES, SUBCLASS_BY_CODE,
                            code_of)
from runtime.execution import ExecutionResult
from runtime.naturalness import NaturalnessPolicy
from runtime.observation_store import ObservationStore
from runtime.observers.vlm_vision import VLMVisionObserver

ROOT = Path(__file__).resolve().parent.parent.parent

# 只对这些动作执行自然性 sleep（#27）：查询/verify/noop 不应人为等待
INPUT_ACTIONS = {"interact", "click_text", "move", "click"}

# 失败子分类（#30）：保持 F1/F2/F3 主类（v0.12.1 冻结），后缀细化供训练/分析
FAILURE_SUBCLASSES = [
    ("uipi", "F6_PRIVILEGE"),
    ("admin", "F6_PRIVILEGE"),
    ("observe_only", "F6_PRIVILEGE"),  # #42-B7：降级模式归权限类（非 F1 输入失败）
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
    "observe_only",  # #20-9：降级模式失败为永久（重试无意义，等待权限恢复）
)

# #19 RecoveryPolicy：失败 → 恢复建议（轻量版，供 orchestrator/GUI 决策）
# 键 = 失败特征子串；值 = 建议动作（reobserve / alternative / retry / abort）
RECOVERY_POLICY = [
    ("no_observation", "reobserve"),
    ("stale_observation", "reobserve"),
    ("low_confidence", "reobserve"),
    ("click_element_failed", "alternative"),
    ("click_text_failed", "alternative"),
    ("unknown_entity", "abort"),
    ("unknown_method", "abort"),
    ("uipi_block", "abort"),
    ("gate_blocked", "abort"),
]


def recovery_for(error):
    """#19：按失败特征给出恢复策略建议。

    BUG-051：优先走 ErrorCode 表（RECOVERY_BY_CODE——稳定契约）；
    字符串子串表仅兜底 backend 外来文本。
    """
    if not error:
        return "retry"
    from runtime.errors import code_of, RECOVERY_BY_CODE
    code = code_of(error)
    if code is not None and code in RECOVERY_BY_CODE:
        return RECOVERY_BY_CODE[code]
    for key, action in RECOVERY_POLICY:
        if key in error:
            return action
    return "retry"

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

    def __init__(self, pkg, bus=None, execution_id=None, use_vlm=True, natural_mode=True,
                 natural_seed=None, input_override=None, guard=None, abort_check=None,
                 min_action_interval=0.0):
        self.pkg = pkg
        self.bus = bus
        self.execution_id = execution_id
        # S13：seed 固定 → 同执行 id 下自然性延迟可复现（replay 不漂移）
        self.naturalness = NaturalnessPolicy(enabled=natural_mode, seed=natural_seed)
        self.natural_mode = natural_mode   # #44：False 时确定性（delay=0，测试可复现）
        self.vlm = VLMVisionObserver() if use_vlm else None
        self.obs_store = ObservationStore()
        self._driver = None
        # #20-9：输入后端注入点（ExecutionRouter 选中 / Replay / ObserveOnly）——
        # 默认 None = driver.input（March7th 真实后端）
        self._input_override = input_override
        # BUG-37：执行前中止检查（orchestrator 注入 emergency ∨ stall）
        self.abort_check = abort_check
        # BUG-50：输入节流（秒；0=关。真机建议 0.5/危险 2.0）
        self.min_action_interval = min_action_interval
        self._last_action_at = 0.0
        # Sprint B-2：执行前安全闸门（默认宽松：workflow 模板路径兼容；
        # observe_act 通道的已验证意图仍完整校验）
        if guard is None:
            from runtime.guards.action_guard import ActionGuard
            guard = ActionGuard(strict=False)
        self.guard = guard
        self._entity_templates = None
        self._recent_events = deque(maxlen=100)  # #5：deque 自限长，不随运行时间增长
        # #1：method → 处理器 registry（扩展定位方式=注册，不改 execute）
        # #17-C：白名单冻结——register_method 只接受核心 method，未来插件
        # 扩展须显式审计（防"知识包注册 shell"式入口污染）
        self._method_handlers = {
            ActionMethod.TEMPLATE.value: self._execute_template,
            ActionMethod.VLM_BBOX.value: self._execute_vlm_bbox,
            ActionMethod.TEXT.value: self._execute_text,
        }
        self._core_methods = frozenset(self._method_handlers)  # 冻结白名单

    @property
    def input(self):
        """当前输入后端：注入优先，否则 driver.input（March7th）。"""
        if self._input_override is not None:
            return self._input_override
        return self.driver.input

    def set_input_backend(self, backend):
        """#42-B6：正式注入接口（测试/路由用）——替代直接改私有字段。

        校验 Protocol 契约（Fake/真实后端签名漂移在注入期即炸）。
        """
        from runtime.input.base import InputBackendProtocol
        if backend is not None and not isinstance(backend, InputBackendProtocol):
            raise TypeError(f"输入后端未实现 InputBackendProtocol: {type(backend).__name__}")
        self._input_override = backend

    def register_method(self, name, handler):
        """#17-C：method 注册入口——白名单校验，未知/未审计 method 拒绝。"""
        if name not in self._core_methods:
            raise ValueError(
                f"method 不在核心白名单: {name}（允许: {sorted(self._core_methods)}，"
                f"插件扩展须先审计进 ALLOWED_METHODS）")
        self._method_handlers[name] = handler

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
            return ev
        return None

    def _precondition_blocked(self, intent):
        """S5 动作前验证钩子：intent.preconditions 为世界事实断言（如 room==black_tower）。

        当前断言源未接入（房间/战斗状态观测不可靠，真机未通），恒通过——
        接入点：从 ObservationStore 校验世界事实，失败返回原因字符串。
        """
        if not intent.preconditions:
            return None
        return None

    def emergency_stop(self):
        """#42：紧急停止——esc 打断当前交互 + 兜底释放可能卡住的按键。"""
        try:
            self.input.press_key("esc", wait_time=0.3)
        except Exception:
            pass
        for k in ("w", "a", "s", "d", "shift"):
            try:
                self.input.release_key(k)
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
        return self.driver.vision.screenshot_path(str(ROOT / "ingest/raw/frames/live"))

    def _capture_for_vlm(self):
        """#17-B2：截图真实性前置——VLM 不吃垃圾输入。

        take_screenshot 已记录 last_quality（#17-G 结构校验）；非 ok 时
        重截一次（前台切换/瞬时黑帧自愈），仍非 ok → 放弃观测（返回 None），
        VLM 永远只看到 quality=ok 的帧。
        """
        vision = getattr(self.driver, "vision", None)
        if vision is None:
            return None
        for _ in range(2):
            shot = vision.screenshot_path(str(ROOT / "ingest/raw/frames/live"))
            quality = getattr(vision, "last_quality", None)
            if quality is None or quality.quality == "ok":
                return shot
            self._emit("observation", detail="frame_rejected",
                       context={"observer": "frame_validator", "quality": quality.quality,
                                "reason": quality.reason})
        return None

    # ---------- 观测（observer 通道，不产决策） ----------

    def observe_room(self, room_ids):
        if self.vlm is None:
            return None, None
        shot = self._capture_for_vlm()
        if shot is None:
            return None, None
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
        shot = self._capture_for_vlm()
        if shot is None:
            return None  # 帧质量不合格 → 本次定位放弃（不把垃圾帧交给 VLM）
        data = self.vlm.locate_target(shot, target_desc)
        # BUG-21：locate 输出 schema 校验（found="yes"/缺 xy 等直接拒绝）
        from runtime.vision_observer import validate_vlm_output
        ok, _ = validate_vlm_output(data, kind="locate")
        if not ok:
            return None
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

    def execute_intent(self, intent: ActionIntent) -> ExecutionResult:
        """#20-7 协议入口：Planner 产出的意图 → 执行（零坐标，适配层转译）。

        WAIT 语义：不触 backend，直接成功（决策层等待占位）。
        #B-2：执行前 ActionGuard 安全闸门——已下沉至 execute()（全路径统一，
        interact_template 等便捷包装同样过闸，无绕过面）。
        """
        if intent.action == ActionType.WAIT.value or intent.action == ActionType.NONE.value:
            self._emit("action_executed", detail=f"wait:{intent.reason or 'none'}",
                       context={"naturalized": False, **intent.to_context()})
            return ExecutionResult(success=True, category="F2")
        return self.execute(intent)

    def _guard_blocked(self, intent, reason):
        """Sprint B.2：闸门拒绝统一出口（F4/F5 分离 + 证据上下文）。"""
        f5 = reason in ("ACTION_RISK_HIGH",)
        cat = "F5_ACTION_BLOCK" if f5 else "F4_VISION"
        code = ErrorCode.ACTION_BLOCKED if f5 else ErrorCode.VISION_UNTRUSTED
        self._emit("fail_recorded", detail=f"{cat}:{reason}:{intent.target}",
                   context={"category": cat, "target": intent.target,
                            "error": f"{code.value}:{reason}",
                            "failure_signature":
                                f"{cat}:{intent.action}:{intent.target}:{reason}",
                            "suggested_recovery": "reobserve",
                            "vision_confidence": intent.vision_confidence,
                            "evidence_id": intent.evidence_id,
                            "guard_reason": reason})
        return ExecutionResult(success=False, error=f"action_blocked:{reason}"
                               if f5 else f"vision_guard:{reason}",
                               retryable=False, category=cat, code=code)

    # ---------- 执行（ActionIntent） ----------

    def execute(self, intent: ActionIntent) -> ExecutionResult:
        """执行动作意图，返回 ExecutionResult（#31：bool 丢失错误上下文）。

        - #45：intent 填充 execution_id，事件/失败可关联
        - 异常 = 可观测失败（executor_exception），禁止黑盒崩溃
        - #44：natural_mode=False 时确定性（delay=0）
        - Sprint B.2：ActionGuard 前置——所有执行路径（含便捷包装）统一过闸，
          无绕过面；宽松模式对无证明意图放行（workflow 模板路径），
          已验证意图按完整校验。
        """
        allowed, reason = self.guard.allow(intent)
        if not allowed:
            return self._guard_blocked(intent, reason)
        # BUG-37：紧急暂停竞态——gate PASS 与 click 之间可能触发 emergency
        #（T0 视觉 PASS → T1 EmergencyMonitor 置位 → T2 仍点击）。
        if self.abort_check is not None and self.abort_check():
            self._emit("fail_recorded",
                       detail=f"F3:aborted:{intent.target}",
                       context={"category": "F3", "target": intent.target,
                                "error": "aborted_before_execute",
                                "suggested_recovery": "retry"})
            return ExecutionResult(success=False, error="aborted_before_execute",
                                   retryable=True, category="F3")
        # BUG-50：输入节流——VLM/OCR 抖动导致的连点保护（默认关，真机开启）
        # BUG-050：按风险加权——high/critical 动作间隔更长（防连续高风险操作）
        if self.min_action_interval > 0:
            risk_weight = {"low": 1.0, "medium": 1.5,
                           "high": 3.0, "critical": 5.0}.get(
                               getattr(intent, "risk", "low"), 1.0)
            interval = self.min_action_interval * risk_weight
            wait = self._last_action_at + interval - time.time()
            if wait > 0:
                time.sleep(wait)
        self._last_action_at = time.time()
        from runtime.input.base import InputResult
        backend = self.input
        blocked = self._precondition_blocked(intent)  # S5：动作前验证
        if blocked:
            self._emit("fail_recorded", detail=f"F3:precondition:{intent.target}",
                       context={"category": "F3", "target": intent.target,
                                "error": f"precondition:{blocked}"})
            return ExecutionResult(success=False, error=f"precondition:{blocked}",
                                   retryable=False, category="F3")
        delay = (self.naturalness.click_delay() if self.natural_mode else 0.0) \
            if intent.action in INPUT_ACTIONS else 0.0
        time.sleep(delay)
        monitor = getattr(self, "monitor", None)
        if monitor is not None and intent.action in INPUT_ACTIONS:
            # 自伤防护：机器人自身的光标移动不能被 EmergencyMonitor 判为"用户介入"
            monitor.suspend_mouse()
        try:
            try:
                # #1：method 分派查表（registry）——新增定位方式不改 execute 本体
                handler = self._method_handlers.get(intent.method)
                if handler is not None:
                    result = handler(intent)
                else:
                    result = backend.execute(intent)
            except Exception as e:
                result = InputResult(success=False, action=intent.action, backend="march7th",
                                     error=f"executor_exception:{type(e).__name__}:{e}")
        finally:
            if monitor is not None and intent.action in INPUT_ACTIONS:
                monitor.resume_mouse()
        self._emit("action_executed", detail=f"{intent.action}:{intent.target}",
                   context={"naturalized": self.natural_mode,
                            "delay_ms": int(delay * 1000),
                            **intent.to_context(), **result.to_context()})
        if not result.success:
            self._record_failure(intent, result)
        return self._to_result(intent, result)

    @staticmethod
    def _to_result(intent, result) -> ExecutionResult:
        # #17-A：code 优先判定（枚举契约），子串表仅兜底 backend 外来文本
        code = code_of(result.error)
        if code is not None and code is not ErrorCode.UNKNOWN:
            sub = SUBCLASS_BY_CODE.get(code)
            retryable = (code not in PERMANENT_CODES) if intent.idempotent else False
        else:
            sub = subclass_for(result.error)
            retryable = retryable_for(result.error) if intent.idempotent else False
        cat = sub or "F1"
        return ExecutionResult(
            success=result.success,
            error=result.error,
            retryable=retryable,
            category=cat,
            code=code if code is not None and code is not ErrorCode.UNKNOWN else None,
        )

    def _execute_template(self, intent):
        from runtime.input.base import InputResult
        path = self.resolve_template(intent.target)
        if path is None:
            return InputResult(success=False, action=intent.action, backend="march7th",
                               error=f"unknown_entity:{intent.target}")
        params = intent.params
        # #5：模板路径/阈值进 result detail——复盘时知道点了哪个模板什么阈值
        result = self.input.click_template(
            path, params.get("threshold", 0.60), params.get("max_retries", 3),
            scale_range=params.get("scale_range"))
        result.detail.update({"template": str(path),
                              "threshold": params.get("threshold", 0.60)})
        # 借鉴 March7th 路线机制：模板未命中（视频帧整帧模板对当前画面
        # 实测全部 <0.54）→ 按知识包实体点位归一化坐标兜底点击——
        # 宝箱是固定地图点位，坐标点击即 m7 的"界面图+固定坐标"路线。
        # 仅"未命中"走兜底（点击失败/权限问题不兜底——换坐标无意义）。
        if not result.success and result.error == "click_element_failed":
            pos = self.pkg.entity_position(intent.target)
            if pos is not None:
                try:
                    px, py = self.driver.vision.to_absolute(*pos)
                except Exception:
                    px = py = None
                if px and py and px > 0 and py > 0:
                    r2 = self._click_with_diff_verify(px, py, intent.target, str(path))
                    if r2.success:
                        r2.detail.update(
                            {"fallback": "entity_position",
                             "nx": pos[0], "ny": pos[1],
                             "template": str(path)})
                        return r2
                    # 坐标兜底也失败：失败上下文留档（复盘可区分
                    # "模板失败"与"坐标兜底也失败"两条独立失败链）
                    r2.detail.update(
                        {"fallback_attempted": "entity_position",
                         "nx": pos[0], "ny": pos[1],
                         "template": str(path)})
                    return r2
        return result

    def _click_with_diff_verify(self, cx, cy, target, template, max_rounds=3,
                                wait_seconds=0.8):
        """点击 + 像素差分验证（借鉴 GameCLI-Agent：点击后画面变化检测 +
        nudge 微调重试）。

        SendInput 成功 ≠ 游戏响应——星铁动画多/反馈延迟，点偏/被挡时
        画面不变。点击前截图 → 点击 → 等待 → 差分：变化 → 成功；
        未变化 → nudge 偏移坐标重试（最多 max_rounds 轮）。
        返回 InputResult。
        """
        from runtime.input.base import InputResult
        from runtime.pixel_diff import images_different, nudge_offsets
        vision = getattr(getattr(self, "driver", None), "vision", None)
        if vision is None:
            return self.input.click(cx, cy)  # 无视觉 → 退化为普通点击
        try:
            shot0 = vision.take_screenshot()
            before = shot0[0] if shot0 else None
        except Exception:
            before = None
        if before is None:
            return self.input.click(cx, cy)
        r = self.input.click(cx, cy)
        if not r.success:
            return r
        import time
        time.sleep(wait_seconds)
        try:
            shot1 = vision.take_screenshot()
            after = shot1[0] if shot1 else None
        except Exception:
            after = None
        changed, ratio = images_different(before, after) if after else (False, 0.0)
        if changed:
            r.detail.update({"diff_verified": True, "diff_ratio": ratio})
            return r
        # 未变化 → nudge 微调重试（8 方向递增偏移）
        for dx, dy in nudge_offsets():
            if dx == 0 and dy == 0:
                continue
            r2 = self.input.click(cx + dx, cy + dy)
            if not r2.success:
                continue
            time.sleep(wait_seconds)
            try:
                shot2 = vision.take_screenshot()
                after2 = shot2[0] if shot2 else None
            except Exception:
                after2 = None
            changed2, ratio2 = images_different(before, after2) if after2 else (False, 0.0)
            if changed2:
                r2.detail.update({"diff_verified": True, "diff_ratio": ratio2,
                                  "nudged": (dx, dy)})
                return r2
        r.detail.update({"diff_verified": False, "diff_ratio": ratio,
                         "nudge_exhausted": True})
        return r

    def _execute_text(self, intent):
        """text 定位专用路径（与 template/vlm_bbox 对称，不依赖 backend 自定义 execute）。"""
        return self.input.click_text(
            intent.target,
            intent.params.get("include", True),
            intent.params.get("max_retries", 3),
            intent.params.get("crop"))

    def _execute_vlm_bbox(self, intent):
        from runtime.input.base import InputResult
        # BUG-070：统一有效观测入口（时效+置信内置——业务层不再裸 get）
        obs = self.obs_store.get_valid(intent.target, max_age=OBS_MAX_AGE,
                                       min_confidence=OBS_MIN_CONFIDENCE)
        if obs is None:
            return InputResult(success=False, action=intent.action, backend="march7th",
                               error=f"no_valid_observation:{intent.target}")
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
        # #35：坐标越界保护——VLM 返回 50000/-100 时禁止点击（防危险区域）
        if px <= 0 or py <= 0 or px > 20000 or py > 20000:
            return InputResult(success=False, action=intent.action, backend="march7th",
                               error=f"invalid_bbox_format:out_of_bounds:{px},{py}")
        # #17-E：点击前二次验证钩子——obs.frame_id 与当前帧一致才允许点击
        # （observe → click 之间的窗口期漂移检测；VLM 帧计数器接入后启用，
        # 默认恒过，与 S5 preconditions 相同的"契约先行"模式）
        if not self._pre_click_verify(intent, obs):
            return InputResult(success=False, action=intent.action, backend="march7th",
                               error=f"stale_observation:{intent.target}:frame_changed")
        return self.input.click(px, py)

    @staticmethod
    def _pre_click_verify(intent, obs):
        """#17-E：观察-动作原子性钩子。默认放行；接入帧校验后：
        对比 obs.frame_id 与当前帧 id，不一致 → 返回 False 强制重新 observe。"""
        return True

    def _record_failure(self, intent, result):
        # #30：按 result.error 特征细分子分类（保持 F1/F2/F3 主类冻结）
        sub = subclass_for(result.error)
        cat = sub or "F1"
        # #31 失败指纹：同因失败可聚合（统计/去重）
        # BUG-059：指纹用稳定字段（code 优先，error 文本不可靠——
        # 文案变化会拆散同类失败）；text 仅作展示后缀
        from runtime.errors import code_of
        # result 可能是 ExecutionResult 或 InputResult（无 code 属性）——getattr 防御
        code_val = getattr(result, "code", None)
        if code_val is not None and hasattr(code_val, "value"):
            code_val = code_val.value
        elif code_val is None and result.error:
            code_val = code_of(result.error).value
        else:
            code_val = code_val or "unknown"
        signature = f"{cat}:{intent.action}:{intent.target}:{code_val}"
        ctx = {"category": cat, "target": intent.target,
               "error": result.error,
               "error_code": code_val,
               "failure_signature": signature,
               "suggested_recovery": recovery_for(getattr(result, "code", None) or result.error),  # #19/BUG-058
               "related_events": list(self._recent_events)[-8:]}
        # #46：失败瞬间截图快照（真机可用时；mock 下 driver 无 vision 则跳过）
        # BUG-031：截图失败不静默——保留错误证据（不阻断主流程）
        # 隐藏 Bug 审查：失败帧目录无限累积（24h 挂机磁盘增长）——保留最近 200 张
        try:
            if self.driver.vision is not None:
                frame = self.driver.vision.screenshot_path(str(ROOT / "failure_reports/frames"))
                ctx["frame"] = str(frame)
                try:
                    from pathlib import Path
                    fdir = Path(frame).parent
                    shots = sorted(fdir.glob("shot_*.jpg"))
                    for old in shots[:-200]:
                        old.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception as e:
            import logging
            logging.getLogger("runtime.step_executor").warning(
                "失败现场截图失败: %s", e, exc_info=True)
            ctx["frame_error"] = f"{type(e).__name__}: {e}"
        self._emit("fail_recorded", detail=f"{cat}:{intent.action}:{intent.target}",
                   context=ctx)

    # ---------- 便捷包装（调用方免构造 intent） ----------

    def interact_template(self, entity_id, threshold=0.60, max_retries=3):
        """entity_id = 世界实体 id（chest_A），模板解析在本层完成。

        #12：intent 是系统边界，非法实体（None/空）不得进入。
        """
        if not entity_id:
            return ExecutionResult(success=False, error="interact:no_entity",
                                   retryable=False, category="F3")
        return self.execute(ActionIntent(
            action="interact", target=entity_id, method=ActionMethod.TEMPLATE.value,
            params={"threshold": threshold, "max_retries": max_retries},
            reason="objective_interact", execution_id=self.execution_id))

    def click_text(self, text, include=True, max_retries=3, crop=None):
        if not text:
            return ExecutionResult(success=False, error="click_text:no_text",
                                   retryable=False, category="F3")
        return self.execute(ActionIntent(
            action="click_text", target=text, method=ActionMethod.TEXT.value,
            params={"include": include, "max_retries": max_retries, "crop": crop},
            reason="objective_ui", execution_id=self.execution_id))

    def move_visual_guided(self, target_desc, ticks, step_seconds, threshold=0.8,
                           abort_check=None) -> ExecutionResult:
        """VLM 短步移动：#14 方向修正（目标在左 → 左转 a），#15 收敛判断。

        #42：不再无条件 True——目标从未被定位 → 失败（F2_COORD），
        状态机不会被假成功污染。
        """
        located = 0
        last_x = None
        stuck = 0
        forward_sec = 0.0
        steer_count = 0
        reached_center = False  # BUG-025：收敛才是成功条件（located>0 不够）
        for i in range(ticks):
            if abort_check and abort_check():
                return ExecutionResult(success=False, error="move_aborted",
                                       retryable=True, category="F2")
            pos = self.locate_target(target_desc)
            if pos is None:
                continue
            located += 1
            x, y = pos
            # 收敛：目标已在屏幕中央附近 → 停（避免撞墙/来回）
            if abs(x - 0.5) < 0.05 and abs(y - 0.5) < 0.15:
                reached_center = True
                break
            # #9 stuck 检测：连续多 tick 目标横向位置几乎不动（撞墙/被挡）→ 失败
            if last_x is not None and abs(x - last_x) < 0.01:
                stuck += 1
                if stuck >= 3:
                    return ExecutionResult(success=False, error="move_stuck",
                                           retryable=True, category="F2_COORD")
            else:
                stuck = 0
            last_x = x
            dur = self.naturalness.sprint_duration(step_seconds)
            # BUG-026：y 参与决策——目标明显在上方（远）→ 前进逼近；
            # 否则按横向偏移转向（第三人称机制：横向 steering + 前进）
            if abs(x - 0.5) < 0.1 and (y - 0.5) > -0.25:
                result = self.input.press_key("w", wait_time=dur)
                # BUG-024：输入失败必须中断移动（W 失败仍继续 = 假成功）
                if not result.success:
                    return ExecutionResult(
                        success=False, error=result.error or "move_input_failed",
                        retryable=True, category="F1_EXEC")
                forward_sec += dur
            else:
                side = "a" if x < 0.5 else "d"  # 目标在左 → 左转
                result = self.input.press_key(side, wait_time=self.naturalness.rotate_duration())
                if not result.success:  # BUG-024
                    return ExecutionResult(
                        success=False, error=result.error or "move_input_failed",
                        retryable=True, category="F1_EXEC")
                steer_count += 1
        # #17-H：move 事件聚合——长移动只发一条 summary，不刷 tick 风暴
        self._emit("move_completed",
                   detail=f"move:{target_desc}",
                   context={"ticks": ticks, "located": located,
                            "reached_center": reached_center,
                            "forward_seconds": round(forward_sec, 2),
                            "steer_count": steer_count})
        if located == 0:
            return ExecutionResult(success=False, error="no_observation",
                                   retryable=False, category="F2_COORD")
        if not reached_center:
            # BUG-025：tick 用尽但未收敛 → 失败（不再 located>0 即成功）
            return ExecutionResult(success=False, error="move_target_not_reached",
                                   retryable=True, category="F2_COORD")
        return ExecutionResult(success=True, category="F2")

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
        # BUG-023：无验证模板 → 失败（fail-closed）——假成功会带状态机
        # 进错误房间。显式声明 allow_unverified_transition=true 才放行。
        if trigger.get("allow_unverified_transition"):
            import logging
            logging.getLogger("runtime.step_executor").warning(
                "传送 %s 未验证（allow_unverified_transition=true 显式放行）", portal.get("id"))
            return True
        return ExecutionResult(
            success=False,
            error="portal_verify_template_missing",
            retryable=False,
            category="F2_VERIFY")

    def verify_signal(self, template, expected, timeout, threshold=0.8,
                      abort_check=None):
        """#24：template 必须解析在 templates_dir 内（防知识包路径穿越）。

        #41：阻塞循环每 tick 检查 abort_check（如 EmergencyMonitor.is_paused /
        session stop），为真立即返回 False——避免 30s 验证期间卡死主循环，
        心跳/监控全部失效。
        """
        tpl = self._resolve_template_path(template)
        if tpl is None:
            return False
        vision = self.driver.vision
        if vision is None:
            # 无视觉通道（observe_only 注入路径）→ 无法验证 = fail-closed
            return False
        deadline = time.time() + timeout
        delay = 0.2
        # 假阳性防御（视频帧整帧模板）：vanished 判定前先建立"命中基线"——
        # 帧模板恒不中 → vanished 恒真（无验证价值）。基线用探测窗口
        # （2s 内见过即真验证；窗口结束仍未见过 → 降级放行 + 证据留档）——
        # 避免"点击后画面立即变化"被首个 tick 误判为从未见过。
        baseline_seen = None  # None=探测中, True/False=定案
        baseline_deadline = time.time() + min(2.0, timeout / 3)
        while time.time() < deadline:
            if abort_check and abort_check():
                return False
            # #17：阈值参数化（默认 0.8，后续可配置化），不硬编码
            found = vision.find_template(str(tpl), threshold) is not None
            if baseline_seen is None:
                if found:
                    baseline_seen = True
                elif time.time() > baseline_deadline:
                    baseline_seen = False
            if expected == "vanished":
                # 基线定案前不得判 vanished（防"点击后立即变化"误判降级/放行）
                if baseline_seen is None:
                    pass
                elif not found:
                    if baseline_seen is False:
                        self._emit("verify_degraded",
                                   detail=f"verify:{template}:never_seen",
                                   context={"template": template,
                                            "reason": "signal never matched before vanish"
                                                      "（视频帧模板恒不中——验证降级）"})
                    return True
            elif expected == "present" and found:
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

    # ---------- 地图传送（抄 Fhoe-Rail 传送链） ----------

    def map_transfer(self, portal, abort_check=None):
        """地图传送：打开地图 → 模板序列点击（传送点）→ 点传送 → 等加载。

        portal 定义（portals.json，kind=map_transfer）：
          steps: [{"template": "Fhoe:map_index_0.png", "threshold": 0.9}, ...]
            "Fhoe:" 前缀 = m7 的 Fhoe-Rail/picture 资产（地图索引/传送点/transfer）；
            无前缀 = 知识包 templates 目录。
          load_wait: 传送后等待秒数（地图加载）。
        返回 bool。任何一步模板未命中 → 失败（可重试）。
        """
        import time
        steps = portal.get("steps") or []
        if not steps:
            return False
        # 1. 打开地图（m7 config hotkey_map，默认 M）
        hotkey = self._hotkey_map()
        r = self.input.press_key(hotkey, wait_time=1.2)
        if not r.success:
            return False
        if abort_check and abort_check():
            return False
        # 2. 依次点击模板（传送点/索引/transfer）
        for step in steps:
            tpl_ref = step.get("template", "")
            threshold = step.get("threshold", 0.9)
            path = self._resolve_fhoe_template(tpl_ref)
            if path is None:
                return False
            hit = self._click_template_hit(path, threshold)
            if not hit:
                return False
            time.sleep(0.8)
            if abort_check and abort_check():
                return False
        # 3. 等加载（固定等待 + 画面稳定）
        load_wait = float(portal.get("load_wait", 8))
        self._wait_loading(load_wait, abort_check)
        return True

    def _hotkey_map(self):
        """m7 config.yaml 的 hotkey_map（打开地图键，默认 m）。"""
        try:
            from runtime.platform.windows.game_launcher import m7_config_value
            v = m7_config_value("hotkey_map")
            if v:
                return str(v)
        except Exception:
            pass
        return "m"

    def _resolve_fhoe_template(self, template_ref):
        """模板引用解析："Fhoe:xxx.png" → 项目内 assets/fhoe（数据内化——
        资产已从 March7thAssistant/3rdparty/Fhoe-Rail/picture 拷入）；否则知识包。"""
        if template_ref.startswith("Fhoe:"):
            name = template_ref[len("Fhoe:"):]
            pic = (Path(__file__).resolve().parent.parent.parent
                   / "assets" / "fhoe" / name)
            return str(pic) if pic.exists() else None
        return self._resolve_template_path(template_ref)

    def _click_template_hit(self, path, threshold=0.9):
        """模板命中即点击（Fhoe 语义：找到目标点一下）。返回是否成功。"""
        from runtime.input.template_backend import TemplateMatcher
        try:
            tm = TemplateMatcher(threshold=threshold)
            hit = tm.locate(path)
        except Exception:
            return False
        if hit is None:
            return False
        _, cx, cy = hit
        r = self.input.click(cx, cy)
        return bool(r.success)

    def _wait_loading(self, seconds, abort_check=None):
        """传送后等待：固定秒 + 期间画面逐步稳定（简易加载等待）。"""
        import time
        from runtime.pixel_diff import images_different
        vision = getattr(getattr(self, "driver", None), "vision", None)
        deadline = time.time() + seconds
        last = None
        stable_rounds = 0
        while time.time() < deadline:
            if abort_check and abort_check():
                return
            time.sleep(1.5)
            if vision is None:
                continue
            try:
                shot = vision.take_screenshot()
                cur = shot[0] if shot else None
            except Exception:
                cur = None
            if cur is not None and last is not None:
                changed, _ = images_different(last, cur)
                if not changed:
                    stable_rounds += 1
                    if stable_rounds >= 2:
                        return  # 画面稳定 → 加载完成
                else:
                    stable_rounds = 0
            if cur is not None:
                last = cur
