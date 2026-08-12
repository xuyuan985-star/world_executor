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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

from runtime.action_intent import ActionType
from runtime.errors import ErrorCode
from runtime.events.schema import make_event
from runtime.execution import ExecutionResult
from runtime.observation import Observation
from runtime.planner import Planner
from runtime.state_machine import Event, State, StateMachine

# #44：workflow 步骤类型白名单——未知类型 fail-fast（F3），
# 知识包注入面收窄：步骤只能是 move/visual_guided_move/interact/verify，
# 无其他执行语义；trajectory = 点位关联的录制轨迹回放（机关/复杂路径）
STEP_TYPES = {"move", "visual_guided_move", "interact", "verify", "portal",
              "trajectory"}
# Bug 83：单目标恢复/重试尝试硬上限（防 recover→retry 无限循环）
MAX_TARGET_ATTEMPTS = 3

# S10：watchdog 判定"执行卡死"的事件静默上限（verify 30s + 重试余量）
WATCHDOG_STALL_SECONDS = 120


class SessionWatchdog(threading.Thread):
    """S10 Supervisor 轻量版：监控事件流活跃度。

    executor 若阻塞（如验证循环无 abort 钩子），事件流静默超过阈值 →
    deadlock_detected 事件 + 置位；主循环每 step 检查置位即中断。
    独立线程、daemon，随 mission 启停。
    """

    def __init__(self, bus, execution_id, stall_seconds=WATCHDOG_STALL_SECONDS):
        super().__init__(daemon=True, name="SessionWatchdog")  # #163
        self.bus = bus
        self.execution_id = execution_id
        self.stall_seconds = stall_seconds
        self._stop_event = threading.Event()  # 勿用 _stop：覆盖 Thread._stop 方法
        self._last_activity = time.monotonic()
        self.tripped = False
        self._sub = None
        if bus is not None:
            # 审查 P1：订阅存句柄——stop() 必须取消订阅（否则每次 run_mission
            # 往 bus._subscribers 追加一条永不清除的强引用，长期运行无界增长）
            self._sub = lambda e: self.touch()
            bus.subscribe(self._sub)

    def touch(self):
        self._last_activity = time.monotonic()

    def run(self):
        while not self._stop_event.is_set():
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
        self._stop_event.set()
        if self.bus is not None and self._sub is not None:
            try:
                self.bus.unsubscribe(self._sub)  # 审查 P1：取消订阅防泄漏
            except Exception:
                pass
        # #7：确保 watchdog 线程退出（防泄漏）——不能 join 自己（自停场景）
        import threading
        if threading.current_thread() is not self:
            self.join(timeout=2)


class TargetRecord:
    """#38：单目标生命周期记录——attempts/结果/失败分类，会话结束可统计。

    Bug 380：补 duration/retry 维度（统计不只 success/fail）。
    """

    def __init__(self, target_id):
        self.target_id = target_id
        self.status = "pending"
        self.attempts = 0
        self.last_error = None
        self.category = None
        self.started_at = None
        self.duration_s = None
        self.retry_count = 0

    def mark_start(self):
        # Bug 628：耗时计时用 monotonic（NTP/改时间不干扰 duration）
        import time
        self.started_at = time.monotonic()

    def mark_finish(self):
        import time
        if self.started_at is not None:
            self.duration_s = round(time.monotonic() - self.started_at, 1)

    def to_dict(self):
        return {"target": self.target_id, "status": self.status,
                "attempts": self.attempts, "error": self.last_error,
                "category": self.category, "duration_s": self.duration_s,
                "retry_count": self.retry_count}


class WorkflowOrchestrator:
    def __init__(self, pkg, bus=None, execution_id=None, use_vlm=True,
                 natural_mode=True, stop_check=None):
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
        self._foreground_retried = False  # BUG-24：失焦激活只尝试一次
        self._last_beat_time = None  # 回放心跳时间节流（0.6.0 第3轮）
        self.foreground_check = True      # BUG-24：前台锁定（mock 环境关闭）
        self._stop_check = stop_check     # #6：外部停止信号（RuntimeAPI.stop）
        # #20-7：决策层——Planner 输入 Observation 输出 ActionIntent（零坐标）
        self.planner = Planner()
        self.observer = None  # 观察器（FakeObserver/真实观察器，由调用方注入）
        self.vision_gate = None  # Sprint B：内容可信度门（None=跳过）
        # 三大策略配置：遇怪处理（auto=自动战斗 / kill=秒杀角色战技键）
        self.battle_strategy = "auto"

    @property
    def executor(self):
        if self._executor is None:
            from runtime.step_executor import RealExecutor
            # S13：seed 由 execution_id 派生——同 id 重跑可复现自然性延迟
            # Bug 625：hash() 受 PYTHONHASHSEED 影响跨进程不稳定——改 sha256
            import hashlib
            seed = int(hashlib.sha256(
                (self.execution_id or "default").encode()).hexdigest()[:8], 16)
            self._executor = RealExecutor(self.pkg, self.bus, self.execution_id,
                                          self.use_vlm, self.natural_mode, seed,
                                          abort_check=self._aborted)
        return self._executor

    def _emit(self, event_type, **kw):
        if self.bus is not None:
            self.bus.publish(make_event(event_type, self.execution_id, **kw))

    @staticmethod
    def _evidence_from_observation(observation):
        """Observation → VisionEvidence（视觉决策快照用）。"""
        from runtime.vision_gate import VisionEvidence, OCREvidence, VLMEvidence
        return VisionEvidence(
            ocr=OCREvidence(texts=list(observation.text or [])),
            vlm=VLMEvidence(scene=observation.ui_state, room=observation.room,
                            confidence=observation.confidence),
            frame_quality=getattr(observation, "frame_quality", None),
        )

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
            # 自伤防护：executor 点击前挂起 monitor 光标检测
            self.executor.monitor = self._monitor
        except Exception:
            # Bug 626：安全模块失败不能静默——告警事件 + 记录（继续执行但可知晓）
            import logging
            logging.getLogger("runtime.orchestrator").exception(
                "EmergencyMonitor 启动失败——继续执行但无人机介入保护")
            self._monitor = None
            try:
                self._emit("fail_recorded",
                           detail="F3:emergency_monitor_failed",
                           context={"category": "F3", "target": None,
                                    "error": "emergency_monitor_failed"})
            except Exception:
                pass

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
        # 修复（0.6.0 F10 急停审查）：目标开始前检查外部停止
        if self._stop_check is not None and self._stop_check():
            return False
        record = self._records.get(target_id) or TargetRecord(target_id)
        self._records[target_id] = record
        record.status = "running"
        record.attempts += 1
        record.mark_start()  # Bug 380：耗时统计起点
        try:
            return self._run_target_inner(target_id, record)
        except Exception:
            # Bug 82：未预期异常 → 显式失败（线程不裸退出），状态机走 ABORT
            import logging
            logging.getLogger("runtime.orchestrator").exception(
                "run_target crashed: %s", target_id)
            record.status = "failed"
            record.last_error = "orchestrator_crash"
            record.category = "F1_EXEC"
            # Bug 627：崩溃现场快照（状态/目标/最近事件——可复盘）
            try:
                snap = {"state": self._machine.state.name
                        if self._machine is not None else None,
                        "target": target_id}
                import json as _json
                from pathlib import Path as _P
                crash_dir = _P(__file__).resolve().parent.parent / "failure_reports" / "orchestrator_crash"
                crash_dir.mkdir(parents=True, exist_ok=True)
                (crash_dir / f"{target_id}_{int(time.time() * 1000)}.json").write_text(
                    _json.dumps(snap, ensure_ascii=False, indent=2),
                    encoding="utf-8")
            except Exception:
                pass
            self._emit("fail_recorded",
                       detail=f"F1_EXEC:crash:{target_id}",
                       context={"category": "F1_EXEC", "target": target_id,
                                "error": "orchestrator_crash"})
            self._emit("target_progress",
                       context={"target": target_id, "status": "failed",
                                "reason": "orchestrator_crash", "category": "F1_EXEC"})
            if self._machine is not None and self._machine.state not in (State.DONE, State.ABORT):
                self._machine.on(Event.ABORT_REQUEST, "orchestrator crash")
            self._interrupted(target_id)
            return False
        finally:
            record.mark_finish()  # Bug 380：所有结束路径统一计时

    def _run_target_inner(self, target_id, record):
        wf = self.pkg.workflow(target_id)
        if wf is None:
            # 自定义轨迹目标（指挥台"自定义"地图）：目标 id = 轨迹文件名，
            # knowledge/trajectories/<id>.json 存在 → 构造纯轨迹 workflow
            from pathlib import Path as _P
            traj_dir = _P(__file__).resolve().parent.parent \
                / "knowledge" / "trajectories"
            if (traj_dir / f"{target_id}.json").exists():
                wf = {"target_id": target_id,
                      "steps": [{"type": "trajectory",
                                 "file": f"{target_id}.json"}]}
            else:
                record.status = "failed"
                record.last_error = "workflow_not_found"
                record.category = "F3"
                self._emit("fail_recorded",
                           detail=f"F3:no_workflow:{target_id}",
                           context={"category": "F3", "target": target_id,
                                    "error": "workflow_not_found"})
                return False
        steps = wf.get("steps", [])
        # 一键混合执行：点位有关联轨迹（chests.json 的 trajectory 字段）→
        # 前插 trajectory 步骤——录制的点位用轨迹回放，其余走模板/坐标，
        # 用户零选择（视频预处理点位 + 手动录制点位混合执行）
        if not any(s.get("type") == "trajectory" for s in steps):
            for chest in (self.pkg.chests or []):
                if chest.get("id") == target_id and chest.get("trajectory"):
                    steps = [{"type": "trajectory",
                              "file": chest["trajectory"]}] + steps
                    break

        def logger(prev, new, action, reason):
            self._emit("state_changed", from_state=prev, to_state=new,
                       detail=reason, context={"target": target_id, "action": action})

        self._machine = StateMachine(self.execution_id, target_id, logger=logger)
        self._machine.on(Event.START, "orchestrator start")
        self._machine.on(Event.ROOM_MATCH, "fixed position (M1-A)")

        for idx, step in enumerate(steps):
            if self._stop_check is not None and self._stop_check():
                record.status = "failed"
                record.last_error = "user_stopped"
                self._emit("target_progress",
                           context={"target": target_id, "status": "failed",
                                    "reason": "user stopped", "category": "F3"})
                return False
            if self._emergency_paused():
                self._human_interrupted(target_id)
                return False
            # S10：watchdog 判卡死 → 中断（不再盲目等待）
            if self._stall_detected():
                self._stall_abort(target_id)
                return False
            # 遇怪策略（三大策略之一）：每步前检测战斗界面——秒杀角色按
            # 战技键（kill）或开自动战斗（auto）→ 等结算回大地图
            if not self._handle_battle_if_needed():
                self._emit("target_progress",
                           context={"target": target_id, "status": "failed",
                                    "reason": "battle_unresolved",
                                    "category": "F4_VISION"})
                self._interrupted(target_id)
                return False
            # S9：窗口消失/丢失 → 系统不可用，停止执行（不再黑屏点击）
            window_problem = self._window_lost()
            if window_problem == "window_not_foreground" and not self._foreground_retried:
                # BUG-24：窗口存在但失焦——按 C.4 协议尝试激活一次再继续
                try:
                    from runtime.win_capture import set_foreground_with_retry
                    from runtime.drivers.march7th.window import find_game_window
                    game = find_game_window()
                    if game:
                        set_foreground_with_retry(game["hwnd"])
                except Exception:
                    pass
                self._foreground_retried = True
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
                    for attempt in range(retry):
                        record.retry_count += 1  # Bug 380：重试次数统计
                        # Bug 106：指数退避（1s→2s→4s）——失败重试不高频占资源
                        # Bug 144：退避可中断（stop/abort 期间不再空等）
                        # 0.6.0：退避上限 1.5s——F10 急停更快生效（原 4s）
                        if not self._interruptible_wait(
                                min(2 ** attempt, 1.5)):
                            break
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

    def _interruptible_wait(self, seconds):
        """Bug 144：分段可中断等待——stop/abort 期间立即返回 False（不空等）。"""
        import time
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self._stop_check is not None and self._stop_check():
                return False
            if self._emergency_paused() or self._stall_detected():
                return False
            time.sleep(0.1)
        return True

    # ---------- 三大策略（遇怪/未解锁/机关） ----------

    def _handle_battle_if_needed(self, max_rounds=6):
        """遇怪策略：检测战斗界面 → 秒杀或自动战斗 → 等结算回大地图。

        有秒杀角色（config battle_strategy=kill）：按战技键（m7
        hotkey_technique，默认 e）秒杀大地图怪；
        无秒杀角色：按自动战斗键（m7 hotkey_auto_battle，默认 v）
        挂机等结算。检测词与 _ensure_game_ready 共用（回合/波次/胜利/失败）。
        """
        executor = self.executor
        try:
            vision = executor.driver.vision
            for i in range(max_rounds):
                texts = []
                try:
                    for t, _ in vision.ocr_lines():
                        texts.append(t)
                except Exception:
                    return True  # 无 OCR 能力 → 不干预
                joined = "".join(texts)
                in_battle = any(k in joined for k in
                                ("回合", "波次", "战斗"))
                settled = any(k in joined for k in ("胜利", "失败", "挑战完成"))
                if not in_battle and not settled:
                    return True  # 不在战斗
                if in_battle:
                    strategy = self.battle_strategy
                    if strategy == "kill":
                        # 秒杀角色：战技键
                        key = self._m7_key("hotkey_technique", "e")
                        executor.input.press_key(key, wait_time=0.6)
                    else:
                        # 自动战斗
                        key = self._m7_key("hotkey_auto_battle", "v")
                        executor.input.press_key(key, wait_time=0.6)
                    self._emit("state_changed", detail="battle:engage",
                               context={"action": "battle",
                                        "strategy": strategy, "key": key})
                if not self._interruptible_wait(3):
                    return False  # 等待期间 stop/emergency/stall → 退出战斗循环
            return False  # 超轮次未结算
        except Exception:
            return True  # 异常不阻断（保守放行）

    def _m7_key(self, key_name, default):
        """读 m7 config 的按键配置（hotkey_technique/auto_battle 等）。"""
        try:
            from runtime.platform.windows.game_launcher import m7_config_value
            v = m7_config_value(key_name)
            if v:
                return str(v)
        except Exception:
            pass
        return default

    def _check_map_locked(self):
        """未解锁检测：OCR 提示词 → 该地图未解锁（跳过而非反复失败）。"""
        executor = self.executor
        try:
            vision = executor.driver.vision
            texts = []
            for t, _ in vision.ocr_lines():
                texts.append(t)
            joined = "".join(texts)
            for k in ("尚未解锁", "未解锁", "需完成", "解锁该区域",
                      "暂时无法", "无法传送"):
                if k in joined:
                    return k
        except Exception:
            pass
        return None

    def _check_mechanism(self):
        """机关检测：交互提示含机关类词 → 该目标需机关操作（回放/人工）。"""
        executor = self.executor
        try:
            vision = executor.driver.vision
            texts = []
            for t, _ in vision.ocr_lines():
                texts.append(t)
            joined = "".join(texts)
            for k in ("机关", "开关", "启动装置", "压力板", "解谜"):
                if k in joined:
                    return k
        except Exception:
            pass
        return None

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
        # 审查 P1-3：步骤非 dict（畸形知识数据）→ 显式失败而非 AttributeError 崩溃
        if not isinstance(step, dict):
            self._emit("fail_recorded", detail=f"F3:bad_step:{idx}",
                       context={"category": "F3", "target": wf.get("target_id"),
                                "error": f"bad_step:{type(step).__name__}"})
            return ExecutionResult(success=False, error=f"bad_step:{type(step).__name__}",
                                   retryable=False, category="F3")
        step_type = step.get("type")
        if step_type not in STEP_TYPES:  # #44：白名单，拒绝未知步骤类型
            self._emit("fail_recorded", detail=f"F3:unknown_step:{step_type}",
                       context={"category": "F3", "target": wf.get("target_id"),
                                "error": f"unknown_step:{step_type}"})
            return ExecutionResult(success=False, error=f"unknown_step:{step_type}",
                                   retryable=False, category="F3")
        if step_type == "move":
            return self._step_move(step)
        if step_type == "portal":
            return self._step_portal(step)
        if step_type == "trajectory":
            return self._step_trajectory(step)
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

    def _step_trajectory(self, step):
        """轨迹回放步骤（点位关联的手动录制轨迹——机关/复杂路径）。

        workflow/chest: {"type": "trajectory", "file": "traj_xxx.json"}
        回放按录制灵敏度（game_sensitivity 记录在轨迹内，不换算）；
        游戏窗口缺失时轨迹点击/视角按 1920x1080 默认基准（近似）。
        """
        fname = step.get("file")
        if not fname:
            return ExecutionResult(success=False, error="trajectory:no_file",
                                   retryable=False, category="F3")
        from pathlib import Path
        traj_dir = Path(__file__).resolve().parent.parent / "knowledge" / "trajectories"
        tpath = traj_dir / fname
        if not tpath.exists():
            return ExecutionResult(success=False, error=f"trajectory:missing:{fname}",
                                   retryable=False, category="F3")
        try:
            from runtime.input.replayer import TrajectoryReplayer
            from runtime.drivers.march7th.window import find_game_window
            # 回放前检查外部停止（F10 在启动期按下 → 不开始播放）
            if self._stop_check is not None and self._stop_check():
                return ExecutionResult(success=False, error="trajectory:stopped",
                                       retryable=False, category="F1")
            game = find_game_window()
            hwnd = game["hwnd"] if game else None
            # 灵敏度换算接线（0.6.0 第3轮：原 sensitivity=None 恒不换算——
            # 设置项接入前，默认用录制值；未来设置 REPLAY_SENSITIVITY
            # 后自动按 录制/回放 比例缩放视角）
            replay_sens = None
            try:
                from config.settings import get as _cfg_get
                _v = _cfg_get("REPLAY_SENSITIVITY", "")
                if _v:
                    f = float(_v)
                    # 校验：0/负数会导致 replayer 除零（0.6.0 第4轮）
                    if f > 0:
                        replay_sens = f
            except Exception:
                pass
            rp = TrajectoryReplayer(game_hwnd=hwnd, sensitivity=replay_sens)
            rp.load(str(tpath))
            # 回放期间暂停 EmergencyMonitor 鼠标检测（回放自身的鼠标移动
            # 会触发 cursor_moved 误判"人工介入"→ 后续目标全被误杀）；
            # 回放结束恢复。审查 blocking（0.6.0 全量）。
            monitor = getattr(self, "_monitor", None)
            if monitor is not None:
                try:
                    monitor.suspend_mouse()
                except Exception:
                    pass

            def _progress(i, total):
                # 回放心跳：防 SessionWatchdog 120s 静默误判卡死。
                # 修复（0.6.0 第3轮）：时间节流——原 i%20 过滤在长等待
                # 期间 i 不变 → 心跳全被吞 → watchdog trip + _stall_detected
                # 误中断回放（与 abort_check 并入互相连锁成新 bug）
                if self._last_beat_time is None or \
                        time.monotonic() - self._last_beat_time >= 15:
                    self._last_beat_time = time.monotonic()
                    self._emit("state_changed",
                               detail=f"trajectory_progress:{i}/{total}",
                               context={"target": getattr(
                                   self, "_current_target", None),
                                   "file": fname})
            try:
                ok = rp.replay(
                    abort_check=(self._abort_condition
                                 if hasattr(self, "_abort_condition")
                                 else (self._stop_check
                                       if self._stop_check is not None
                                       else (lambda: False))),
                    progress=_progress)
            finally:
                if monitor is not None:
                    try:
                        monitor.resume_mouse()
                    except Exception:
                        pass
            if not ok:
                return ExecutionResult(success=False, error="trajectory:aborted",
                                       retryable=False, category="F1")
            self._emit("state_changed", detail="trajectory_done",
                       context={"target": getattr(self, "_current_target", None),
                                "file": fname})
            return ExecutionResult(success=True)
        except Exception as e:
            return ExecutionResult(success=False,
                                   error=f"trajectory:err:{type(e).__name__}:{e}",
                                   retryable=False, category="F1")

    def _abort_condition(self):
        """统一中止条件（0.6.0 F10 急停审查）：人工介入 / 卡死检测 /
        外部停止（F10）——原多处 abort_check 只查前两者，F10 后 verify
        最长阻塞 30s、portal 8s+ 才生效。"""
        if self._stop_check is not None and self._stop_check():
            return True
        return self._emergency_paused() or self._stall_detected()

    def _step_portal(self, step):
        """地图传送步骤（抄 Fhoe-Rail 传送链：打开地图→点传送点→点传送→等加载）。

        workflow: {"type": "portal", "portal_id": "tp_xxx"}
        portal 定义在 portals.json：kind=map_transfer 时走地图传送
        （steps 模板序列 + load_wait），kind=loading 时走原有门传送。
        """
        pid = step.get("portal_id")
        portal = self.pkg.portal(pid) if pid else None
        if portal is None:
            return ExecutionResult(success=False, error=f"portal_not_found:{pid}",
                                   retryable=False, category="F3")
        if portal.get("kind") == "map_transfer":
            ok = self.executor.map_transfer(
                portal, abort_check=self._abort_condition)
        else:
            ok = self.executor.portal_transition(
                portal, wait_base=portal.get("load_wait", 8))
        # portal_transition 可能返回 ExecutionResult（无验证模板 fail-closed）——
        # 透传原结果（准确错误码/retryable），不一律转成 portal_failed（可重试）
        if isinstance(ok, ExecutionResult):
            return ok
        if ok is True:
            # 未解锁检测：传送后画面出现解锁提示词 → 标记该地图 locked
            locked = self._check_map_locked()
            if locked:
                self._emit("state_changed", detail=f"map_locked:{locked}",
                           context={"action": "map_locked",
                                    "portal": pid, "hint": locked})
                return ExecutionResult(
                    success=False, error=f"map_locked:{locked}",
                    retryable=False, category="F3")
            return ExecutionResult(success=True, category="F2")
        return ExecutionResult(success=False, error="portal_failed",
                               retryable=True, category="F2_VERIFY")

    def _step_vgm(self, step, wf):
        ticks = step.get("ticks", 3)
        step_seconds = step.get("step_seconds", 2)
        # #42：VGM 结果以真实定位为准——目标从未出现即失败，不污染状态机
        # #41：循环可中断（emergency / watchdog stall）
        return self.executor.move_visual_guided(
            f"{wf.get('target_id')} 附近的可互动宝箱实体", ticks, step_seconds,
            abort_check=self._abort_condition)

    def _step_interact(self, step, wf):
        tid = wf.get("target_id")
        # 机关检测（三大策略之一）：交互提示含机关词 → 该目标需机关操作
        # （当前自动处理不可行——回放路线/人工）→ 明确标记跳过
        mech = self._check_mechanism()
        if mech:
            self._emit("state_changed", detail=f"mechanism:{mech}",
                       context={"action": "mechanism", "target": tid,
                                "hint": mech})
            return ExecutionResult(
                success=False, error=f"requires_mechanism:{mech}",
                retryable=False, category="F3")
        # BUG-15：backend 层 max_retries 固定 1（单次查找）——动作重试由
        # orchestrator 唯一控制（双层 retry 会放大物理点击次数）
        result = self.executor.interact_template(
            tid, threshold=step.get("threshold", 0.8),
            max_retries=1)
        if not result.success:
            return result
        self._machine.on(Event.TARGET_VISIBLE, "target visible")
        self._machine.on(Event.TARGET_VERIFIED, "interact clicked")
        return result

    def _step_verify(self, step):
        # 7×24 稳定性：验证步骤绝不假成功——signal 缺失/验证模板缺失
        # 都是"无法验证"，必须显式失败（目标 failed → mission 继续下一目标），
        # 不能标记通过（否则开箱未成却记 done——误操作源头）
        signal = step.get("signal")
        if not signal:
            return ExecutionResult(
                success=False, error="verify_no_signal",
                retryable=False, category="F2_VERIFY")
        template = f"{signal}.png"
        if not self.pkg.template_exists(template):
            return ExecutionResult(
                success=False, error="verify_template_missing",
                retryable=False, category="F2_VERIFY")
        expected = step.get("expected", "vanished")
        timeout = step.get("timeout", 30)
        # #41：验证循环可中断（emergency / watchdog stall 立即退出）
        ok = self.executor.verify_signal(
            template, expected, timeout,
            abort_check=self._abort_condition)
        if ok:
            # 审查 P0：只有 INTERACTING 态才有 INTERACT_OK 迁移——NAVIGATING 等
            # 状态下 verify 通过不应推进状态机（否则 ValueError 非法迁移崩溃）
            if self._machine.state == State.INTERACTING:
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
                     "confidence": observation.confidence},
                frame_confidence=getattr(observation, "frame_confidence", None))
            if not gate["valid"]:
                if gate.get("mode") == "observe":
                    # Sprint B-6：OCR 强但 VLM 弱 → 观察模式（不执行，可重试）
                    self._emit("observation",
                               context={"observer": observation.source,
                                        "target": target,
                                        "gate": "VISION_OBSERVE",
                                        "reason": gate["reason"],
                                        **observation.to_context()})
                    return self.executor.execute_intent(
                        self.planner.plan_wait("vision observe (ocr strong, vlm weak)"))
                # B-08：视觉决策快照落盘（复盘"执行前看到什么"）
                try:
                    from runtime.vision_gate import dump_vision_decision
                    dump_vision_decision(str(ROOT / "failure_reports/vision"),
                                         observation.frame_id,
                                         self._evidence_from_observation(observation),
                                         {"allowed": False, "reason": gate["reason"],
                                          "score": gate.get("score"),
                                          "signals": gate.get("signals")})
                except Exception:
                    pass
                self._emit("observation",
                           context={"observer": observation.source,
                                    "target": target,
                                    "gate": "VISION_UNTRUSTED",
                                    "reason": gate["reason"],
                                    **observation.to_context()})
                self._emit("vision_blocked",  # B-15：可独立过滤的视觉拒绝事件
                           context={"target": target, "reason": gate["reason"],
                                    "score": gate.get("score"),
                                    "signals": gate.get("signals")})
                return ExecutionResult(success=False, error="vision_untrusted",
                                       retryable=False, category="F4_VISION",
                                       code=ErrorCode.VISION_UNTRUSTED)
            vision_ok = True
            vision_conf = gate["confidence"]
            # 审查 P1-8：内置 hash 跨进程不稳定（同帧两进程 id 不同——
            # 证据关联/replay 追踪失效）。用 sha256 稳定派生。
            import hashlib as _hl
            _seed = f"{observation.frame_id}:{time.time()}".encode()
            evidence_id = f"evid_{_hl.sha256(_seed).hexdigest()[:6]}"
        intent = self.planner.decide(observation, target)
        if intent.action == ActionType.WAIT.value:
            self._emit("observation",
                       context={"observer": observation.source,
                                "target": target,
                                **observation.to_context()})
        # Sprint B-2：gate 通过 → 视觉证明写入意图（ActionGuard 消费）
        if vision_ok and intent.action != ActionType.WAIT.value:
            from dataclasses import replace
            # BUG-12：evidence 注册到 guard.evidence_store——TTL 过期检查
            # 依赖它（此前只生成 id 不注册，_evidence_age 恒 None → 过期失效）
            guard_store = getattr(self.executor.guard, "evidence_store", None)
            if guard_store is None and hasattr(self.executor.guard, "evidence_store"):
                self.executor.guard.evidence_store = {}
                guard_store = self.executor.guard.evidence_store
            if guard_store is not None:
                import time as _t
                # BUG-047：evidence 生命周期——注册时清理过期（TTL×2）+ 容量上限
                guard_store[evidence_id] = {"timestamp": _t.time(),
                                            "confidence": vision_conf}
                cutoff = _t.time() - (getattr(self.executor.guard, "max_age", 3.0) * 2)
                stale = [k for k, v in guard_store.items()
                         if v.get("timestamp", 0) < cutoff]
                for k in stale:
                    guard_store.pop(k, None)
                if len(guard_store) > 500:
                    # LRU 近似：删最早注册的一批
                    for k in sorted(guard_store, key=lambda k: guard_store[k].get("timestamp", 0))[:100]:
                        guard_store.pop(k, None)
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

    def _ensure_foreground(self):
        """#72：任务开始时主动把游戏窗口拉到前台（抄 March7th window 激活逻辑）。

        操作前激活窗口（C.4 协议）——不等失焦检测，开始即抢占前台。
        """
        if not self.foreground_check:
            return True
        try:
            from runtime.drivers.march7th.window import find_game_window
            from runtime.win_capture import set_foreground_with_retry
            game = find_game_window()
            if game is None:
                return False
            set_foreground_with_retry(game["hwnd"])
            import ctypes
            fg = ctypes.windll.user32.GetForegroundWindow()
            return fg == game["hwnd"]
        except Exception:
            return False

    def _replay_only(self, target_ids):
        """纯轨迹回放目标判定：所有目标都是 trajectory 步骤（自定义地图
        录制的操作回放）——不需要界面归一化/前台激活/环境门槛。

        判定：workflow 存在且 steps 全为 trajectory；或无 workflow 但
        knowledge/trajectories/<id>.json 存在（自定义轨迹目标）。
        """
        from pathlib import Path as _P
        traj_dir = _P(__file__).resolve().parent.parent / "knowledge" / "trajectories"
        for tid in target_ids:
            wf = self.pkg.workflow(tid)
            if wf is not None:
                steps = wf.get("steps") or []
                if not steps or not all(
                        s.get("type") == "trajectory" for s in steps):
                    return False
            elif not (traj_dir / f"{tid}.json").exists():
                return False
        return True

    def run_mission(self, target_ids, emergency=True):
        # 修复（0.6.0 F10 急停审查）：启动阶段检查外部停止——
        # F10 在启动期按下（回放尚未开始）→ 直接返回，不启动任何环节
        if self._stop_check is not None and self._stop_check():
            self._emit("state_changed", detail="stopped_at_start",
                       context={"action": "user_stopped"})
            return {}, []
        if emergency:  # #10：emergency=False 不启动安全线程
            self.start_emergency()
        self.start_watchdog()
        try:
            # 纯轨迹回放：跳过前台激活与界面归一化（无需游戏画面——
            # 0.6.0：纯播放秒开，不再走 OCR 环境链）
            replay_only = self._replay_only(target_ids)
            # 修复（0.6.0）：纯回放也先拉游戏置顶——回放移动鼠标/按键
            # 必须发给游戏窗口；跳过 _ensure_game_ready（OCR 界面归一化
            # 15s 静默）但 _ensure_foreground 仅 0.5s，不牺牲秒开
            self._foreground_retried = False
            self._ensure_foreground()
            if not replay_only:
                # 借鉴 March7th Screen._handle_autotry：任务开始前界面归一化——
                # 用户在战斗/菜单/弹窗/剧情中开始任务时，先 ESC/点弹窗退出到
                # 可执行画面（m7"识别不到界面就 ESC 重试"的适配版）。失败抛异常
                # → crashed（诚实；空结果返回会误报 all_done——已知坑）。
                self._ensure_game_ready()
            else:
                self._emit("state_changed",
                           detail="replay_only:skip_ready",
                           context={"action": "replay_only"})
            # Bug 533：目标去重（同目标不重复执行——保持输入顺序）
            target_ids = list(dict.fromkeys(target_ids))
            results = {}
            for tid in target_ids:
                if self._aborted():
                    break
                # Bug 83：恢复/重试循环防失控——单目标尝试次数硬上限
                if self._records.get(tid) and self._records[tid].attempts >= MAX_TARGET_ATTEMPTS:
                    record = self._records[tid]
                    record.status = "failed"
                    record.last_error = "max_attempts_exceeded"
                    record.category = "F3"
                    self._emit("fail_recorded",
                               detail=f"F3:max_attempts:{tid}",
                               context={"category": "F3", "target": tid,
                                        "error": "max_attempts_exceeded"})
                    self._emit("target_progress",
                               context={"target": tid, "status": "failed",
                                        "reason": "max_attempts_exceeded",
                                        "category": "F3"})
                    results[tid] = False
                    continue
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

    # 借鉴 March7th Screen._handle_autotry 的界面归一化关键词（OCR 命中即处理）：
    # 弹窗（前情提要→稍后再看）、断线/异常（点确定重连）、战斗/结算（ESC 退出）、
    # 菜单/设置（ESC 关闭）。关键词保守——宁可漏判（下轮 ESC 兜底）不可误点。
    _READY_POPUP = ("稍后再看", "前情提要", "跳过剧情")
    _READY_EXCEPTION = ("重新连接", "连接失败", "连接中断", "重试")
    _READY_BATTLE = ("波次", "回合", "胜利", "失败", "挑战者")
    _READY_MENU = ("设置", "返回标题", "退出游戏")

    def _ensure_game_ready(self, max_rounds=6):
        """任务开始前界面归一化（m7 _handle_autotry 适配版）：

        战斗/菜单/弹窗/剧情等非可执行界面 → ESC 或点弹窗按钮退出，直到
        OCR 无可执行信号。m7 语义："识别不到目标界面就 ESC 重试 + 弹窗
        处理"；我们用 OCR 关键词判"非可执行状态"（无界面图资产）。
        每轮 2s 等待画面变化；超轮次/无 OCR 能力 → 抛 RuntimeError 或
        放行（mock 环境无 ocr_lines → 放行，真实链路自然验证）。
        """
        executor = self.executor
        try:
            for i in range(max_rounds):
                if self._stop_check is not None and self._stop_check():
                    raise RuntimeError("任务开始前被停止（界面归一化中）")
                # 进度反馈（0.6.0：界面归一化静默 15s=用户感知"没动静"）
                self._emit("state_changed",
                           detail=f"ready:checking:{i + 1}/{max_rounds}",
                           context={"action": "ready_check"})
                try:
                    texts = [t for t, _ in executor.driver.vision.ocr_lines()]
                except AttributeError:
                    return  # mock/无 OCR 能力 → 放行（不阻断测试与降级链路）
                except Exception:
                    return  # OCR 异常 → 放行（后面观察链会自然失败，不在此误拦）
                joined = "".join(texts)
                if any(k in joined for k in self._READY_POPUP):
                    self._emit("state_changed", detail="ready:popup_dismissed",
                               context={"action": "ready_popup"})
                    executor.click_text("稍后再看", max_retries=1)
                    self._interruptible_wait(2)
                    continue
                if any(k in joined for k in self._READY_EXCEPTION):
                    self._emit("state_changed", detail="ready:relogin",
                               context={"action": "ready_relogin"})
                    executor.click_text("确定", max_retries=1)
                    self._interruptible_wait(20)  # 重连等待（m7 同款 20s）
                    continue
                if any(k in joined for k in self._READY_BATTLE):
                    self._emit("state_changed", detail="ready:battle_exit",
                               context={"action": "ready_battle"})
                    executor.input.press_key("esc", wait_time=2)
                    continue
                if any(k in joined for k in self._READY_MENU):
                    self._emit("state_changed", detail="ready:menu_exit",
                               context={"action": "ready_menu"})
                    executor.input.press_key("esc", wait_time=2)
                    continue
                # 无任何"非可执行"信号 → 画面就绪
                self._emit("state_changed", detail="ready:ok",
                           context={"action": "ready_ok", "rounds": i + 1})
                return
            raise RuntimeError(
                "游戏画面未就绪：战斗/菜单/弹窗多次尝试未能退出（" 
                f"{max_rounds} 轮）——请手动回到主城后重试")
        except RuntimeError:
            raise
        except Exception as e:
            import logging
            logging.getLogger("runtime.orchestrator").warning(
                "界面归一化异常（按就绪处理）: %s", e)

    def _window_lost(self):
        """S9：窗口消失/尺寸异常/失焦 → 返回原因，正常返回 None。

        BUG-24：窗口存在但不在前台 → window_not_foreground（点击会打到别的窗口）。
        foreground_check=False（mock 环境）时跳过前台判定。
        """
        try:
            from runtime.drivers.march7th.window import find_game_window
            game = find_game_window()
            if game is None:
                return "window_lost"
            w, h = game["client"]
            if w < 500 or h < 500:
                return f"window_too_small:{w}x{h}"
            # BUG-24：前台锁定（操作前游戏必须在最前——防点到浏览器）
            if self.foreground_check:
                import ctypes
                fg = ctypes.windll.user32.GetForegroundWindow()
                if fg != game["hwnd"]:
                    return "window_not_foreground"
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
        # 修复（0.6.0 F10 急停审查）：外部 stop 信号（RuntimeAPI.stop/F10）
        # 也是中止条件——原只查内部 ABORT 状态，F10 后目标循环继续跑
        if self._stop_check is not None and self._stop_check():
            return True
        return self._machine is not None and self._machine.state == State.ABORT

    def _emergency_paused(self):
        """EmergencyMonitor 已触发人工介入 → 停止继续执行（M1-A 安全）。"""
        return self._monitor is not None and self._monitor.is_paused()

    def _human_interrupted(self, target_id):
        # #42：紧急介入先做安全清理（esc + 释放可能卡住的按键），再中断
        # BUG-037：安全路径禁止静默失败——释放失败必须 critical 记录
        try:
            self.executor.emergency_stop()
        except Exception:
            import logging
            logging.getLogger("runtime.orchestrator").critical(
                "EMERGENCY STOP 失败——按键/鼠标可能未释放！", exc_info=True)
            try:  # 二级兜底：win32 release_all
                backend = getattr(self.executor.input, "backend", None) \
                    or getattr(self.executor.input, "backends", None)
                if hasattr(self.executor.input, "release_all"):
                    self.executor.input.release_all()
            except Exception:
                pass
        self._emit("target_progress",
                   context={"target": target_id, "status": "failed",
                            "reason": "human_interrupt", "category": "EMERGENCY"})
        if self._machine.state not in (State.DONE, State.ABORT):
            self._machine.on(Event.ABORT_REQUEST, "human intervention")
        self._interrupted(target_id)
