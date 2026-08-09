import threading
from dataclasses import dataclass
from typing import Optional

from runtime import db
from runtime.events.bus import EventBus
from runtime.events.schema import WorldEvent, make_event


@dataclass
class MissionSpec:
    knowledge_dir: str
    target_ids: Optional[list] = None
    mode: str = "dry"  # dry | real（企划 v0.12.2 门槛 G3 前置）
    natural_mode: bool = True  # #44：False → 确定性执行（delay=0，可复现测试）
    requires: Optional[list] = None  # S15：任务必需能力（缺则拒绝启动），默认 G3 critical 集


class RuntimeAPI:
    # Bug 79：合法状态集——非法字符串进不来（UI/执行不进入未知状态）
    # P1-008：与 MissionState 枚举对齐（runtime/state.py 统一状态体系）
    VALID_STATES = {"idle", "running", "done", "crashed", "stopped",
                    "gate_blocked", "paused", "paused_for_human",
                    "resume_check", "invalid"}

    @property
    def mission_state(self):
        """P1-008：统一枚举状态（UI/外部消费用，替代裸字符串）。"""
        from runtime.state import normalize_state
        return normalize_state(self._state)

    def __init__(self, event_bus: EventBus, execution_id=None):
        self.bus = event_bus
        self.execution_id = execution_id
        self._runner = None
        self._thread = None
        self._set_state("idle")
        self._pending_requires = None
        self._stop_event = threading.Event()  # #6：真停止信号

    def _set_state(self, new_state):
        """Bug 79：状态写入统一入口——非法状态抛 ValueError（防漂移）。"""
        if new_state not in self.VALID_STATES:
            raise ValueError(f"非法状态: {new_state!r}（合法: {sorted(self.VALID_STATES)}）")
        self._state = new_state

    def start_mission(self, spec: MissionSpec, runner_factory=None):
        from runtime import dry_run
        self._pending_requires = spec.requires
        self._stop_event.clear()  # #6

        def runner(bus, execution_id):
            from ingest.compiler.validate_graph import validate
            from runtime.knowledge_loader import KnowledgePackage
            from pathlib import Path

            # GUI-1：knowledge_dir 绝对化（进程 cwd 可能被 March7th 探测线程
            # chdir 污染——相对路径会解析到 M7 导致 validate 报缺文件）
            knowledge_dir = self._absolute_knowledge_dir(spec.knowledge_dir)
            pkg = KnowledgePackage(Path(knowledge_dir))
            errors, _ = validate(pkg, verbose=False)
            if errors:
                bus.publish(make_event("run_finished", execution_id,
                                       context={"result": "invalid", "errors": len(errors)}))
                self._set_state("idle")  # Bug 5：清理状态，下次点击不受污染
                self._runner = None
                self._thread = None
                return "invalid"

            if spec.mode == "real":
                gate = self._gate_check(bus, execution_id, pkg)
                if gate is not None:
                    return gate

            targets = spec.target_ids or [c["id"] for c in pkg.chests]
            self._set_state("running")
            input_mode = getattr(orch.executor.input, "name", "real") \
                if spec.mode == "real" and "orch" in dir() else "dry"
            bus.publish(make_event("run_started", execution_id,
                                   context={"knowledge": knowledge_dir,
                                            "targets": targets, "mode": spec.mode,
                                            "input_mode": input_mode,  # Bug 8：observe_only 可见
                                            "knowledge_hash": pkg.package_hash()}))
            try:
                if self._stop_event.is_set():
                    return "stopped"
                if spec.mode == "real":
                    from runtime.orchestrator import WorkflowOrchestrator
                    orch = WorkflowOrchestrator(pkg, bus=bus,
                                                execution_id=execution_id,
                                                use_vlm=True,
                                                stop_check=self._stop_event.is_set)
                    results, completed = orch.run_mission(targets)
                    result = ("stopped" if self._stop_event.is_set()
                              else ("all_done" if all(results.values())
                                    else "some_failed"))
                    bus.publish(make_event("mission_summary", execution_id,
                                           context={"results": results,
                                                    "completed_targets": completed,
                                                    "records": orch.session_summary()}))
                else:
                    result = dry_run.dry_run(knowledge_dir, targets, bus=bus,
                                             execution_id=execution_id)
                self._set_state("done")
                bus.publish(make_event("run_finished", execution_id,
                                       context={"result": result}))
                return result
            except Exception as e:  # #9：real 执行异常 → 显式 run_finished(crashed)，GUI 不永久卡运行
                import traceback
                traceback.print_exc()
                self._set_state("crashed")
                bus.publish(make_event("run_finished", execution_id,
                                       context={"result": "crashed",
                                                "error": str(e)}))
                return "crashed"

        import uuid

        self.execution_id = self.execution_id or f"run{uuid.uuid4().hex[:4]}"
        # GUI-2：runner_factory 注入（诊断/测试用）——此前参数存在但被忽略
        make_runner = runner_factory or (lambda bus_, eid: runner(bus_, eid))
        self._thread = threading.Thread(
            target=lambda: make_runner(self.bus, self.execution_id), daemon=True,
            name="RuntimeAPI-runner")  # #163：线程命名（日志可辨识）
        self._thread.start()
        return self.execution_id

    @staticmethod
    def _absolute_knowledge_dir(knowledge_dir):
        """相对知识目录 → 基于 world_executor 根绝对化（不受进程 cwd 影响）。"""
        from pathlib import Path
        p = Path(knowledge_dir)
        if p.is_absolute():
            return str(p)
        root = Path(__file__).resolve().parent.parent.parent
        return str(root / knowledge_dir)

    def _gate_check(self, bus, execution_id, pkg):
        """G3 门槛：health 全绿才进 real mission（企划 v0.12.2 §2.4）。

        含 Capability Gate（第四批审查 P0）：window/capture/ocr/vlm + foreground/admin + input L0/L1，
        L2 失败即拦——避免"点击失败→重试→点击失败→F1"死循环（根因：权限/前台未满足）。
        #15：spec.requires 可追加任务必需能力键。
        """
        from runtime.health import check_health
        from runtime.capability import detect_capability
        h = check_health()
        cap = h["capability"]
        critical = ["window", "capture", "ocr", "vlm", "foreground", "admin"]
        fails = [k for k in critical if not cap.get(k)] + [k for k in ("input_l0", "input_l1")
                                                           if not cap.get(k)]
        if cap.get("input_l2") is False:
            fails.append("input_l2")
        for req in (self._pending_requires or []):
            if req not in cap or not cap.get(req):
                fails.append(req)
        if fails:
            # 目标 4：能力报告——区分 OBSERVE_ONLY（可观测但输入被拦）与 BLOCKED（观测不可用）
            cap_report = detect_capability(h)
            bus.publish(make_event("run_finished", execution_id,
                                   context={"result": "gate_blocked",
                                            "fails": fails,
                                            "mode": cap_report.mode,
                                            "reasons": cap_report.reasons,
                                            "errors": h["errors"]}))
            self._set_state("gate_blocked")
            return "gate_blocked"
        return None

    def pause(self):
        self._set_state("paused")
        return self._state

    def request_pause_human(self, reason="unknown_state"):
        self._set_state("paused_for_human")
        self.bus.publish(make_event("pause_requested", self.execution_id,
                                    context={"reason": reason}))
        return self._state

    def resume_check(self, checks=None):
        self._set_state("resume_check")
        self.bus.publish(make_event("resume_checked", self.execution_id,
                                    context={"checks": checks or []}))
        return self._state

    def resume(self):
        self._set_state("running")
        return self._state

    @property
    def state(self):
        """公开状态（Bug 24：GUI 不直接读私有 _state）。"""
        return self._state

    def stop(self):
        # #6：真停止——置信号；orchestrator 每 step 检查 stop_check 即中断
        self._stop_event.set()
        # Bug 80：停止即清理运行上下文（防下次启动残留旧任务状态）
        self._runner = None
        self._thread = None
        self._set_state("stopped")
        return self._state

    def inspect(self):
        return {"state": self._state, "execution_id": self.execution_id}

    def recent_events(self, limit=50):
        return self.bus.replay(self.execution_id)[-limit:]
