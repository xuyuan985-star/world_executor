"""M1-A 编排器：workflow → 状态机 → executor 的流水线（企划 v0.12.2）。

- EmergencyMonitor 随 run 启停；human_intervention → ABORT_REQUEST + 目标 interrupted。
- 失败（retry 用尽）→ EVENT_INTERRUPTED → 一次 recovery → 仍败 → fail_recorded + target failed。
- #32：只重试 retryable 失败（模板缺/低置信/非幂等动作不重试）。
- #42：紧急介入先按 esc + 释放按键（防卡键），再中断。
- #38/#48：TargetRecord 跟踪每目标生命周期；run_mission 返回 (results, completed)。
- 状态机联动语义见企划 v0.12.2 §2.2。
"""
import threading
import time

from runtime.action_intent import ActionIntent, ActionMethod, ActionType
from runtime.events.schema import make_event
from runtime.execution import ExecutionResult
from runtime.observation import Observation
from runtime.planner import Planner
from runtime.state_machine import Event, State, StateMachine

TARGET_ALIVE = ("running", "succeeded", "failed")

# #44：workflow 步骤类型白名单——未知类型 fail-fast（F3），
# 知识包注入面收窄：步骤只能是 move/visual_guided_move/interact/verify，无其他执行语义
STEP_TYPES = {"move", "visual_guided_move", "interact", "verify"}

# S10：watchdog 判定"执行卡死"的事件静默上限（verify 30s + 重试余量）
WATCHDOG_STALL_SECONDS = 120


class SessionWatchdog(threading.Thread):
    """S10 Supervisor 轻量版：监控事件流活跃度。

    executor 若阻塞（如验证循环无 abort 钩子），事件流静默超过阈值 →
    deadlock_detected 事件 + 置位；主循环每 step 检查置位即中断。
    独立线程、daemon，随 mission 启停。
    """

    def __init__(self, bus, execution_id, stall_seconds=WATCHDOG_STALL_SECONDS):
        super().__init__(daemon=True)
        self.bus = bus
        self.execution_id = execution_id
        self.stall_seconds = stall_seconds
        self._stop = threading.Event()
        self._last_activity = time.monotonic()
        self.tripped = False
        if bus is not None:
            bus.subscribe(lambda e: self.touch())  # 任何事件都是活跃信号

    def touch(self):
        self._last_activity = time.monotonic()

    def run(self):
        while not self._stop.is_set():
            time.sleep(5)
            if self.tripped:
                continue
            if time.monotonic() - self._last_activity > self.stall_seconds:
                self.tripped = True
                if self.bus is not None:
                    from runtime.events.schema import make_event
                    self.bus.publish(make_event(
                        "deadlock_detected", self.execution_id,
                        detail=f"事件静默 {self.stall_seconds}s，判定执行卡死"))

    def stop(self):
        self._stop.set()


class TargetRecord:
    """#38：单目标生命周期记录——attempts/结果/失败分类，会话结束可统计。"""

    def __init__(self, target_id):
        self.target_id = target_id
        self.status = "pending"
        self.attempts = 0
        self.last_error = None
        self.category = None

    def to_dict(self):
        return {"target": self.target_id, "status": self.status,
                "attempts": self.attempts, "error": self.last_error,
                "category": self.category}


class WorkflowOrchestrator:
    def __init__(self, pkg, bus=None, execution_id=None, use_vlm=True, natural_mode=True):
        self.pkg = pkg
        self.bus = bus
        self.execution_id = execution_id
        self.use_vlm = use_vlm
        self.natural_mode = natural_mode   # #44：False → 确定性执行（delay=0）
        self._executor = None
        self._machine = None
        self._monitor = None
        self._watchdog = None
        self._records = {}
        # #20-7：决策层——Planner 输入 Observation 输出 ActionIntent（零坐标）
        self.planner = Planner()
        self.observer = None  # 观察器（FakeObserver/真实观察器，由调用方注入）
        self.vision_gate = None  # Sprint B：内容可信度门（None=跳过）

    @property
    def executor(self):
        if self._executor is None:
            from runtime.step_executor import RealExecutor
            # S13：seed 由 execution_id 派生——同 id 重跑可复现自然性延迟
            seed = hash(self.execution_id or "default") & 0xFFFFFFFF
            self._executor = RealExecutor(self.pkg, self.bus, self.execution_id,
                                          self.use_vlm, self.natural_mode, seed)
        return self._executor

    def _emit(self, event_type, **kw):
        if self.bus is not None:
            self.bus.publish(make_event(event_type, self.execution_id, **kw))

    # ---------- Emergency ----------

    def start_emergency(self):
        try:
            from runtime.drivers.march7th.window import find_game_window
            from runtime.safety import EmergencyMonitor
            game = find_game_window()
            if game is None:
                return
            self._monitor = EmergencyMonitor(self.bus, self.execution_id, game["hwnd"])
            self._monitor.start()
        except Exception:
            self._monitor = None

    def start_watchdog(self):
        """S10：watchdog 随 mission 启停（独立于窗口，始终可用）。"""
        self._watchdog = SessionWatchdog(self.bus, self.execution_id)
        self._watchdog.start()

    def stop_emergency(self):
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None
        if getattr(self, "_watchdog", None) is not None:
            self._watchdog.stop()
            self._watchdog = None

    # ---------- 主流程 ----------

    def run_target(self, target_id):
        record = self._records.get(target_id) or TargetRecord(target_id)
        self._records[target_id] = record
        record.status = "running"
        record.attempts += 1
        wf = self.pkg.workflow(target_id)
        if wf is None:
            record.status = "failed"
            record.last_error = "workflow_not_found"
            record.category = "F3"
            self._emit("fail_recorded", detail=f"F3:no_workflow:{target_id}",
                       context={"category": "F3", "target": target_id,
                                "error": "workflow_not_found"})
            return False
        steps = wf.get("steps", [])

        def logger(prev, new, action, reason):
            self._emit("state_changed", from_state=prev, to_state=new,
                       detail=reason, context={"target": target_id, "action": action})

        self._machine = StateMachine(self.execution_id, target_id, logger=logger)
        self._machine.on(Event.START, "orchestrator start")
        self._machine.on(Event.ROOM_MATCH, "fixed position (M1-A)")

        for idx, step in enumerate(steps):
            if self._emergency_paused():
                self._human_interrupted(target_id)
                return False
            # S10：watchdog 判卡死 → 中断（不再盲目等待）
            if self._stall_detected():
                self._stall_abort(target_id)
                return False
            # S9：窗口消失/丢失 → 系统不可用，停止执行（不再黑屏点击）
            window_problem = self._window_lost()
            if window_problem:
                self._system_failure(target_id, window_problem)
                return False
            result = self._run_step(step, idx, wf)
            if not result.success:
                # #32：只有 retryable 失败才重试（非幂等动作/模板缺失/低置信 → 直接失败）
                retry = int(step.get("retry", 1) or 1)
                recovered = False
                if result.retryable:
                    for _ in range(retry):
                        time.sleep(1.0)
                        self._retry_transition()
                        result = self._run_step(step, idx, wf)
                        if result.success:
                            recovered = True
                            break
                if not recovered:
                    category = result.category
                    record.status = "failed"
                    record.last_error = result.error or "step_failed"
                    record.category = category
                    self._emit("fail_recorded",
                               detail=f"{category}:step:{step.get('type')}:{target_id}",
                               context={"category": category, "target": target_id,
                                        "step": step.get("type"),
                                        "error": result.error or "step_failed"})
                    self._emit("target_progress",
                               context={"target": target_id, "status": "failed",
                                        "reason": f"step[{idx}] {step.get('type')} failed",
                                        "category": category})
                    self._machine.on(Event.ABORT_REQUEST, "step failed")
                    self._interrupted(target_id)
                    return False
            self._progress(target_id, idx, len(steps))

        record.status = "succeeded"
        self._emit("target_progress", context={"target": target_id, "status": "done"})
        return True

    def _retry_transition(self):
        """失败重试的状态机迁移：只走当前状态合法的事件。"""
        st = self._machine.state
        if st in (State.VERIFYING, State.INTERACTING):
            self._machine.on(Event.INTERACT_AGAIN, "retry")
        else:
            if st != State.EVENT_INTERRUPT:
                self._machine.on(Event.EVENT_INTERRUPTED, "step fail")
            self._machine.on(Event.RECOVER_OK, "retry")

    def _run_step(self, step, idx, wf):
        step_type = step.get("type")
        if step_type not in STEP_TYPES:  # #44：白名单，拒绝未知步骤类型
            self._emit("fail_recorded", detail=f"F3:unknown_step:{step_type}",
                       context={"category": "F3", "target": wf.get("target_id"),
                                "error": f"unknown_step:{step_type}"})
            return ExecutionResult(success=False, error=f"unknown_step:{step_type}",
                                   retryable=False, category="F3")
        if step_type == "move":
            return self._step_move(step)
        if step_type == "visual_guided_move":
            return self._step_vgm(step, wf)
        if step_type == "interact":
            return self._step_interact(step, wf)
        if step_type == "verify":
            return self._step_verify(step)
        return ExecutionResult(success=False, error=f"unhandled_step:{step_type}",
                               retryable=False, category="F3")

    def _step_move(self, step):
        lm_id = step.get("target")
        if not lm_id:
            return ExecutionResult(success=False, error="move:no_target",
                                   retryable=False, category="F3")
        # 纯移动步骤不推进状态机：TARGET_VISIBLE 语义由 interact 步骤确认（#36 严格迁移）
        return self.executor.interact_template(lm_id, threshold=0.8)

    def _step_vgm(self, step, wf):
        ticks = step.get("ticks", 3)
        step_seconds = step.get("step_seconds", 2)
        # #42：VGM 结果以真实定位为准——目标从未出现即失败，不污染状态机
        # #41：循环可中断（emergency / watchdog stall）
        return self.executor.move_visual_guided(
            f"{wf.get('target_id')} 附近的可互动宝箱实体", ticks, step_seconds,
            abort_check=lambda: self._emergency_paused() or self._stall_detected())

    def _step_interact(self, step, wf):
        tid = wf.get("target_id")
        result = self.executor.interact_template(
            tid, threshold=step.get("threshold", 0.8),
            max_retries=step.get("retry", 1) + 1)
        if not result.success:
            return result
        self._machine.on(Event.TARGET_VISIBLE, "target visible")
        self._machine.on(Event.TARGET_VERIFIED, "interact clicked")
        return result

    def _step_verify(self, step):
        signal = step.get("signal")
        if not signal:
            return ExecutionResult(success=True, category="F2")
        template = f"{signal}.png"
        if not self.pkg.template_exists(template):
            return ExecutionResult(success=True, category="F2")  # 无模板则跳过
        expected = step.get("expected", "vanished")
        timeout = step.get("timeout", 30)
        # #41：验证循环可中断（emergency / watchdog stall 立即退出）
        ok = self.executor.verify_signal(
            template, expected, timeout,
            abort_check=lambda: self._emergency_paused() or self._stall_detected())
        if ok:
            self._machine.on(Event.INTERACT_OK, "verify passed")
        return ExecutionResult(
            success=ok, error=None if ok else "verify_timeout",
            retryable=not ok, category="F2")

    # ---------- 观察→规划→执行（#20-7 插层通道） ----------

    def observe_act(self, target, observer=None):
        """Observation → Planner → ActionIntent → execute_intent 一条龙。

        observer 未注入时用 self.observer（None → 直接返回失败）。
        不推进状态机（workflow 步骤路径保持原有迁移语义）——
        本通道供自主决策/观察驱动流程使用。
        """
        obs = (observer or self.observer)
        if obs is None:
            return ExecutionResult(success=False, error="no_observer",
                                   retryable=False, category="F3")
        observation = obs.observe()
        if not isinstance(observation, Observation):
            return ExecutionResult(success=False, error="observer:bad_return",
                                   retryable=False, category="F3")
        # Sprint B：VisionGate 内容可信度门——不信任则压低置信，Planner 拒绝行动
        vision_ok = self.vision_gate is not None   # 无 gate → 不写入证明（宽松放行）
        vision_conf = 0.0
        evidence_id = None
        if self.vision_gate is not None:
            gate = self.vision_gate.validate(
                frame_quality=getattr(observation, "frame_quality", None),
                ocr_texts=observation.text,
                vlm={"ui_state": observation.ui_state,
                     "room": observation.room,
                     "confidence": observation.confidence})
            if not gate["valid"]:
                self._emit("observation",
                           context={"observer": observation.source,
                                    "target": target,
                                    "gate": "VISION_UNTRUSTED",
                                    "reason": gate["reason"],
                                    **observation.to_context()})
                return ExecutionResult(success=False, error="vision_untrusted",
                                       retryable=False, category="F4_VISION",
                                       code=ErrorCode.VISION_UNTRUSTED)
            vision_ok = True
            vision_conf = gate["confidence"]
            evidence_id = f"evid_{abs(hash((observation.frame_id, time.time()))) & 0xFFFFFF:06x}"
        intent = self.planner.decide(observation, target)
        if intent.action == ActionType.WAIT.value:
            self._emit("observation",
                       context={"observer": observation.source,
                                "target": target,
                                **observation.to_context()})
        # Sprint B-2：gate 通过 → 视觉证明写入意图（ActionGuard 消费）
        if vision_ok and intent.action != ActionType.WAIT.value:
            from dataclasses import replace
            intent = replace(intent, vision_verified=True,
                             vision_confidence=vision_conf,
                             evidence_id=evidence_id)
        return self.executor.execute_intent(intent)

    # ---------- 辅助 ----------

    def _progress(self, target_id, idx, total):
        self._emit("target_progress",
                   context={"target": target_id, "status": "running",
                            "step": idx + 1, "total": total})

    def _interrupted(self, target_id):
        self._emit("pause_requested", context={"reason": "target_failed",
                                               "detail": target_id})

    # ---------- 会话级（多目标） ----------

    def run_mission(self, target_ids, emergency=True):
        self.start_emergency()
        self.start_watchdog()
        try:
            results = {}
            for tid in target_ids:
                if self._aborted():
                    break
                results[tid] = self.run_target(tid)
            # #48：completed_targets = 本会话实际跑完的目标（不含失败/未执行）
            completed = [tid for tid in target_ids
                         if self._records.get(tid) is not None
                         and self._records[tid].status == "succeeded"]
            return results, completed
        finally:
            self.stop_emergency()

    def session_summary(self):
        """#38：目标生命周期汇总（status/attempts/error/category）。"""
        return {tid: r.to_dict() for tid, r in self._records.items()}

    # ---------- 系统状态（S9/S10） ----------

    @staticmethod
    def _window_lost():
        """S9：窗口消失/尺寸异常 → 返回原因，正常返回 None。"""
        try:
            from runtime.drivers.march7th.window import find_game_window
            game = find_game_window()
            if game is None:
                return "window_lost"
            w, h = game["client"]
            if w < 500 or h < 500:
                return f"window_too_small:{w}x{h}"
        except Exception as e:
            return f"window_check_error:{type(e).__name__}"
        return None

    def _stall_detected(self):
        return getattr(self, "_watchdog", None) is not None and self._watchdog.tripped

    def _stall_abort(self, target_id):
        """S10：执行卡死 → 中断目标（deadlock_detected 已由 watchdog 发出）。"""
        record = self._records.get(target_id)
        if record:
            record.status = "failed"
            record.last_error = "execution_stall"
            record.category = "F3"
        self._emit("target_progress",
                   context={"target": target_id, "status": "failed",
                            "reason": "execution_stall", "category": "F3"})
        if self._machine.state not in (State.DONE, State.ABORT):
            self._machine.on(Event.ABORT_REQUEST, "watchdog stall")
        self._interrupted(target_id)

    def _system_failure(self, target_id, reason):
        """S9：系统不可用（窗口消失等）→ 记 F3_WINDOW，停止本目标。"""
        record = self._records.get(target_id)
        if record:
            record.status = "failed"
            record.last_error = reason
            record.category = "F3_WINDOW"
        self._emit("fail_recorded",
                   detail=f"F3_WINDOW:{reason}:{target_id}",
                   context={"category": "F3_WINDOW", "target": target_id,
                            "error": reason})
        self._emit("target_progress",
                   context={"target": target_id, "status": "failed",
                            "reason": reason, "category": "F3_WINDOW"})
        if self._machine.state not in (State.DONE, State.ABORT):
            self._machine.on(Event.ABORT_REQUEST, "system unavailable")
        self._interrupted(target_id)

    def _aborted(self):
        return self._machine is not None and self._machine.state == State.ABORT

    def _emergency_paused(self):
        """EmergencyMonitor 已触发人工介入 → 停止继续执行（M1-A 安全）。"""
        return self._monitor is not None and self._monitor.is_paused()

    def _human_interrupted(self, target_id):
        # #42：紧急介入先做安全清理（esc + 释放可能卡住的按键），再中断
        try:
            self.executor.emergency_stop()
        except Exception:
            pass
        self._emit("target_progress",
                   context={"target": target_id, "status": "failed",
                            "reason": "human_interrupt", "category": "EMERGENCY"})
        if self._machine.state not in (State.DONE, State.ABORT):
            self._machine.on(Event.ABORT_REQUEST, "human intervention")
        self._interrupted(target_id)
