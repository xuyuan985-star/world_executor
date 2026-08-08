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


class RuntimeAPI:
    def __init__(self, event_bus: EventBus, execution_id=None):
        self.bus = event_bus
        self.execution_id = execution_id
        self._runner = None
        self._thread = None
        self._state = "idle"

    def start_mission(self, spec: MissionSpec, runner_factory=None):
        from runtime import dry_run

        def runner(bus, execution_id):
            from ingest.compiler.validate_graph import validate
            from runtime.knowledge_loader import KnowledgePackage
            from pathlib import Path

            pkg = KnowledgePackage(Path(spec.knowledge_dir))
            errors, _ = validate(pkg, verbose=False)
            if errors:
                bus.publish(make_event("run_finished", execution_id,
                                       context={"result": "invalid", "errors": len(errors)}))
                return "invalid"

            if spec.mode == "real":
                gate = self._gate_check(bus, execution_id, pkg)
                if gate is not None:
                    return gate

            targets = spec.target_ids or [c["id"] for c in pkg.chests]
            self._state = "running"
            bus.publish(make_event("run_started", execution_id,
                                   context={"knowledge": spec.knowledge_dir,
                                            "targets": targets, "mode": spec.mode}))
            if spec.mode == "real":
                from runtime.orchestrator import WorkflowOrchestrator
                orch = WorkflowOrchestrator(pkg, bus=bus, execution_id=execution_id)
                results = orch.run_mission(targets)
                result = "all_done" if all(results.values()) else "some_failed"
            else:
                result = dry_run.dry_run(spec.knowledge_dir, targets, bus=bus,
                                         execution_id=execution_id)
            self._state = "done"
            bus.publish(make_event("run_finished", execution_id,
                                   context={"result": result}))
            return result

        import uuid

        self.execution_id = self.execution_id or f"run{uuid.uuid4().hex[:4]}"
        self._thread = threading.Thread(target=lambda: runner(self.bus, self.execution_id), daemon=True)
        self._thread.start()
        return self.execution_id

    def _gate_check(self, bus, execution_id, pkg):
        """G3 门槛：health 全绿才进 real mission（企划 v0.12.2 §2.4）。

        含 Capability Gate（第四批审查 P0）：window/capture/ocr/vlm + foreground/admin + input L0/L1，
        L2 失败即拦——避免"点击失败→重试→点击失败→F1"死循环（根因：权限/前台未满足）。
        """
        from runtime.health import check_health
        h = check_health()
        cap = h["capability"]
        critical = ["window", "capture", "ocr", "vlm", "foreground", "admin"]
        fails = [k for k in critical if not cap.get(k)] + [k for k in ("input_l0", "input_l1")
                                                           if not cap.get(k)]
        if cap.get("input_l2") is False:
            fails.append("input_l2")
        if fails:
            bus.publish(make_event("run_finished", execution_id,
                                   context={"result": "gate_blocked",
                                            "fails": fails,
                                            "errors": h["errors"]}))
            self._state = "gate_blocked"
            return "gate_blocked"
        return None

    def pause(self):
        self._state = "paused"
        return self._state

    def request_pause_human(self, reason="unknown_state"):
        self._state = "paused_for_human"
        self.bus.publish(make_event("pause_requested", self.execution_id,
                                    context={"reason": reason}))
        return self._state

    def resume_check(self, checks=None):
        self._state = "resume_check"
        self.bus.publish(make_event("resume_checked", self.execution_id,
                                    context={"checks": checks or []}))
        return self._state

    def resume(self):
        self._state = "running"
        return self._state

    def stop(self):
        self._state = "stopped"
        return self._state

    def inspect(self):
        return {"state": self._state, "execution_id": self.execution_id}

    def recent_events(self, limit=50):
        return self.bus.replay(self.execution_id)[-limit:]
