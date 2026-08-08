"""M1-A 编排器：workflow → 状态机 → executor 的流水线（企划 v0.12.2）。

- EmergencyMonitor 随 run 启停；human_intervention → ABORT_REQUEST + 目标 interrupted。
- 失败（retry 用尽）→ EVENT_INTERRUPTED → 一次 recovery → 仍败 → fail_recorded + target failed。
- 状态机联动语义见企划 v0.12.2 §2.2。
"""
import threading
import time

from runtime.decision.action import ActionIntent
from runtime.events.schema import make_event
from runtime.state_machine import Event, State, StateMachine


class WorkflowOrchestrator:
    def __init__(self, pkg, bus=None, execution_id=None, use_vlm=True):
        self.pkg = pkg
        self.bus = bus
        self.execution_id = execution_id
        self.use_vlm = use_vlm
        self._executor = None
        self._machine = None
        self._monitor = None

    @property
    def executor(self):
        if self._executor is None:
            from runtime.step_executor import RealExecutor
            self._executor = RealExecutor(self.pkg, self.bus, self.execution_id, self.use_vlm)
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

    def stop_emergency(self):
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None

    # ---------- 主流程 ----------

    def run_target(self, target_id):
        wf = self.pkg.workflow(target_id)
        if wf is None:
            self._emit("fail_recorded", detail=f"F3:no_workflow:{target_id}",
                       context={"category": "F3", "target": target_id,
                                "error": "workflow_not_found"})
            return False
        steps = wf.get("steps", [])
        self._machine = StateMachine(self.execution_id, target_id, logger=None)
        self._machine.on(Event.START, "orchestrator start")
        self._machine.on(Event.ROOM_MATCH, "fixed position (M1-A)")

        for idx, step in enumerate(steps):
            ok = self._run_step(step, idx, wf)
            if not ok:
                retry = int(step.get("retry", 1) or 1)
                recovered = False
                for _ in range(retry):
                    time.sleep(1.0)
                    self._retry_transition()
                    ok = self._run_step(step, idx, wf)
                    if ok:
                        recovered = True
                        break
                if not recovered:
                    category = self._classify(step)
                    self._emit("fail_recorded",
                               detail=f"{category}:step:{step.get('type')}:{target_id}",
                               context={"category": category, "target": target_id,
                                        "step": step.get("type"), "error": "step_failed"})
                    self._emit("target_progress",
                               context={"target": target_id, "status": "failed",
                                        "reason": f"step[{idx}] {step.get('type')} failed",
                                        "category": category})
                    self._machine.on(Event.ABORT_REQUEST, "step failed")
                    self._interrupted(target_id)
                    return False
            self._progress(target_id, idx, len(steps))

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
        ex = self.executor
        if step_type == "move":
            return self._step_move(step)
        if step_type == "visual_guided_move":
            return self._step_vgm(step, wf)
        if step_type == "interact":
            return self._step_interact(step, wf)
        if step_type == "verify":
            return self._step_verify(step)
        self._emit("fail_recorded", detail=f"F3:unknown_step:{step_type}",
                   context={"category": "F3", "target": wf.get("target_id"),
                            "error": f"unknown_step:{step_type}"})
        return False

    def _step_move(self, step):
        lm_id = step.get("target")
        if not lm_id:
            return False
        return self.executor.interact_template(lm_id, threshold=0.8)

    def _step_vgm(self, step, wf):
        ticks = step.get("ticks", 3)
        step_seconds = step.get("step_seconds", 2)
        return self.executor.move_visual_guided(
            f"{wf.get('target_id')} 附近的可互动宝箱实体", ticks, step_seconds)

    def _step_interact(self, step, wf):
        tid = wf.get("target_id")
        ok = self.executor.interact_template(
            tid, threshold=step.get("threshold", 0.8),
            max_retries=step.get("retry", 1) + 1)
        if not ok:
            return False
        self._machine.on(Event.TARGET_VISIBLE, "target visible")
        self._machine.on(Event.TARGET_VERIFIED, "interact clicked")
        return True

    def _step_verify(self, step):
        signal = step.get("signal")
        if not signal:
            return True
        template = f"{signal}.png"
        if not self.pkg.template_exists(template):
            return True  # 无模板则跳过（真机知识包补齐后生效）
        expected = step.get("expected", "vanished")
        timeout = step.get("timeout", 30)
        ok = self.executor.verify_signal(template, expected, timeout)
        if ok:
            self._machine.on(Event.INTERACT_OK, "verify passed")
        return ok

    # ---------- 辅助 ----------

    @staticmethod
    def _classify(step):
        t = step.get("type")
        if t in ("interact", "move"):
            return "F1"
        if t in ("visual_guided_move", "verify"):
            return "F2"
        return "F3"

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
        try:
            results = {}
            for tid in target_ids:
                if self._aborted():
                    break
                results[tid] = self.run_target(tid)
            return results
        finally:
            self.stop_emergency()

    def _aborted(self):
        return self._machine is not None and self._machine.state == State.ABORT
